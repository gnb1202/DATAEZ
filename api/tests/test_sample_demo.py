"""Sample resets and presets must survive retries without modifying other data."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from psycopg import sql

from app import db, sample_workspace as sample
from app.dashboard_metrics import CreateMetricRequest, create_saved_metric
from .test_file_library import live  # noqa: F401
from .test_file_scopes import ready


def test_presets_are_exact_original_scoped_and_replay_partial_failure(live, monkeypatch):
    ready(live, monkeypatch)
    workspace = sample.prepare_sample(live.user)
    pid = str(workspace['project']['id'])
    import app.dashboard_metrics as metrics
    real = metrics.create_saved_metric
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('response lost during setup')
        return real(*args)
    monkeypatch.setattr(metrics, 'create_saved_metric', interrupted)
    with pytest.raises(RuntimeError):
        sample.prepare_dashboard(live.user, pid)
    monkeypatch.setattr(metrics, 'create_saved_metric', real)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: sample.prepare_dashboard(live.user, pid), range(3)))
    assert len({tuple(w['id'] for w in r['widgets']) for r in results}) == 1
    widgets = results[0]['widgets']
    assert widgets[0]['widget_data']['value'] == '690200'
    assert [(r['dimension'], r['value']) for r in widgets[1]['widget_data']['data']] == [
        ('2026-09-01','164500'), ('2026-09-02','190000'), ('2026-09-03','139800'), ('2026-09-04','195900')]
    assert [(r['dimension'], r['value']) for r in widgets[2]['widget_data']['data']] == [('card','582700'), ('cash','107500')]
    assert all(w['widget_data']['scope_label'] == '파일 원본만' for w in widgets)
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM dashboard_widgets').fetchone()['n'] == 3
        conn.execute("UPDATE dashboard_widgets SET title='내가 바꾼 제목', layout=%s::jsonb WHERE id=%s",
                     (json.dumps({'x':6,'y':2,'w':6,'h':8}), widgets[0]['id']))
    sample.prepare_dashboard(live.user, pid)
    with live.connect() as conn:
        w = conn.execute('SELECT * FROM dashboard_widgets WHERE id=%s', (widgets[0]['id'],)).fetchone()
        assert w['title'] == '내가 바꾼 제목' and w['layout']['h'] == 8


def test_restart_preserves_regular_and_old_sample_and_other_account(live, monkeypatch):
    file = ready(live, monkeypatch)
    normal = create_saved_metric(live.store, live.user, CreateMetricRequest(title='실제 가게',
        definition={'table_id':file['bindings'][0]['table_id'], 'column':'amount'}))
    before = sample.prepare_sample(live.user)
    other = sample.prepare_sample(live.stranger)
    pid = str(before['project']['id'])
    sample.prepare_dashboard(live.user, pid)

    def snapshot():
        with live.connect() as conn:
            data = {name: conn.execute(f'SELECT * FROM {name} ORDER BY id').fetchall()
                    for name in ('projects', 'files', 'table_meta', 'dashboard_widgets')}
            data['transactions'] = [{'table_id':row['id'], 'rows':conn.execute(
                sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(db.get_user_table_name(str(row['user_id']),str(row['id']))))).fetchall()}
                for row in data['table_meta']]
            data['original_bytes'] = [{'file_id':row['id'], 'bytes':live.storage.read_bytes(row['storage_key'])} for row in data['files']]
            return data
    original = snapshot()
    request = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: sample.restart_sample(live.user,pid,request), range(3)))
    new = results[0]
    assert len({r['file']['file_id'] for r in results}) == 1
    assert str(new['project']['id']) != pid and new['file']['file_id'] != before['file']['file_id']
    assert sample.prepare_sample(live.user)['file']['file_id'] == new['file']['file_id']
    assert sample.prepare_sample(live.stranger)['file']['file_id'] == other['file']['file_id']
    after = snapshot()
    for name, rows in original.items():
        assert all(row in after[name] for row in rows), name
    assert any(str(w['id']) == normal['id'] for w in after['dashboard_widgets'])
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM sample_workspace_restarts').fetchone()['n'] == 1


def test_restart_resumes_failed_file_preparation_and_rejects_stale_or_foreign_targets(live, monkeypatch):
    old = sample.prepare_sample(live.user)
    pid, request = str(old['project']['id']), str(uuid4())
    real = sample.prepare_file
    monkeypatch.setattr(sample, 'prepare_file', lambda *args: (_ for _ in ()).throw(RuntimeError('temporary failure')))
    with pytest.raises(RuntimeError):
        sample.restart_sample(live.user, pid, request)
    monkeypatch.setattr(sample, 'prepare_file', real)
    restored = sample.restart_sample(live.user, pid, request)
    assert restored['file']['bindings'][0]['row_count'] == 8
    for owner, target, key in [(live.user,pid,str(uuid4())), (live.user,live.store,str(uuid4())),
                               (live.stranger,pid,request), (live.user,live.store,request)]:
        with pytest.raises(HTTPException) as error:
            sample.restart_sample(owner,target,key)
        assert error.value.status_code == 409
    assert sample.current_sample(live.stranger)['project'] is None


def test_sample_api_status_restart_and_dashboard(live, monkeypatch):
    ready(live, monkeypatch)
    assert live.client.get('/api/library/files/sample-workspace').json() == {'project':None}
    old = live.client.post('/api/library/files/sample-workspace').json()
    pid = old['project']['id']
    assert live.client.post('/api/library/files/sample-workspace/dashboard', json={'project_id':live.store}).status_code == 409
    response = live.client.post('/api/library/files/sample-workspace/dashboard', json={'project_id':pid})
    assert response.status_code == 200, response.text
    assert len(response.json()['widgets']) == 3
    body = {'expected_project_id':pid,'request_id':str(uuid4())}
    response = live.client.post('/api/library/files/sample-workspace/restart', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['project']['id'] != pid
    assert live.client.post('/api/library/files/sample-workspace/restart', json=body).json()['file']['file_id'] == response.json()['file']['file_id']
