"""Concurrency and isolation use real PostgreSQL; object transport is simulated."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from uuid import uuid4

import pytest
from fastapi import Response

from .test_file_library import live  # noqa: F401 (shared isolated-schema fixture)
from app import direct_uploads as uploads
from app.auth import get_current_user
from app.config import settings
from app.upload_schema import DDL


@pytest.fixture
def direct(live, monkeypatch):
    with live.connect() as conn:
        conn.execute('CREATE TABLE users(id uuid PRIMARY KEY)')
        conn.execute('INSERT INTO users VALUES(%s),(%s)', (live.user, live.stranger))
        conn.execute(DDL)
    objects = {}
    class Store:
        def create_upload_url(self, key):
            self.last_key = key
            return 'https://example.supabase.co/' + key + '?token=test'
        def get_limited(self, key, limit):
            if key not in objects:
                raise FileNotFoundError()
            if len(objects[key]) > limit:
                raise ValueError()
            return objects[key]
        def delete(self, key):
            objects.pop(key, None)
    store = Store()
    monkeypatch.setattr(uploads, 'require_storage', lambda: store)
    monkeypatch.setattr(settings, 'storage_backend', 'supabase')
    live.app.include_router(uploads.router)
    live.objects, live.remote = objects, store
    return live


def reserve(direct, content=b'amount\n20000\n', **changes):
    payload = dict(request_id=str(uuid4()), project_id=direct.store, filename='매출.csv',
                   size_bytes=len(content), content_hash=hashlib.sha256(content).hexdigest())
    payload.update(changes)
    response = direct.client.post('/api/uploads', json=payload)
    assert response.status_code == 201, response.text
    session = response.json()['session_id']
    with direct.connect() as conn:
        key = conn.execute('SELECT storage_key FROM upload_sessions WHERE id=%s',(session,)).fetchone()['storage_key']
    direct.objects[key] = content
    return session, key, payload


def test_concurrent_completion_and_content_dedupe(direct):
    session, key, payload = reserve(direct)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: uploads.complete(session, {'id':direct.user}), range(3)))
    assert len({r['file_id'] for r in results}) == 1
    assert sum(not r['replayed'] for r in results) == 1
    second, _, _ = reserve(direct)
    assert uploads.complete(second, {'id':direct.user})['file_id'] == results[0]['file_id']
    with direct.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM files').fetchone()['n'] == 1
        assert conn.execute('SELECT storage_key FROM files').fetchone()['storage_key'] == key
    replay = direct.client.post('/api/uploads', json=payload)
    assert replay.json()['upload_url'] is None
    assert replay.json()['file_id'] == results[0]['file_id']
    assert replay.headers['cache-control'] == 'private, no-store'
    payload['filename'] = 'changed.csv'
    assert direct.client.post('/api/uploads', json=payload).status_code == 409


def test_other_account_and_deleted_store_denied(direct):
    session, _, payload = reserve(direct)
    direct.app.dependency_overrides[get_current_user] = lambda: {'id':direct.stranger}
    assert direct.client.post(f'/api/uploads/{session}/complete').status_code == 404
    assert direct.client.post('/api/uploads', json=payload).status_code == 404
    direct.app.dependency_overrides[get_current_user] = lambda: {'id':direct.user}
    with direct.connect() as conn:
        conn.execute('UPDATE projects SET deleted_at=now() WHERE id=%s', (direct.store,))
    assert direct.client.post(f'/api/uploads/{session}/complete').status_code == 404


@pytest.mark.parametrize('actual', [None, b'wrong size', b'xxxxxxxxxxxxx', b''])
def test_missing_or_mismatched_bytes_never_registered(direct, actual):
    session, key, _ = reserve(direct)
    if actual is None:
        del direct.objects[key]
    else:
        direct.objects[key] = actual
    assert direct.client.post(f'/api/uploads/{session}/complete').status_code in (409, 422)
    with direct.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM files').fetchone()['n'] == 0


def test_expiry_cleanup_preserves_registered_original_and_live_token(direct):
    done, key, _ = reserve(direct)
    uploads.complete(done, {'id':direct.user})
    abandoned, abandoned_key, _ = reserve(direct, b'other')
    active, active_key, _ = reserve(direct, b'active')
    with direct.connect() as conn:
        conn.execute("UPDATE upload_sessions SET expires_at=now()-interval '11 minutes' WHERE id IN (%s,%s)", (done, abandoned))
    assert direct.client.post(f'/api/uploads/{abandoned}/complete').status_code == 410
    assert uploads.cleanup_expired_uploads() == 2
    assert key in direct.objects and active_key in direct.objects and abandoned_key not in direct.objects
    with direct.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM upload_sessions').fetchone()['n'] == 1


def test_pending_limit_shared_by_all_requests(direct):
    for _ in range(10):
        reserve(direct)
    response = direct.client.post('/api/uploads', json=dict(request_id=str(uuid4()), filename='one.txt', size_bytes=1, content_hash='a'*64))
    assert response.status_code == 429


@pytest.mark.parametrize('change', [{'size_bytes':0}, {'size_bytes':20971521}, {'content_hash':'bad'}, {'storage_key':'someone/else'}, {'filename':'run.exe'}])
def test_invalid_reservations(direct, change):
    payload = dict(request_id=str(uuid4()), filename='one.txt', size_bytes=1, content_hash='a'*64)
    payload.update(change)
    assert direct.client.post('/api/uploads', json=payload).status_code == 422
