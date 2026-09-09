"""I acceptance: real HTTP/browser/pgvector, injected provider outage, real recovery.

Only a fresh loopback database is used. Browser processes close between phases;
recovery runs with no browser open. Embedding calls on recovery are paid.
"""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('live_runtime', ROOT / 'scripts/ui-eval/live-run.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')


def main():
    admin = os.environ['DATAEZ_RAG_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    assert config.get('host') in {'127.0.0.1', 'localhost', '::1'} and not config.get('hostaddr')
    name = 'dataez_index_eval_' + uuid4().hex
    out = ROOT / 'scripts/index-eval/artifacts' / name
    out.mkdir(parents=True)
    ordinary_env = os.environ.copy()
    local = dotenv_values(ROOT / '.env')
    if local.get('OPENAI_API_KEY') and not os.environ.get('OPENAI_API_KEY'):
        os.environ['OPENAI_API_KEY'] = local['OPENAI_API_KEY']
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('A real embedding API key is required')
    api_port, web_port = runtime.free_port(), runtime.free_port()
    os.environ.update(DATABASE_URL=make_conninfo(admin, dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
        APP_ENV='development', RAG_ENABLED='true', INDEX_WORKER_ENABLED='false', STORAGE_BACKEND='local',
        LOCAL_STORAGE_PATH=str(out/'uploads'), METRIC_SCHEDULER_ENABLED='false', IMPORT_CLEANUP_ENABLED='false',
        REDIS_URL='redis://127.0.0.1:1/0', UPLOAD_RATE_LIMIT_PER_MINUTE='100',
        ALLOWED_ORIGINS=f'http://127.0.0.1:{web_port}', NEXT_PUBLIC_API_URL=f'http://127.0.0.1:{api_port}',
        LIVE_UI_URL=f'http://127.0.0.1:{web_port}', LIVE_ARTIFACTS=str(out))
    sys.path.insert(0, str(ROOT/'api'))
    from app import db, rag
    from app.agent_tools import ToolExecutor
    report = {'run_id': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
        'api_mocks': False, 'real_postgres': True, 'real_browser': True, 'real_recovery_embeddings': True,
        'fault_injection': 'Embedding endpoint temporarily points to a closed loopback port',
        'real_chat_model_evaluated': False, 'checks': [], 'passed': False}
    logs, api, web, build, browser, created, built = [], None, None, None, None, False, False
    node = shutil.which('node')

    def check(label, actual, expected):
        report['checks'].append({'check': label, 'actual': actual, 'expected': expected, 'passed': actual == expected})
        assert actual == expected, f'{label}: {actual!r} != {expected!r}'

    def start(command, cwd, label, env=None):
        log = (out/(label+'.log')).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=cwd, env=env or os.environ.copy(), stdout=log,
                                stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN)

    def start_api(label, *, enabled, outage=False):
        env = {**os.environ, 'INDEX_WORKER_ENABLED': str(enabled).lower()}
        env.pop('OPENAI_BASE_URL', None)
        if outage:
            env['OPENAI_BASE_URL'] = f'http://127.0.0.1:{runtime.free_port()}/v1'
        process = start([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port)], ROOT/'api', label, env)
        runtime.wait_http(os.environ['NEXT_PUBLIC_API_URL']+'/health', process)
        return process

    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT/'db/init.sql').read_text(encoding='utf-8'))
        api = start_api('api-pending', enabled=False)
        client = httpx.Client(base_url=os.environ['NEXT_PUBLIC_API_URL'], timeout=120)
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        email, password = name+'@example.test', secrets.token_urlsafe(20) + 'Aa1!'
        owner = request('POST', '/api/auth/signup', json={'email': email, 'password': password, 'name': '검색 복구 검증'})
        uid = owner['user_id']
        client.headers['Authorization'] = 'Bearer '+owner['access_token']
        pid = request('POST', '/api/projects', json={'name': '검색 갱신 검증점'})['id']
        other = request('POST', '/api/projects', json={'name': '다른 가게'})['id']
        base = f'/api/projects/{pid}'
        meta = request('POST', base+'/tables/import', files={'file': ('sales.csv', b'amount\n100\n')}, data={'table_name': '카드 매출'})
        widget = request('POST', base+'/metrics', json={'title': '기존 매출', 'definition': {'table_id': meta['id'], 'column': 'amount'}, 'refresh_interval_seconds': 3600})
        with db._connect() as conn:
            before_widget = conn.execute('SELECT * FROM dashboard_widgets WHERE id=%s', (widget['id'],)).fetchone()
        initial = request('GET', base+'/search-index')
        check('Disabled worker preserves pending request', initial['counts'], {'pending': 1})
        dump(out/'browser-input.json', {'email': email, 'password': password, 'project_id': pid, 'table_id': meta['id']})
        built = True
        build = start([node, 'node_modules/next/dist/bin/next', 'build'], ROOT/'web', 'build')
        if build.wait(timeout=240):
            raise RuntimeError('Web build failed')
        web = start([node, 'node_modules/next/dist/bin/next', 'start', '-p', str(web_port), '-H', '127.0.0.1'], ROOT/'web', 'web')
        runtime.wait_http(os.environ['LIVE_UI_URL'], web)

        def browser_phase(phase):
            nonlocal browser
            browser = start([node, 'search-index.cjs', phase], ROOT/'scripts/ui-eval', 'browser-'+phase)
            if browser.wait(timeout=150):
                raise RuntimeError('Browser '+phase+' failed')
            value = json.loads((out/('browser-'+phase+'.json')).read_text(encoding='utf-8'))
            report[phase] = value
            check('Browser '+phase+' has no page errors', value['errors'], [])
            return value

        pending = browser_phase('pending')
        document_id = pending['document']['file_id']
        empty_id = pending['empty_document']['file_id']
        check('Pending document visible before embeddings', request('GET', base+'/documents')['total'], 2)
        print('Pending UI and document upload passed; injecting provider outage', flush=True)
        runtime.stop(api)
        api = start_api('api-outage', enabled=True, outage=True)

        def wait_counts(expected):
            deadline = time.monotonic()+120
            while time.monotonic() < deadline:
                value = request('GET', base+'/search-index')
                if value['counts'] == expected:
                    return value
                time.sleep(.3)
            raise AssertionError(f'Expected {expected}, got {value}')

        outage = wait_counts({'retry': 2, 'failed': 1})
        check('Connection failure schedules retries; empty document stops', outage['counts'], {'retry': 2, 'failed': 1})
        browser_phase('retry')
        before_retry = {j['id']: j['attempts'] for j in request('GET', base+'/search-index')['jobs']}
        runtime.stop(api)
        print('Retry UI passed; restarting API with real provider, browser closed', flush=True)
        api = start_api('api-recovered', enabled=True)
        recovered = wait_counts({'succeeded': 2, 'failed': 1})
        check('Retry state survives restart and recovers without browser', recovered['counts'], {'succeeded': 2, 'failed': 1})
        check('Recovery continues previous attempt counts', all(j['attempts'] > before_retry[j['id']] for j in recovered['jobs'] if j['status']=='succeeded'), True)
        report['recovery_jobs'] = recovered
        schema = ToolExecutor(uid, pid).execute('search_schema', '{"query":"카드 매출"}')
        docs = ToolExecutor(uid, pid).execute('search_documents', '{"query":"예약 취소 환불 규정"}')
        check('Recovered schema is retrieved with real embedding', schema['results'][0]['table_meta_id'], meta['id'])
        check('Recovered document is retrieved with real embedding', docs['results'][0]['file_id'], document_id)
        check('Failed document prevents false no-data claim', docs['status'], 'index_incomplete')
        check('Other store never receives these jobs', request('GET', f'/api/projects/{other}/search-index')['total'], 0)
        foreign_retry = client.post(f"/api/projects/{other}/search-index/{recovered['jobs'][0]['id']}/retry")
        check('Other store retry is rejected', foreign_retry.status_code, 404)
        report['retrieval'] = {'schema': schema, 'documents': docs}
        browser_phase('recovered')
        final = wait_counts({'succeeded': 2})
        check('Failed document can be deleted from UI', request('GET', base+'/documents')['total'], 1)
        request('POST', base+f"/metrics/{widget['id']}/refresh")
        with db._connect() as conn:
            after_widget = conn.execute('SELECT * FROM dashboard_widgets WHERE id=%s', (widget['id'],)).fetchone()
            physical = conn.execute(sql.SQL('SELECT amount FROM {}').format(sql.Identifier(db.get_user_table_name(uid, meta['id'])))).fetchone()['amount']
        check('Index recovery leaves ledger value unchanged', str(physical), '100')
        check('Metric identity definition layout schedule preserved',
            [after_widget[k] for k in ['id','layout','refresh_interval_seconds']],
            [before_widget[k] for k in ['id','layout','refresh_interval_seconds']])
        check('Metric value and definition preserved',
            [after_widget['widget_data'][k] for k in ['value','metric_definition']],
            [before_widget['widget_data'][k] for k in ['value','metric_definition']])
        report['final_jobs'] = final
        report['passed'] = True
    finally:
        for process in [browser, build, web, api]:
            runtime.stop(process)
        db.close_pool()
        if created:
            assert name.startswith('dataez_index_eval_') and len(name) == len('dataez_index_eval_')+32
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['temporary_database_removed'] = True
        if built:
            with (out/'restore-build.log').open('w', encoding='utf-8') as log:
                result = subprocess.run([node, 'node_modules/next/dist/bin/next', 'build'], cwd=ROOT/'web', env=ordinary_env,
                    stdout=log, stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN, timeout=240)
            report['ordinary_web_build_restored'] = result.returncode == 0
            report['passed'] = report['passed'] and result.returncode == 0
        for log in logs:
            log.close()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        dump(out/'report.json', report)
        print('Report: '+str(out/'report.json'), flush=True)
    print('I acceptance: '+str(report['passed']), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
