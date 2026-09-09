"""G acceptance on disposable pgvector DB; --browser includes paid real chat.

Uses project-configured OpenAI models. Never opens a production database.
Without --browser, runs HTTP imports and deterministic saved-metric checks.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
import json
import os
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

from oracle import ROOT, SAMPLES, expected

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
    name = 'dataez_payment_eval_' + uuid4().hex
    out = ROOT / 'scripts/payment-eval/artifacts' / name
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
    from app.agent import run_agent
    from app.config import settings
    report = {'run_id': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
              'real_postgres': True, 'real_embeddings': True, 'browser_evaluated': args.browser,
              'worker_model': settings.openai_model, 'router_model': settings.openai_orchestrator_model,
              'checks': [], 'agent': [], 'oracle': expected(), 'passed': False}
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
        email, password = name + '@example.test', secrets.token_urlsafe(20) + 'Aa1!'

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.is_error:
                raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:1000]}')
            return response.json()

        owner = request('POST', '/api/auth/signup', json={'email': email, 'password': password, 'name': 'G 합성 검증'})
        uid = owner['user_id']
        client.headers['Authorization'] = 'Bearer ' + owner['access_token']
        pid = request('POST', '/api/projects', json={'name': '결제 분석 검증점'})['id']
        base = f'/api/projects/{pid}'
        if args.browser:
            dump(out / 'browser-input.json', {'email': email, 'password': password, 'project_id': pid, 'samples': str(SAMPLES)})
            node = shutil.which('node')
            built = True
            build = start([node, 'node_modules/next/dist/bin/next', 'build'], ROOT / 'web', 'build')
            if build.wait(timeout=240):
                raise RuntimeError('Web build failed')
            web = start([node, 'node_modules/next/dist/bin/next', 'start', '-p', str(web_port), '-H', '127.0.0.1'], ROOT / 'web', 'web')
            runtime.wait_http(os.environ['LIVE_UI_URL'], web)
            browser = start([node, 'payment-attributes.cjs'], ROOT / 'scripts/ui-eval', 'browser')
            if browser.wait(timeout=480):
                raise RuntimeError('Browser acceptance failed; inspect browser.json')
            report['browser'] = json.loads((out / 'browser.json').read_text(encoding='utf-8'))
            src = report['browser']['source']
        else:
            manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
            src = request('POST', base + '/ledger-sources', json={'name': '결제 분석원장', 'provider': '가상PG', 'account': 'G001', 'feed': '결제취소이벤트',
                'mapping': {**manifest['pg_mapping'], 'payment_method_column': '결제수단', 'channel_column': '판매채널', 'fee_column': 'PG수수료'}})
            for filename in ['01_gangnam_pg.csv', '03_gangnam_pg_overlap.csv']:
                batch = request('POST', base + '/imports', data={'source_id': src['id'], 'request_key': str(uuid4())}, files={'file': (filename, (SAMPLES / filename).read_bytes())})
                url = base + '/imports/' + batch['id']
                ready = request('POST', url + '/preview')
                request('POST', url + '/commit', json={'preview_token': ready['preview_token']})
        check('54 unique PG events', request('GET', base + '/ledger-sources')['sources'][0]['row_count'], report['oracle']['rows'])
        for group, expected_group in [('payment_method', 'methods'), ('channel', 'channels')]:
            for column in ['amount', 'fee']:
                data = request('POST', base + '/metrics/preview', json={'definition': {'table_id': src['table_id'], 'column': column, 'group_by': group}})
                check(group + '/' + column, {r['dimension']: str(Decimal(r['value'])) for r in data['data']},
                      {k: v[column] for k, v in report['oracle'][expected_group].items()})
        runtime.wait_indexes(request, base)
        hits = rag.hybrid_search_schema(uid, pid, 'PG 결제수단별 매출과 판매채널별 수수료', top_k=3)
        check('Attribute retrieval top1', str(hits[0]['table_meta_id']) if hits else None, src['table_id'])

        if args.browser:
            with db._connect() as conn:
                widgets = conn.execute('SELECT * FROM dashboard_widgets WHERE project_id=%s ORDER BY created_at', (pid,)).fetchall()
                report['browser_messages'] = conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at", (uid,)).fetchall()
            check('Browser saved two metrics', len(widgets), 2)
            for title, group, column, expected_group, interval in [('결제수단별 순결제액', 'payment_method', 'amount', 'methods', 3600), ('채널별 PG 수수료', 'channel', 'fee', 'channels', 0)]:
                widget = next(w for w in widgets if w['title'] == title)
                definition = widget['widget_data']['metric_definition']
                check(title + ' definition', [definition['table_id'], definition['operation'], definition['column'], definition['group_by'], definition['filters']], [src['table_id'], 'sum', column, group, []])
                check(title + ' values', {r['dimension']: r['value'] for r in widget['widget_data']['data']}, {k: v[column] for k, v in report['oracle'][expected_group].items()})
                check(title + ' schedule', widget['refresh_interval_seconds'], interval)
            report['widgets'] = widgets
            print('Browser: 54 events + two exact category charts and schedules passed', flush=True)

            questions = [
                ('card', '결제 분석원장에서 전체 기간 카드 결제수단의 순결제액을 미리 보여줘. 저장하지 마.', '980000', 'amount'),
                ('fee', '결제 분석원장의 전체 기간 PG 수수료 합계를 미리 보여줘. 저장하지 마.', report['oracle']['fee_total'], 'fee'),
            ]
            for key, question, wanted, column in questions:
                result = run_agent(uid, pid, '결제 분석 검증점', db.list_table_metas(pid, uid), [], question)
                previews = [s.tool_output for s in result.steps if s.tool_name == 'preview_metric' and not s.tool_output.get('error')]
                passed = any(Decimal(p.get('value', '-1')) == Decimal(wanted) and p.get('metric_definition', {}).get('column') == column for p in previews) and not result.mutations_performed
                report['agent'].append({'case': key, 'question': question, 'automatic_passed': passed, 'result': asdict(result)})
                dump(out / 'report.json', report)
                print(f'Real agent {key}: {passed}', flush=True)

            # An independent imported table keeps the complete PG source intact.
            request('POST', base + '/tables/import', data={'table_name': '수수료 누락 검증'}, files={'file': ('missing.csv', '거래금액,PG수수료\n100,3\n200,\n'.encode())})
            for key, question in [
                ('missing_count', '수수료 누락 검증 장부에서 전체 기간 PG수수료가 미제공인 행 건수 지표를 대시보드에 저장해줘. 제목은 수수료 미제공 건수, 자동갱신은 꺼줘.'),
                ('missing_total', '수수료 누락 검증 장부의 전체 기간 모든 거래의 PG수수료 합계를 대시보드에 저장해줘. 누락이 있어 전체 합계를 알 수 없다면 저장하지 말고 알려줘.')]:
                before = len(request('GET', base + '/metrics')['metrics'])
                result = run_agent(uid, pid, '결제 분석 검증점', db.list_table_metas(pid, uid), [], question)
                saved = request('GET', base + '/metrics')['metrics']
                if key == 'missing_count':
                    with db._connect() as conn:
                        found = conn.execute('SELECT widget_data FROM dashboard_widgets WHERE project_id=%s AND title=%s', (pid, '수수료 미제공 건수')).fetchall()
                    passed = len(saved) == before + 1 and len(found) == 1 and found[0]['widget_data']['value'] == 1 and found[0]['widget_data']['metric_definition']['operation'] == 'count'
                else:
                    passed = len(saved) == before and not result.mutations_performed and any(word in result.answer for word in ['미제공', '누락', '비어'])
                report['agent'].append({'case': key, 'question': question, 'automatic_passed': passed, 'result': asdict(result)})
                dump(out / 'report.json', report)
                print(f'Real agent {key}: {passed}', flush=True)
        report['passed'] = all(c['passed'] for c in report['checks']) and all(c['automatic_passed'] for c in report['agent'])
    finally:
        for process in [browser, build, web, api]:
            runtime.stop(process)
        db.close_pool()
        if created:
            assert name.startswith('dataez_payment_eval_') and len(name) == len('dataez_payment_eval_') + 32
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
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
