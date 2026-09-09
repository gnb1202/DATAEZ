"""H: real HTTP/DB attribute restoration; --browser uses real paid streaming AI.

The loopback pgvector database is temporary and always dropped. Existing app
data and source mappings are never selected by this runner.
"""
import argparse
import csv
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / 'samples/pg-evaluation'
spec = importlib.util.spec_from_file_location('live_runtime', ROOT / 'scripts/ui-eval/live-run.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    admin = os.environ['DATAEZ_RAG_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    assert config.get('host') in {'localhost', '127.0.0.1', '::1'} and not config.get('hostaddr')
    name = 'dataez_restore_eval_' + uuid4().hex
    out = ROOT / 'scripts/restore-eval/artifacts' / name
    out.mkdir(parents=True)
    local = dotenv_values(ROOT / '.env')
    for key in ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_ORCHESTRATOR_MODEL', 'OPENAI_EMBEDDING_MODEL']:
        if local.get(key) and key not in os.environ:
            os.environ[key] = local[key]
    api_port, web_port = runtime.free_port(), runtime.free_port()
    original_env = os.environ.copy()
    os.environ.update(DATABASE_URL=make_conninfo(admin, dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
        APP_ENV='development', RAG_ENABLED='true', INDEX_WORKER_ENABLED='true', STORAGE_BACKEND='local', LOCAL_STORAGE_PATH=str(out / 'uploads'),
        METRIC_SCHEDULER_ENABLED='false', IMPORT_CLEANUP_ENABLED='false', REDIS_URL='redis://127.0.0.1:1/0',
        UPLOAD_RATE_LIMIT_PER_MINUTE='100', ALLOWED_ORIGINS=f'http://127.0.0.1:{web_port}',
        NEXT_PUBLIC_API_URL=f'http://127.0.0.1:{api_port}', LIVE_UI_URL=f'http://127.0.0.1:{web_port}', LIVE_ARTIFACTS=str(out))
    sys.path.insert(0, str(ROOT / 'api'))
    from app import db, rag
    from app.config import settings
    report = {'run_id': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
        'api_mocks': False, 'real_postgres': True, 'real_embeddings': True, 'browser_evaluated': args.browser,
        'worker_model': settings.openai_model, 'router_model': settings.openai_orchestrator_model, 'checks': [], 'passed': False}
    logs, api, web, build, browser, created, built = [], None, None, None, None, False, False

    def check(label, actual, expected):
        report['checks'].append({'check': label, 'actual': actual, 'expected': expected, 'passed': actual == expected})
        if actual != expected:
            raise AssertionError(f'{label}: {actual!r} != {expected!r}')

    def start(command, cwd, label):
        log = (out / (label + '.log')).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=cwd, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN)

    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT / 'db/init.sql').read_text(encoding='utf-8'))
        api = start([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port)], ROOT / 'api', 'api')
        runtime.wait_http(os.environ['NEXT_PUBLIC_API_URL'] + '/health', api)
        client = httpx.Client(base_url=os.environ['NEXT_PUBLIC_API_URL'], timeout=180)
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.is_error:
                raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:1000]}')
            return response.json()

        email, password = name + '@example.test', secrets.token_urlsafe(20) + 'Aa1!'
        owner = request('POST', '/api/auth/signup', json={'email': email, 'password': password, 'name': '복원 검증'})
        uid = owner['user_id']
        client.headers['Authorization'] = 'Bearer ' + owner['access_token']
        pid = request('POST', '/api/projects', json={'name': '기존 출처 복원 검증점'})['id']
        base = f'/api/projects/{pid}'
        manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
        src = request('POST', base + '/ledger-sources', json={'name': '기존 결제원장', 'provider': '가상PG', 'account': 'H001', 'feed': '결제취소이벤트', 'mapping': manifest['pg_mapping']})
        def upload(filename, content, commit=True):
            batch = request('POST', base + '/imports', data={'source_id': src['id'], 'request_key': str(uuid4())}, files={'file': (filename, content)})
            url = base + '/imports/' + batch['id']
            ready = request('POST', url + '/preview')
            return request('POST', url + '/commit', json={'preview_token': ready['preview_token']}) if commit else ready
        for filename in ['01_gangnam_pg.csv', '03_gangnam_pg_overlap.csv']:
            upload(filename, (SAMPLES / filename).read_bytes())
        pending = upload('04_partial_refunds_repeat.csv', (SAMPLES / '04_partial_refunds_repeat.csv').read_bytes(), commit=False)
        metric = request('POST', base + '/metrics', json={'title': '기존 순결제액', 'definition': {'table_id': src['table_id'], 'column': 'amount'}, 'refresh_interval_seconds': 3600})
        table = db.get_user_table_name(uid, src['table_id'])
        runtime.wait_indexes(request, base)
        with db._connect() as conn:
            original_rows = conn.execute(sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(table))).fetchall()
            original_widget = conn.execute('SELECT * FROM dashboard_widgets WHERE id=%s', (metric['id'],)).fetchone()
            original_index = conn.execute('SELECT content FROM schema_embeddings WHERE table_meta_id=%s', (src['table_id'],)).fetchone()['content']
        check('Seed uses old six-column mapping', len(request('GET', base + '/tables')['tables'][0]['columns_schema']), 6)
        check('Original net payments', metric['widget_data']['value'], '1358000')
        with (SAMPLES / '01_gangnam_pg.csv').open(encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            columns, row = reader.fieldnames, next(reader)
        row.update({'거래번호': 'H-NEW-0001', '거래금액': '50000', 'PG수수료': '1500', '거래일시': '2026-09-08T20:00:00+09:00'})
        next_file = out / 'next-payment.csv'
        with next_file.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerow(row)

        path = base + '/ledger-sources/' + src['id'] + '/attribute-restorations'
        if args.browser:
            dump(out / 'browser-input.json', {'email': email, 'password': password, 'project_id': pid,
                 'table_id': src['table_id'], 'metric_id': metric['id'], 'samples': str(SAMPLES), 'next_file': str(next_file)})
            node = shutil.which('node')
            built = True
            build = start([node, 'node_modules/next/dist/bin/next', 'build'], ROOT / 'web', 'build')
            if build.wait(timeout=240):
                raise RuntimeError('Web build failed')
            web = start([node, 'node_modules/next/dist/bin/next', 'start', '-p', str(web_port), '-H', '127.0.0.1'], ROOT / 'web', 'web')
            runtime.wait_http(os.environ['LIVE_UI_URL'], web)
            browser = start([node, 'attribute-restoration.cjs'], ROOT / 'scripts/ui-eval', 'browser')
            if browser.wait(timeout=480):
                raise RuntimeError('Browser acceptance failed; inspect browser.json')
            report['browser'] = json.loads((out / 'browser.json').read_text(encoding='utf-8'))
            applied = report['browser']['applied']
        else:
            checked = request('POST', path + '/preview', json={'payment_method_column': '결제수단', 'channel_column': '판매채널', 'fee_column': 'PG수수료'})
            applied = request('POST', path + '/' + checked['id'] + '/apply')
            check('Duplicate upload adds zero after upgrade', upload('01_gangnam_pg.csv', (SAMPLES / '01_gangnam_pg.csv').read_bytes())['rows_added'], 0)
            check('New event appended after upgrade', upload(next_file.name, next_file.read_bytes())['rows_added'], 1)
            request('POST', base + '/metrics/' + metric['id'] + '/refresh')
        report['restoration'] = applied
        check('Restoration schema indexing queued', applied['index_status'], 'queued')
        runtime.wait_indexes(request, base)
        replay = request('POST', path + '/' + applied['id'] + '/apply')
        check('Apply replay does not repeat changes', replay['replayed'], True)
        check('Old pending upload requires new upload', request('GET', base + '/imports/' + pending['id'])['requires_reupload'], True)
        with db._connect() as conn:
            after_rows = conn.execute(sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(table))).fetchall()
            after_widget = conn.execute('SELECT * FROM dashboard_widgets WHERE id=%s', (metric['id'],)).fetchone()
            index = conn.execute('SELECT content FROM schema_embeddings WHERE table_meta_id=%s', (src['table_id'],)).fetchone()['content']
            registry = conn.execute('SELECT count(*) AS n FROM source_events WHERE source_id=%s', (src['id'],)).fetchone()['n']
        check('Historical row IDs and six original fields unchanged', [{k: row[k] for k in original_rows[0]} for row in after_rows[:54]], original_rows)
        check('Physical and registry row counts after new import', [len(after_rows), registry], [55, 55])
        check('Existing widget identity layout schedule preserved', {k: after_widget[k] for k in ['id', 'layout', 'refresh_interval_seconds']}, {k: original_widget[k] for k in ['id', 'layout', 'refresh_interval_seconds']})
        check('Existing metric definition preserved', after_widget['widget_data']['metric_definition'], original_widget['widget_data']['metric_definition'])
        check('Existing metric refresh sees new payment', after_widget['widget_data']['value'], '1408000')
        check('RAG catalog changed to include fee semantics', index != original_index and 'PG 수수료' in index and 'fee' in index, True)
        changes = request('GET', path + '/' + applied['id'] + '/changes?limit=100')
        check('Exactly 54 restoration journal rows', changes['total'], 54)
        check('Audit before/after fee', [changes['changes'][0]['before_normalized'].get('fee'), changes['changes'][0]['after_normalized']['fee']], [None, '3000'])
        calculated = request('POST', base + '/metrics/preview', json={'definition': {'table_id': src['table_id'], 'column': 'fee'}})
        check('Restored fee total plus new event', calculated['value'], '42240')
        report['after_widget'] = after_widget
        report['audit_sample'] = changes['changes'][:5]
        if args.browser:
            with db._connect() as conn:
                fees = conn.execute("SELECT * FROM dashboard_widgets WHERE project_id=%s AND title='복원된 PG 수수료'", (pid,)).fetchall()
                report['messages'] = conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at", (uid,)).fetchall()
            check('Real chat saved one fee metric', len(fees), 1)
            check('Real chat saved restored fee total', fees[0]['widget_data']['value'], '42240')
            check('Real chat used actual restored table', [fees[0]['widget_data']['metric_definition']['table_id'], fees[0]['widget_data']['metric_definition']['column']], [src['table_id'], 'fee'])
            check('Real chat fee metric manual schedule', fees[0]['refresh_interval_seconds'], 0)
            report['fee_widget'] = fees[0]
        report['passed'] = all(check['passed'] for check in report['checks'])
    finally:
        for process in [browser, build, web, api]:
            runtime.stop(process)
        db.close_pool()
        if created:
            assert name.startswith('dataez_restore_eval_') and len(name) == len('dataez_restore_eval_') + 32
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['temporary_database_removed'] = True
        if built:
            with (out / 'restore-build.log').open('w', encoding='utf-8') as log:
                restored = subprocess.run([shutil.which('node'), 'node_modules/next/dist/bin/next', 'build'], cwd=ROOT / 'web', env=original_env,
                                          stdout=log, stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN, timeout=240)
            report['ordinary_web_build_restored'] = restored.returncode == 0
            report['passed'] = report['passed'] and restored.returncode == 0
        for log in logs:
            log.close()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        dump(out / 'report.json', report)
        print(f'Report: {out / "report.json"}', flush=True)
    print(f'H acceptance: {report["passed"]}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
