"""Real pgvector transactions and isolation; synthetic vectors, not retrieval quality.

Set DATAEZ_RAG_TEST_DATABASE_URL to a loopback disposable PostgreSQL server.
Every test creates/drops its own DB; real OpenAI retrieval has a separate runner.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import json
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest

from app import db, rag, table_imports, ledger_imports
from app.exceptions import AppException
from app.storage import StorageService

DSN = os.environ.get('DATAEZ_RAG_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_RAG_TEST_DATABASE_URL for real pgvector')
ROOT = Path(__file__).resolve().parents[2]
VEC = [1.0] + [0.0] * 1535


@pytest.fixture
def vector_db(monkeypatch, tmp_path):
    config = conninfo_to_dict(DSN)
    assert config.get('host') in {'127.0.0.1', 'localhost', '::1'} and not config.get('hostaddr')
    name = 'dataez_rag_test_' + uuid4().hex
    url = make_conninfo(DSN, dbname=name)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))

    @contextmanager
    def connect():
        with psycopg.connect(url, row_factory=dict_row) as conn:
            yield conn

    try:
        with connect() as conn:
            conn.execute((ROOT / 'db/init.sql').read_text(encoding='utf-8'))
        for module in [db, rag, table_imports, ledger_imports]:
            monkeypatch.setattr(module, '_connect', connect)
        monkeypatch.setattr(rag.settings, 'rag_enabled', True)
        monkeypatch.setattr(rag.settings, 'local_storage_path', str(tmp_path))
        monkeypatch.setattr(rag, 'embed_one', lambda *a, **kw: VEC)
        monkeypatch.setattr(rag, 'generate_embeddings', lambda chunks, **kw: [VEC for _ in chunks])
        db.ensure_ledger_import_tables()
        db.ensure_rag_tables()
        user, other_user, store, other_store, foreign_store, file_id = [str(uuid4()) for _ in range(6)]
        with connect() as conn:
            for uid in [user, other_user]:
                conn.execute("INSERT INTO users(id,email,password_hash) VALUES(%s,%s,'test-only')", (uid, uid + '@synthetic.invalid'))
        for pid, uid in [(store, user), (other_store, user), (foreign_store, other_user)]:
            db.create_project(pid, uid, '합성 검증')
        db.save_file(user, file_id, '규칙.md', 'unused-test-object', 100)
        yield connect, user, store, other_store, other_user, foreign_store, file_id
    finally:
        assert name.startswith('dataez_rag_test_') and len(name) == 48
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s', (name,))
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def rows(connect, file_id):
    with connect() as conn:
        return conn.execute('SELECT chunk_index,content FROM document_chunks WHERE file_id=%s ORDER BY chunk_index', (file_id,)).fetchall()


def test_failed_later_embedding_batch_preserves_previous_complete_document(vector_db, monkeypatch):
    connect, user, store, *_, file_id = vector_db
    assert rag.chunk_and_embed_document(file_id, user, store, ['기존 규칙 A', '기존 규칙 B']) == 2
    before = rows(connect, file_id)
    monkeypatch.setattr(rag, '_EMBED_BATCH_SIZE', 1)
    with patch.object(rag, 'generate_embeddings', side_effect=[[VEC], RuntimeError('second batch failed')]):
        with pytest.raises(AppException) as exc:
            rag.chunk_and_embed_document(file_id, user, store, ['새 규칙 A', '새 규칙 B'])
    assert exc.value.code == 'rag_index_failed' and rows(connect, file_id) == before
    assert rag.chunk_and_embed_document(file_id, user, store, ['교체 완료']) == 1
    assert rows(connect, file_id) == [{'chunk_index': 0, 'content': '교체 완료'}]


def test_sql_failure_rolls_back_document_replacement(vector_db):
    connect, user, store, *_, file_id = vector_db
    rag.chunk_and_embed_document(file_id, user, store, ['기존 자료'])
    with connect() as conn:
        conn.execute("ALTER TABLE document_chunks ADD CHECK(content<>'reject')")
    with pytest.raises(AppException) as exc:
        rag.chunk_and_embed_document(file_id, user, store, ['첫 새 청크', 'reject'])
    assert exc.value.code == 'rag_index_failed'
    assert rows(connect, file_id) == [{'chunk_index': 0, 'content': '기존 자료'}]


def test_document_scope_is_rechecked_and_foreign_scope_never_embedded(vector_db):
    connect, user, store, other_store, other_user, _, file_id = vector_db
    rag.chunk_and_embed_document(file_id, user, store, ['가게 전용 자료'])
    with patch.object(rag, 'generate_embeddings') as embed:
        for uid, pid in [(other_user, store), (user, other_store)]:
            with pytest.raises(AppException) as exc:
                rag.chunk_and_embed_document(file_id, uid, pid, ['다른 범위'])
            assert exc.value.code == 'not_found'
        embed.assert_not_called()
    assert not rag.hybrid_search_documents(user, '가게', project_id=other_store)
    assert not rag.hybrid_search_documents(other_user, '가게', project_id=store)
    assert len(rag.hybrid_search_documents(user, '가게', project_id=store)) == 1
    with connect() as conn:
        conn.execute('UPDATE projects SET deleted_at=now() WHERE id=%s', (store,))
    assert not rag.hybrid_search_documents(user, '가게', project_id=store)


def test_document_delete_checks_store_and_owner(vector_db):
    connect, user, store, other_store, other_user, _, file_id = vector_db
    rag.chunk_and_embed_document(file_id, user, store, ['가게 전용 자료'])
    assert not db.delete_file(user, file_id, project_id=other_store)
    assert not db.delete_file(other_user, file_id, project_id=store)
    assert len(rows(connect, file_id)) == 1
    assert db.delete_file(user, file_id, project_id=store)
    assert not rows(connect, file_id)


def test_scoped_catalog_cli_plans_and_skips_unchanged_without_api(vector_db, tmp_path):
    connect, user, store, _, other_user, *_ = vector_db
    meta = table_imports.create_imported_table(user, store, '검증 장부', b'day,amount\n2026-09-01,100\n', 'ledger.csv', StorageService())
    assert rag.upsert_schema_embedding(user, store, str(meta['id']))
    with connect() as conn:
        dsn = conn.info.dsn
    env = {**os.environ, 'DATABASE_URL': dsn, 'RAG_ENABLED': 'true', 'STORAGE_BACKEND': 'local',
           'LOCAL_STORAGE_PATH': str(tmp_path), 'OPENAI_API_KEY': 'unused-catalog-test',
           'JWT_SECRET_KEY': 'catalog-test-only-random-string-2026'}
    cmd = [sys.executable, str(ROOT / 'scripts/reindex_catalog.py'), '--user-id', user, '--project-id', store]
    for flags in [[], ['--apply']]:
        result = subprocess.run(cmd + flags, env=env, cwd=ROOT / 'api', capture_output=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['status'] == 'current'
    cmd[3] = other_user
    result = subprocess.run(cmd, env=env, cwd=ROOT / 'api', capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode != 0 and 'Store not found' in result.stderr


def test_catalog_indexes_filename_aliases_period_and_discards_stale_write(vector_db):
    connect, user, store, other_store, *_, file_id = vector_db
    storage = StorageService()
    source = ledger_imports.create_source(user, store, ledger_imports.CreateSourceRequest(
        name='카드 결제', provider='가상 PG', account='0001', feed='온라인 결제',
        mapping={'amount_column': '금액', 'occurred_at_column': '일시', 'event_id_column': '번호', 'event_kind': 'signed'}))
    content = '번호,금액,일시\n0001,100,2026-09-01T00:05:00+09:00\n0002,-10,2026-09-02T12:00:00+09:00\n'.encode()
    batch = ledger_imports.upload_batch(user, store, str(source['id']), str(uuid4()), content, 'september-pg.csv', storage)
    batch = ledger_imports.preview_batch(user, store, str(batch['id']), storage)
    ledger_imports.commit_batch(user, store, str(batch['id']), str(batch['preview_token']), storage)
    tid = str(source['table_id'])
    assert not rag.upsert_schema_embedding(user, other_store, tid)
    assert rag.upsert_schema_embedding(user, store, tid)
    with connect() as conn:
        doc = conn.execute('SELECT content FROM schema_embeddings WHERE table_meta_id=%s', (tid,)).fetchone()['content']
    assert all(s in doc for s in ['september-pg.csv', '2026-09-01 ~ 2026-09-02', '취소', '원본 금액 컬럼: 금액'])
    assert not rag.upsert_schema_embedding(user, store, tid)
    db.update_table_meta(tid, user, description='중간 설명')

    def changed_while_embedding(*a, **kw):
        # Succeeds on a separate connection: no DB row lock spans the API call.
        db.update_table_meta(tid, user, description='최신 설명')
        return VEC

    with patch.object(rag, 'embed_one', side_effect=changed_while_embedding):
        assert not rag.upsert_schema_embedding(user, store, tid)
    with connect() as conn:
        assert conn.execute('SELECT content FROM schema_embeddings WHERE table_meta_id=%s', (tid,)).fetchone()['content'] == doc
    assert rag.upsert_schema_embedding(user, store, tid)
    with connect() as conn:
        conn.execute('UPDATE table_meta SET deleted_at=now() WHERE id=%s', (tid,))
    assert not rag.hybrid_search_schema(user, store, '카드 결제')


def test_mislabelled_index_cannot_cross_live_table_ownership(vector_db):
    connect, user, store, _, other_user, foreign_store, _ = vector_db
    table = table_imports.create_imported_table(other_user, foreign_store, '비공개 매출', b'amount\n777777\n', 'private.csv', StorageService())
    assert rag.upsert_schema_embedding(other_user, foreign_store, str(table['id']))
    with connect() as conn:
        conn.execute('UPDATE schema_embeddings SET user_id=%s,project_id=%s WHERE table_meta_id=%s', (user, store, table['id']))
    assert not rag.hybrid_search_schema(user, store, '비공개 매출')
