"""Real PostgreSQL acceptance for original rows, saved settings and first use."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql

from app import db, dashboard_metrics as metrics, file_library as library, agent_tools, sql_executor
from app.exceptions import AppException
from app.metric_definitions import MetricDefinition
from app.sample_workspace import prepare_sample
from app.widget_saves import ensure_widget_saves
from .test_file_library import live, upload, selection  # noqa: F401

CSV = b'paid_at,amount,method\n2026-09-01,100000.01,card\n2026-09-02,200000.02,card\n2026-09-02,-50000.00,card\n2026-09-03,80000.03,cash\n'


def ready(live, monkeypatch):
    monkeypatch.setattr(metrics, '_connect', live.connect)
    monkeypatch.setattr(sql_executor, '_connect', live.connect)
    with live.connect() as conn:
        conn.execute('''CREATE TABLE dashboard_widgets (id uuid PRIMARY KEY,user_id uuid,project_id uuid,widget_type text,
            title text,widget_data jsonb,layout jsonb,created_at timestamptz DEFAULT now(),
            refresh_interval_seconds integer DEFAULT 0,next_refresh_at timestamptz,refresh_failures integer DEFAULT 0)''')
    ensure_widget_saves()
    file = upload(live, content=CSV)
    return library.prepare_file(live.user,file['file_id'],live.store)


def test_original_scope_is_immutable_and_persists_saved_settings(live, monkeypatch):
    file = ready(live,monkeypatch)
    request = {**selection(file),'scope':'original_file'}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _:library.resolve_references(live.user,live.store,[request],confirmed=True),range(3)))
    refs = results[0]
    assert len({r[0]['table_id'] for r in results}) == 1
    original, ledger = refs[0]['table_id'],file['bindings'][0]['table_id']
    assert original != ledger
    assert refs[0]['row_count'] == 4
    assert library.resolve_references(live.user,live.store,refs,confirmed=True)[0]['table_id'] == original
    assert [str(t['id']) for t in db.list_table_metas(live.store,live.user)] == [ledger]
    assert len(library.get_record(live.user,file['file_id'])['bindings']) == 1
    definition = MetricDefinition(table_id=original,column='amount',unit='KRW')
    saved = metrics.create_saved_metric(live.store,live.user,metrics.CreateMetricRequest(title='원본 매출',definition=definition,refresh_interval_seconds=3600,save_key='original:one'))
    assert saved['widget_data']['value'] == '330000.06'
    with live.connect() as conn:
        conn.execute(sql.SQL('INSERT INTO {}(paid_at,amount,method) VALUES (%s,%s,%s)').format(sql.Identifier(db.get_user_table_name(live.user,ledger))),('2026-09-04',Decimal('30000.09'),'card'))
    def recalc():
        with live.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT * FROM dashboard_widgets WHERE id=%s FOR UPDATE',(saved['id'],))
            return metrics.refresh_locked(conn,cur,cur.fetchone(),saved['id'],live.user,live.store)
    data,error = recalc()
    assert error is None and data['value'] == '330000.06'
    assert data['unit'] == 'KRW' and data['scope_label'] == '파일 원본만'
    assert data['analysis_sources'][0]['file_id'] == file['file_id']
    assert metrics.preview_saved_metric(live.store,live.user,MetricDefinition(table_id=ledger,column='amount'))['value'] == '360000.15'
    for query in ['INSERT INTO {}(amount) VALUES(1)','UPDATE {} SET amount=0','DELETE FROM {}','TRUNCATE {}']:
        with pytest.raises(psycopg.Error), live.connect() as conn:
            conn.execute(sql.SQL(query).format(sql.Identifier(db.get_user_table_name(live.user,original))))
    with pytest.raises(AppException): db.delete_table_meta(original,live.user)
    with pytest.raises(AppException): db.update_table_meta(original,live.user,name='mutable')
    executor = agent_tools.ToolExecutor(live.user,live.store,library_refs=refs)
    assert len(executor._tables) == 1 and str(executor._tables[0]['id']) == original
    assert executor.execute('insert_rows','{}')['error'] == 'library_scope'
    queried = executor.execute('query_data',json.dumps({'table_name':refs[0]['query_table_name'],'operation':'sum','value_column':'amount'}))
    assert 'error' not in queried,queried
    assert '330000.06' in json.dumps(queried,default=str)
    library.remove_file(live.user,file['file_id'])
    with pytest.raises(HTTPException): library.resolve_references(live.user,live.store,[request],confirmed=True)
    assert recalc()[0]['value'] == '330000.06'  # exclusion retains existing saved evidence
    with pytest.raises(HTTPException): metrics.preview_saved_metric(live.other,live.user,definition)
    with pytest.raises(HTTPException): metrics.preview_saved_metric(live.store,live.stranger,definition)


def test_invalid_scope_and_changed_original_fail_closed(live):
    file = upload(live,content=CSV)
    file = library.prepare_file(live.user,file['file_id'],live.store)
    with pytest.raises(HTTPException): library.resolve_references(live.user,live.store,[{**selection(file),'scope':'anything'}],confirmed=True)
    row = library.get_record(live.user,file['file_id'])
    target = Path(row['storage_key']).resolve()
    assert target.is_relative_to(live.storage._local_root.resolve())
    target.write_bytes(b'amount\n1\n')
    with pytest.raises(HTTPException) as exc:
        library.resolve_references(live.user,live.store,[{**selection(file),'scope':'original_file'}],confirmed=True)
    assert exc.value.status_code == 409
    with live.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM table_meta WHERE original_file_id IS NOT NULL').fetchone()['n'] == 0


def test_sample_setup_retries_and_accounts_are_isolated(live):
    before = db.list_projects(live.user)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _:prepare_sample(live.user),range(3)))
    assert len({str(r['project']['id']) for r in results}) == 1
    assert len({r['file']['file_id'] for r in results}) == 1
    sample = results[0]
    assert str(sample['project']['id']) not in {str(p['id']) for p in before}
    assert sample['file']['bindings'][0]['row_count'] == 8
    assert prepare_sample(live.stranger)['file']['file_id'] != sample['file']['file_id']
    response = live.client.post('/api/library/files/sample-workspace')
    assert response.status_code == 200,response.text
    assert response.json()['file']['file_id'] == sample['file']['file_id']


def test_count_unit_is_not_currency():
    from uuid import uuid4
    with pytest.raises(ValueError): MetricDefinition(table_id=uuid4(),operation='count',unit='KRW')


def test_new_optional_unit_preserves_older_save_fingerprints():
    import hashlib
    from uuid import uuid4
    from app.widget_saves import fingerprint
    definition = MetricDefinition(table_id=uuid4(),column='amount').model_dump(mode='json')
    old = {k:v for k,v in definition.items() if k != 'unit'}
    before = {'title':'매출','definition':old,'refresh_interval_seconds':0}
    legacy_digest = hashlib.sha256(json.dumps(before,sort_keys=True,ensure_ascii=False,default=str,separators=(',',':')).encode()).hexdigest()
    assert fingerprint({**before,'definition':definition}) == legacy_digest
    assert fingerprint({**before,'definition':{**definition,'unit':'KRW'}}) != legacy_digest


def test_formula_operand_units_cannot_contradict_their_source():
    from uuid import uuid4
    from app.metric_definitions import FormulaOperand, GroupedFormulaOperand
    definition = {'table_id':uuid4(),'operation':'sum','column':'amount','unit':'KRW'}
    with pytest.raises(ValueError): FormulaOperand(label='매출',definition=definition,unit='count')
    with pytest.raises(ValueError): GroupedFormulaOperand(label='매출',definition={**definition,'group_by':'method'},unit='count')
