"""Exercise private signed uploads with synthetic accounts; no LLM calls or secrets in output."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
REF = 'whbygnzoaehvlddltwlb'


def main(deployment=None):
    values = dict(dotenv_values(ROOT / '.env.supabase.local'))
    assert values['SUPABASE_URL'] == f'https://{REF}.supabase.co'
    assert f'dataez_app.{REF}:' in values['DATABASE_URL']
    os.environ.update(values)
    sys.path.insert(0, str(ROOT / 'api'))
    from fastapi.testclient import TestClient
    from app.main import app
    from app import db
    from app.storage import StorageService
    if deployment:
        from vercel_test_client import VercelTestClient
        factory = lambda: VercelTestClient(deployment)
    else:
        factory = lambda: TestClient(app)
    logging.disable(logging.CRITICAL)
    report = {'project_ref': REF, 'deployment': deployment, 'checks': [],
              'scope':'Authenticated API reservations/completion + real direct Storage PUT/GET; SQL checks and cleanup local; no LLM'}
    checks, emails, keys = report['checks'], [], set()
    store = StorageService()._supabase
    try:
        with factory() as client:
            headers = []
            for _ in range(2):
                email = f'direct-upload-{uuid4().hex}@example.invalid'
                emails.append(email)
                response = client.post('/api/auth/signup', json={'email':email, 'password':'Aa1!'+secrets.token_urlsafe(24)})
                assert response.status_code == 200, f'signup HTTP {response.status_code}'
                headers.append({'Authorization':'Bearer '+response.json()['access_token']})
            project = client.post('/api/projects', headers=headers[0], json={'name':'Direct upload check'}).json()['id']
            assert client.get('/api/uploads/capabilities', headers=headers[0]).json()['direct_upload']

            def reserve(content, name):
                response = client.post('/api/uploads', headers=headers[0], json={
                    'request_id':str(uuid4()), 'project_id':project, 'filename':name,
                    'size_bytes':len(content), 'content_hash':hashlib.sha256(content).hexdigest()})
                assert response.status_code == 201, f'reservation HTTP {response.status_code}'
                assert response.headers['cache-control'] == 'private, no-store'
                return response.json()

            # Exact configured maximum, far above Vercel's multipart body limit.
            content = b'DATAEZ private upload verification\n'.ljust(20*1024*1024, b'x')
            item = reserve(content, '직접업로드-20MiB.txt')
            endpoint = f"/api/uploads/{item['session_id']}/complete"
            assert client.post(endpoint, headers=headers[1]).status_code == 404
            assert client.post(endpoint, headers=headers[0]).status_code == 409
            checks.append('other_account_and_missing_upload_rejected')
            preflight = httpx.options(item['upload_url'], headers={
                'Origin':'https://dataez.vercel.app', 'Access-Control-Request-Method':'PUT',
                'Access-Control-Request-Headers':'content-type,cache-control'}, timeout=20)
            assert preflight.status_code < 400
            assert preflight.headers.get('access-control-allow-origin') in ('*','https://dataez.vercel.app')
            allowed = preflight.headers.get('access-control-allow-headers','').lower()
            assert 'content-type' in allowed and 'cache-control' in allowed
            checks.append('production_origin_storage_cors')
            uploaded = httpx.put(item['upload_url'], content=content, headers={'Content-Type':'application/octet-stream','Cache-Control':'no-store'}, timeout=120)
            assert uploaded.status_code in (200, 201), f'direct PUT HTTP {uploaded.status_code}'
            checks.append('20_mib_signed_upload_without_api_body_or_user_jwt')
            # Token replay must not change bytes accepted during finalization.
            overwritten = httpx.put(item['upload_url'], content=b'changed', headers={'Content-Type':'application/octet-stream','x-upsert':'true'}, timeout=30)
            assert overwritten.status_code >= 400, 'signed URL unexpectedly allowed overwrite'
            checks.append('signed_token_cannot_overwrite_even_with_upsert_header')
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: client.post(endpoint, headers=headers[0]), range(2)))
            assert all(r.status_code == 200 for r in results), 'concurrent completion failed'
            assert len({r.json()['file_id'] for r in results}) == 1
            file_id = results[0].json()['file_id']
            checks.append('concurrent_completion_creates_one_file')
            assert client.post(f'/api/library/files/{file_id}/download-url', headers=headers[1]).status_code == 404
            response = client.post(f'/api/library/files/{file_id}/download-url', headers=headers[0])
            assert response.status_code == 200, f'signed download HTTP {response.status_code}'
            download = httpx.get(response.json()['url'], timeout=120)
            assert download.content == content
            checks.append('20_mib_private_signed_download_exact_bytes')
            # Also exercise the analysis-ready CSV path through the new reservation.
            csv = 'date,amount\n2026-09-01,12000\n2026-09-02,8000\n'.encode()
            small = reserve(csv, '매출.csv')
            assert httpx.put(small['upload_url'], content=csv, headers={'Content-Type':'application/octet-stream'}, timeout=30).status_code == 200
            response = client.post(f"/api/uploads/{small['session_id']}/complete", headers=headers[0])
            assert response.status_code == 200
            csv_id = response.json()['file_id']
            assert client.get(f'/api/library/files/{csv_id}/preview', headers=headers[0]).json()['row_count'] == 2
            prepared = client.post(f'/api/library/files/{csv_id}/prepare', headers=headers[0], json={'project_id':project})
            assert prepared.status_code == 200
            table_id = prepared.json()['bindings'][0]['table_id']
            with db._connect() as conn:
                uid = conn.execute('SELECT user_id FROM files WHERE id=%s',(csv_id,)).fetchone()['user_id']
                table = db.get_user_table_name(str(uid), table_id)
                total = conn.execute(sql.SQL('SELECT sum(amount) AS total FROM {}').format(sql.Identifier(table))).fetchone()['total']
                assert total == 20000
                assert conn.execute("SELECT rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename='upload_sessions'").fetchone()['rowsecurity']
                assert not conn.execute("SELECT has_table_privilege('anon','upload_sessions','SELECT') AS allowed").fetchone()['allowed']
            checks.append('korean_csv_preview_prepare_sql_total_20000')
            checks.append('session_table_rls_and_browser_role_denied')
    finally:
        db.close_pool()
        with psycopg.connect(values['DATABASE_URL'], prepare_threshold=None, connect_timeout=10) as conn:
            ids = [r[0] for r in conn.execute('SELECT id FROM users WHERE email=ANY(%s)', (emails,)).fetchall()]
            if ids:
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM upload_sessions WHERE user_id=ANY(%s)',(ids,)).fetchall())
                keys.update(r[0] for r in conn.execute('SELECT storage_key FROM files WHERE user_id=ANY(%s)',(ids,)).fetchall())
                for uid, tid in conn.execute('SELECT user_id,id FROM table_meta WHERE user_id=ANY(%s)',(ids,)).fetchall():
                    conn.execute(sql.SQL('DROP TABLE IF EXISTS {}').format(sql.Identifier(db.get_user_table_name(str(uid),str(tid)))))
                for name in ('upload_sessions','audit_log','query_history','dashboard_widgets','conversations','search_index_jobs','schema_embeddings','document_chunks','table_meta','library_entries','refresh_tokens','projects','files','users'):
                    field = 'id' if name == 'users' else 'user_id'
                    conn.execute(sql.SQL('DELETE FROM {} WHERE {}=ANY(%s)').format(sql.Identifier(name),sql.Identifier(field)), (ids,))
        for key in keys:
            store.delete(key)
        report['synthetic_data_removed'] = True
    name = 'direct-upload-vercel.json' if deployment else 'direct-upload-supabase.json'
    (ROOT/'docs/evaluations/vercel-api'/name).write_text(json.dumps(report, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment')
    args = parser.parse_args()
    try:
        main(args.deployment)
    except Exception as error:
        import traceback
        print('Failure location:', [(Path(frame.filename).name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)])
        print('Direct upload verification failed:', type(error).__name__, str(error) if isinstance(error,AssertionError) else '')
        raise SystemExit(1)
