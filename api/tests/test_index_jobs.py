"""Real pgvector/outbox transactions; vectors synthetic, provider failure injected."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app import db, rag, index_jobs as jobs, table_imports, ledger_imports
from app.exceptions import AppException
from app.storage import StorageService
from tests.test_rag_postgres import vector_db, DSN, VEC

pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_RAG_TEST_DATABASE_URL for real pgvector')


def table(env):
    _, user, store, *_ = env
    return table_imports.create_imported_table(user, store, '카드 매출', b'amount\n100\n', 'sales.csv', StorageService())


def job(env, *, table_id=None, file_id=None):
    with env[0]() as conn:
        return dict(conn.execute('SELECT * FROM search_index_jobs WHERE table_meta_id=%s OR file_id=%s', (table_id, file_id)).fetchone())


def due(env, target, *, expired=False):
    with env[0]() as conn:
        conn.execute("UPDATE search_index_jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE id=%s", (target['id'],))
        if expired:
            conn.execute("UPDATE search_index_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (target['id'],))


def document(env, text='환불은 방문 1일 전까지 가능합니다.', name='규정.txt'):
    return jobs.register_document(env[1], env[2], name, text.encode(), StorageService())


def test_outbox_is_atomic_with_metadata_and_bootstrap_is_idempotent(vector_db):
    env = vector_db
    with pytest.raises(RuntimeError):
        with env[0]() as conn:
            conn.execute("INSERT INTO table_meta(id,user_id,project_id,name) VALUES(%s,%s,%s,'rolled back')", (str(uuid4()), env[1], env[2]))
            raise RuntimeError('rollback')
    assert jobs.list_jobs(env[1], env[2])['total'] == 0
    meta = table(env)
    claimed = jobs.claim_one()
    jobs.ensure_index_jobs()
    after = job(env, table_id=meta['id'])
    assert after['lease_token'] == claimed['lease_token'] and after['attempts'] == 1
    assert jobs.claim_one() is None


def test_unchanged_content_skips_provider_and_completes_generation(vector_db):
    env = vector_db
    meta = table(env)
    assert jobs.process_one()
    db.update_table_meta(str(meta['id']), env[1], description='')
    with patch.object(rag, 'embed_one') as embed:
        assert jobs.process_one()
        embed.assert_not_called()
    state = job(env, table_id=meta['id'])
    assert state['status'] == 'succeeded' and state['generation'] == state['completed_generation']


def test_retry_backoff_exhaustion_manual_retry_and_redacted_error(vector_db):
    env = vector_db
    meta = table(env)
    jobs.process_one()
    with env[0]() as conn:
        previous = conn.execute('SELECT * FROM schema_embeddings WHERE table_meta_id=%s', (meta['id'],)).fetchone()
    db.update_table_meta(str(meta['id']), env[1], description='새 설명')
    with patch.object(rag, 'embed_one', side_effect=RuntimeError('private api secret')):
        for attempt in range(1, 6):
            assert jobs.process_one()
            state = job(env, table_id=meta['id'])
            assert state['attempts'] == attempt and state['status'] == ('failed' if attempt == 5 else 'retry')
            assert 'secret' not in state['last_error']
            assert jobs.process_one() is False
            if attempt < 5:
                with env[0]() as conn:
                    wait = conn.execute('SELECT extract(epoch FROM next_attempt_at-clock_timestamp()) AS n FROM search_index_jobs WHERE id=%s', (state['id'],)).fetchone()['n']
                assert jobs.RETRY_SECONDS[attempt-1]-5 < wait <= jobs.RETRY_SECONDS[attempt-1]
                due(env, state)
    with env[0]() as conn:
        assert conn.execute('SELECT * FROM schema_embeddings WHERE table_meta_id=%s', (meta['id'],)).fetchone() == previous
    assert not jobs.retry_job(env[1], env[2], str(state['id']))['replayed']
    assert jobs.retry_job(env[1], env[2], str(state['id']))['replayed']
    assert jobs.process_one()
    assert job(env, table_id=meta['id'])['status'] == 'succeeded'


def test_parallel_claim_has_one_owner_and_expired_worker_cannot_write(vector_db):
    env = vector_db
    meta = table(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: jobs.claim_one(), range(2)))
    old = next(c for c in claims if c)
    assert sum(c is not None for c in claims) == 1
    due(env, old, expired=True)
    new = jobs.claim_one()
    assert new['attempts'] == 2 and new['lease_token'] != old['lease_token']
    assert rag.index_schema(env[1], env[2], str(meta['id']), job=old) == 'superseded'
    with env[0]() as conn:
        assert conn.execute('SELECT count(*) AS n FROM schema_embeddings').fetchone()['n'] == 0
    assert rag.index_schema(env[1], env[2], str(meta['id']), job=new) == 'updated'
    jobs._finish_failure(old, 'old', 'old failure')
    assert job(env, table_id=meta['id'])['status'] == 'succeeded'


def test_repeated_crashes_eventually_stop_and_new_change_restarts(vector_db):
    env = vector_db
    meta = table(env)
    for _ in range(5):
        claimed = jobs.claim_one()
        due(env, claimed, expired=True)
    assert jobs.process_one()
    assert job(env, table_id=meta['id'])['status'] == 'failed'
    db.update_table_meta(str(meta['id']), env[1], description='변경 후')
    assert jobs.process_one()
    assert job(env, table_id=meta['id'])['attempts'] == 1


def test_edit_during_embedding_has_no_lock_and_discards_old_content(vector_db):
    env = vector_db
    meta = table(env)
    def change(*a, **kw):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(db.update_table_meta, str(meta['id']), env[1], description='최신 설명').result(timeout=5)
        return VEC
    with patch.object(rag, 'embed_one', side_effect=change):
        jobs.process_one()
    assert job(env, table_id=meta['id'])['status'] == 'pending'
    jobs.process_one()
    with env[0]() as conn:
        assert '최신 설명' in conn.execute('SELECT content FROM schema_embeddings').fetchone()['content']


def test_index_and_completion_rollback_together(vector_db):
    env = vector_db
    meta = table(env)
    with env[0]() as conn:
        conn.execute("ALTER TABLE search_index_jobs ADD CHECK(status<>'succeeded')")
    jobs.process_one()
    with env[0]() as conn:
        assert conn.execute('SELECT count(*) AS n FROM schema_embeddings').fetchone()['n'] == 0
    assert job(env, table_id=meta['id'])['status'] == 'retry'


@pytest.mark.parametrize('resource', ['table', 'project'])
def test_delete_during_embedding_does_not_resurrect_index(vector_db, resource):
    env = vector_db
    meta = table(env)
    def remove(*a, **kw):
        if resource == 'table':
            db.delete_table_meta(str(meta['id']), env[1])
        else:
            db.delete_project(env[2], env[1])
        return VEC
    with patch.object(rag, 'embed_one', side_effect=remove):
        jobs.process_one()
    with env[0]() as conn:
        assert conn.execute('SELECT count(*) AS n FROM schema_embeddings').fetchone()['n'] == 0
    assert job(env, table_id=meta['id'])['status'] == 'cancelled'


def test_document_upload_visible_before_index_and_retry_preserves_old_chunks(vector_db):
    env = vector_db
    doc = document(env)
    assert db.list_project_documents(env[1], env[2])[0]['chunk_count'] == 0
    assert jobs.process_one()
    state = job(env, file_id=doc['file_id'])
    with env[0]() as conn:
        before = conn.execute('SELECT * FROM document_chunks').fetchall()
    jobs.retry_job(env[1], env[2], str(state['id']))
    with patch.object(rag, 'generate_embeddings', side_effect=RuntimeError('offline')):
        jobs.process_one()
    assert job(env, file_id=doc['file_id'])['status'] == 'retry'
    with env[0]() as conn:
        assert conn.execute('SELECT * FROM document_chunks').fetchall() == before
    due(env, state)
    jobs.process_one()
    assert job(env, file_id=doc['file_id'])['status'] == 'succeeded'


@pytest.mark.parametrize('failure,code', [('empty','document_empty'), ('changed','document_changed'), ('missing','document_missing'), ('large','document_too_large')])
def test_bad_document_stops_with_actionable_status(vector_db, monkeypatch, failure, code):
    env = vector_db
    doc = document(env, text='' if failure == 'empty' else '규정입니다.')
    file = db.get_file(env[1], doc['file_id'])
    storage = StorageService()
    if failure == 'changed':
        storage.write_staged(file['storage_key'], b'changed')
    elif failure == 'missing':
        storage.delete_staged(file['storage_key'])
    elif failure == 'large':
        monkeypatch.setattr(jobs, 'MAX_DOCUMENT_CHUNKS', 0)
    jobs.process_one(storage)
    state = job(env, file_id=doc['file_id'])
    assert state['status'] == 'failed' and state['last_error_code'] == code and state['attempts'] == 1
    assert db.list_project_documents(env[1], env[2])[0]['index_status'] == 'failed'
    assert db.delete_file(env[1], doc['file_id'], project_id=env[2])
    assert jobs.list_jobs(env[1], env[2])['total'] == 0


def test_document_expired_worker_and_delete_cannot_restore_old_chunks(vector_db):
    env = vector_db
    doc = document(env)
    old = jobs.claim_one()
    due(env, old, expired=True)
    new = jobs.claim_one()
    assert jobs._document(old, StorageService()) == 0
    assert jobs._document(new, StorageService()) == 1
    state = job(env, file_id=doc['file_id'])
    jobs.retry_job(env[1], env[2], str(state['id']))
    def remove(chunks, **kw):
        assert db.delete_file(env[1], doc['file_id'], project_id=env[2])
        return [VEC for _ in chunks]
    with patch.object(rag, 'generate_embeddings', side_effect=remove):
        jobs.process_one()
    with env[0]() as conn:
        assert conn.execute('SELECT count(*) AS n FROM document_chunks').fetchone()['n'] == 0
    assert jobs.list_jobs(env[1], env[2])['total'] == 0


def test_owner_store_scopes_and_disabled_worker(vector_db, monkeypatch):
    env = vector_db
    meta = table(env)
    doc = document(env)
    target = job(env, table_id=meta['id'])
    for uid, pid in [(env[1], env[3]), (env[4], env[5])]:
        assert jobs.list_jobs(uid, pid)['total'] == 0
        with pytest.raises(AppException) as err:
            jobs.retry_job(uid, pid, str(target['id']))
        assert err.value.status_code == 404
        assert not db.delete_file(uid, doc['file_id'], project_id=pid)
    with pytest.raises(AppException):
        jobs.list_jobs(env[4], env[2])
    monkeypatch.setattr(jobs.settings, 'rag_enabled', False)
    assert jobs.process_one() is False
    assert jobs.list_jobs(env[1], env[2])['search_enabled'] is False
    assert job(env, table_id=meta['id'])['attempts'] == 0


def test_committed_import_and_restore_enqueue_without_http_hooks(vector_db):
    env = vector_db
    from app import attribute_restoration as restore
    from unittest.mock import patch
    with patch.object(restore, '_connect', env[0]):
        src = ledger_imports.create_source(env[1], env[2], ledger_imports.CreateSourceRequest(name='출처', provider='PG', account='a', feed='결제',
            mapping={'amount_column': 'amount', 'occurred_at_column': 'day', 'event_id_column': 'id', 'event_kind': 'signed'}))
        jobs.process_one()
        batch = ledger_imports.upload_batch(env[1], env[2], str(src['id']), str(uuid4()), b'id,amount,day,fee\n1,100,2026-09-08,3\n', 'payment.csv', StorageService())
        assert job(env, table_id=src['table_id'])['status'] == 'succeeded'
        ready = ledger_imports.preview_batch(env[1], env[2], str(batch['id']), StorageService())
        ledger_imports.commit_batch(env[1], env[2], str(batch['id']), str(ready['preview_token']), StorageService())
        assert job(env, table_id=src['table_id'])['status'] == 'pending'
        jobs.process_one()
        preview = restore.preview_restoration(env[1], env[2], str(src['id']), restore.RestoreAttributesRequest(fee_column='fee'), StorageService())
        restore.apply_restoration(env[1], env[2], str(src['id']), str(preview['id']), StorageService())
        assert job(env, table_id=src['table_id'])['status'] == 'pending'
        jobs.process_one()
        with env[0]() as conn:
            assert 'PG 수수료: fee' in conn.execute('SELECT content FROM schema_embeddings').fetchone()['content']


def test_http_pending_document_status_retry_and_scope(vector_db, monkeypatch):
    env = vector_db
    from app import main
    from app.auth import get_current_user
    monkeypatch.setattr(main, 'storage', StorageService())
    main.app.dependency_overrides[get_current_user] = lambda: {'id': env[1], 'email': 'synthetic@test.invalid'}
    try:
        client = TestClient(main.app)
        base = f'/api/projects/{env[2]}'
        response = client.post(base+'/documents', files={'file': ('rules.txt', b'refund policy')})
        assert response.status_code == 200 and response.json()['index_status'] == 'pending'
        doc = response.json()
        assert client.get(base+'/documents').json()['documents'][0]['chunk_count'] == 0
        status = client.get(base+'/search-index').json()
        assert status['counts'] == {'pending': 1}
        assert client.post(base+f"/search-index/{doc['index_job_id']}/retry").json()['replayed']
        assert client.get(f'/api/projects/{env[5]}/search-index').status_code == 404
        assert client.delete(base+f"/documents/{doc['file_id']}").status_code == 200
    finally:
        main.app.dependency_overrides.clear()


def test_generic_row_edits_enqueue_atomically_and_keep_counts(vector_db, monkeypatch):
    env = vector_db
    from app import sql_executor
    monkeypatch.setattr(sql_executor, '_connect', env[0])
    meta = table(env)
    name = db.get_user_table_name(env[1], str(meta['id']))
    jobs.process_one()
    sql_executor.safe_insert(name, env[1], [{'amount': 200}])
    assert job(env, table_id=meta['id'])['status'] == 'pending'
    assert db.get_table_meta(str(meta['id']), env[1])['row_count'] == 2
    jobs.process_one()
    where = [{'column': 'amount', 'operator': '=', 'value': '200'}]
    sql_executor.safe_update(name, env[1], {'amount': 300}, where)
    assert job(env, table_id=meta['id'])['status'] == 'pending'
    jobs.process_one()
    with pytest.raises(Exception):
        sql_executor.safe_insert(name, env[1], [{'amount': 400}, {'amount': 'not numeric'}])
    assert job(env, table_id=meta['id'])['status'] == 'succeeded'
    sql_executor.safe_delete(name, env[1], [{'column': 'amount', 'operator': '=', 'value': '300'}])
    assert job(env, table_id=meta['id'])['status'] == 'pending'
    assert db.get_table_meta(str(meta['id']), env[1])['row_count'] == 1


def test_chat_reports_pending_and_stale_indexes_without_claiming_no_data(vector_db):
    env = vector_db
    from app.agent_tools import ToolExecutor
    meta = table(env)
    document(env)
    executor = ToolExecutor(env[1], env[2])
    for tool in ['search_schema', 'search_documents']:
        result = executor.execute(tool, '{"query":"자료"}')
        assert result['status'] == 'index_incomplete' and result['index_coverage']['updating'] == 1
    jobs.process_one()
    db.update_table_meta(str(meta['id']), env[1], description='수정된 장부')
    coverage = rag.schema_index_coverage(env[1], env[2])
    assert coverage['indexed'] == 1 and coverage['missing'] == 0 and coverage['updating'] == 1


def test_legacy_bootstrap_and_document_registration_rollback(vector_db):
    env = vector_db
    meta = table(env)
    jobs.process_one()
    with env[0]() as conn:
        conn.execute('DELETE FROM search_index_jobs WHERE table_meta_id=%s', (meta['id'],))
    jobs.ensure_index_jobs()
    assert job(env, table_id=meta['id'])['status'] == 'pending'
    with env[0]() as conn:
        before = conn.execute('SELECT count(*) AS n FROM files').fetchone()['n']
        conn.execute('ALTER TABLE search_index_jobs ADD CHECK(file_id IS NULL)')
    with pytest.raises(Exception):
        document(env)
    with env[0]() as conn:
        assert conn.execute('SELECT count(*) AS n FROM files').fetchone()['n'] == before


def test_same_hash_with_incorrect_index_scope_is_repaired(vector_db):
    env = vector_db
    meta = table(env)
    jobs.process_one()
    with env[0]() as conn:
        conn.execute('UPDATE schema_embeddings SET user_id=%s,project_id=%s WHERE table_meta_id=%s', (env[4], env[5], meta['id']))
    state = job(env, table_id=meta['id'])
    jobs.retry_job(env[1], env[2], str(state['id']))
    jobs.process_one()
    with env[0]() as conn:
        row = conn.execute('SELECT user_id,project_id FROM schema_embeddings WHERE table_meta_id=%s', (meta['id'],)).fetchone()
    assert [str(row[k]) for k in ['user_id','project_id']] == [env[1],env[2]]
