"""F: real OpenAI embeddings + pgvector + HTTP imports + optional live chat UI.

Requires a loopback DATAEZ_RAG_TEST_DATABASE_URL with CREATE DATABASE rights.
All fixtures are synthetic; all application writes use a disposable database.
No API, model response, browser request or retrieval vector is mocked.
"""
import argparse
from dataclasses import asdict
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
SAMPLES = ROOT / 'samples/pg-evaluation'
spec = importlib.util.spec_from_file_location('live_runtime', ROOT / 'scripts/ui-eval/live-run.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Also build web and send paid real streaming chat turns')
    parser.add_argument('--browser-only', action='store_true', help='Repeat HTTP seed and browser checks without repeating retrieval/agent goldens')
    args = parser.parse_args()
    args.browser = args.browser or args.browser_only
    admin = os.environ['DATAEZ_RAG_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    assert config.get('host') in {'localhost', '127.0.0.1', '::1'} and not config.get('hostaddr')
    name = 'dataez_rag_eval_' + uuid4().hex
    out = ROOT / 'scripts/rag-eval/artifacts' / name
    out.mkdir(parents=True)
    local = dotenv_values(ROOT / '.env')
    for key in ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_ORCHESTRATOR_MODEL', 'OPENAI_EMBEDDING_MODEL']:
        if local.get(key) and key not in os.environ:
            os.environ[key] = local[key]
    api_port, web_port = runtime.free_port(), runtime.free_port()
    original_env = os.environ.copy()
    os.environ.update(DATABASE_URL=make_conninfo(admin, dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
        APP_ENV='development', RAG_ENABLED='true', INDEX_WORKER_ENABLED='true', STORAGE_BACKEND='local', LOCAL_STORAGE_PATH=str(out / 'uploads'),
        METRIC_SCHEDULER_ENABLED='false', IMPORT_CLEANUP_ENABLED='false',
        UPLOAD_RATE_LIMIT_PER_MINUTE='100', ALLOWED_ORIGINS=f'http://127.0.0.1:{web_port}',
        NEXT_PUBLIC_API_URL=f'http://127.0.0.1:{api_port}', LIVE_UI_URL=f'http://127.0.0.1:{web_port}', LIVE_ARTIFACTS=str(out))
    sys.path.insert(0, str(ROOT / 'api'))
    from app import db, rag
    from app.agent import run_agent
    from app.agent_tools import ToolExecutor
    from app.config import settings
    from app.llm_telemetry import TurnLedger
    report = {'run_id': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
              'real_embeddings': True, 'real_postgres': True, 'api_mocks': False,
              'embedding_model': settings.openai_embedding_model, 'worker_model': settings.openai_model,
              'router_model': settings.openai_orchestrator_model, 'browser_only': args.browser_only,
              'retrieval': [], 'checks': [], 'agent': [], 'passed': False}
    logs, api, web, created, web_built = [], None, None, False, False
    build = browser = None

    def check(label, actual, expected):
        report['checks'].append({'check': label, 'actual': actual, 'expected': expected, 'passed': actual == expected})
        if actual != expected:
            raise AssertionError(label)

    def start(command, cwd, label):
        log = (out / (label + '.log')).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=cwd, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
                                creationflags=runtime.HIDDEN)

    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT / 'db/init.sql').read_text(encoding='utf-8'))
        api = start([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port)], ROOT / 'api', 'api')
        runtime.wait_http(os.environ['NEXT_PUBLIC_API_URL'] + '/health', api)
        with db._connect() as conn:
            report['pgvector_version'] = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
        client = httpx.Client(base_url=os.environ['NEXT_PUBLIC_API_URL'], timeout=180)

        def request(method, path, *, token=None, **kw):
            res = client.request(method, path, headers={'Authorization': 'Bearer ' + token} if token else {}, **kw)
            if res.is_error:
                raise RuntimeError(f'{method} {path}: HTTP {res.status_code}: {res.text[:1000]}')
            return res.json()

        email, password = name + '@example.test', secrets.token_urlsafe(20) + 'Aa1!'
        owner = request('POST', '/api/auth/signup', json={'email': email, 'password': password, 'name': '합성 검색 검증'})
        foreign = request('POST', '/api/auth/signup', json={'email': 'foreign-' + email, 'password': password, 'name': '격리 검증'})
        token, uid = owner['access_token'], owner['user_id']
        def store(title, auth=token):
            return request('POST', '/api/projects', token=auth, json={'name': title})['id']
        pid, second, foreign_pid, empty_pid = store('RAG 검증 강남점'), store('RAG 검증 홍대점'), store('외부 가게', foreign['access_token']), store('자료 없는 가게')
        manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
        tables = {}

        def source(key, title, mapping):
            src = request('POST', f'/api/projects/{pid}/ledger-sources', token=token,
                json={'name': title, 'provider': '가상PG' if key == 'pg' else '직접입력', 'account': '0001001', 'feed': '결제취소이벤트', 'mapping': mapping})
            tables[key] = str(src['table_id'])
            return src

        def import_batch(src, filename, decisions=None):
            batch = request('POST', f'/api/projects/{pid}/imports', token=token,
                data={'source_id': src['id'], 'request_key': str(uuid4())}, files={'file': (filename, (SAMPLES / filename).read_bytes())})
            url = f'/api/projects/{pid}/imports/{batch["id"]}'
            batch = request('POST', url + '/preview', token=token)
            if decisions:
                batch = request('POST', url + '/decisions', token=token, json={'preview_token': batch['preview_token'],
                    'decisions': [{'row_number': int(n), 'decision': d} for n, d in decisions.items()]})
            return request('POST', url + '/commit', token=token, json={'preview_token': batch['preview_token']})

        pg = source('pg', '온라인 결제원장', manifest['pg_mapping'])
        cash = source('cash', '현금 수납원장', manifest['cash_mapping'])
        import_batch(pg, '01_gangnam_pg.csv')
        import_batch(pg, '03_gangnam_pg_overlap.csv')
        import_batch(cash, '08_cash_first.csv')
        import_batch(cash, '09_cash_review.csv', manifest['cash_decisions'])

        def table(key, title, filename, content, project=pid, auth=token):
            meta = request('POST', f'/api/projects/{project}/tables/import', token=auth,
                data={'table_name': title}, files={'file': (filename, content.encode() if isinstance(content, str) else content)})
            if project == pid:
                tables[key] = str(meta['id'])
            return str(meta['id'])

        table('settle', '정산 참고자료', '10_settlement_reference.csv', (SAMPLES / '10_settlement_reference.csv').read_bytes())
        table('booking', '방문 예약', 'booking.csv', '예약일,예약상태,예약금,잔금\n2026-09-03,노쇼,20000,50000\n2026-09-04,방문완료,30000,70000\n')
        table('expense', '가게 운영지출', 'operating-cost.csv', '지출일,항목,금액\n2026-09-01,임차료,800000\n2026-09-03,직원 인건비,900000\n')
        table('august', '8월 월간 요약', 'august-summary.csv', '기준일,월매출합계,설명\n2026-08-31,100000,8월 마감 집계표 원장과 합산 금지\n')
        table('september', '9월 월간 요약', 'september-summary.csv', '기준일,월매출합계,설명\n2026-09-08,1258000,9월 집계표 원장과 합산 금지\n')
        table('stock', '재고 입출고', 'inventory.csv', '기록일,품목,입고수량,출고수량\n2026-09-02,종이컵,100,15\n')
        table('campaign', '쿠폰 발급', 'coupon.csv', '발급일,쿠폰명,발급수,사용수\n2026-09-01,단골 감사,50,12\n')
        table('foreign', '온라인 결제원장', '01_gangnam_pg.csv', '일시,금액,비고\n2026-09-01,777777,홍대전용원장\n', second)
        table('foreign', '온라인 결제원장', '01_gangnam_pg.csv', '일시,금액,비고\n2026-09-01,888888,외부소유자원장\n', foreign_pid, foreign['access_token'])

        def document(filename, body, project=pid, auth=token):
            return request('POST', f'/api/projects/{project}/documents', token=auth, files={'file': (filename, body.encode())})['file_id']
        docs = {
            'refund': document('순결제액 산정 기준.md', '# 합성 강남점 순결제액 기준\n순결제액은 승인액과 음수 취소액을 합산한다. 부분 취소가 음수로 기록되면 다시 차감하지 않는다. 정산입금액과 결제매출을 합산하지 않는다. 이 문서는 계산 규칙이며 거래 원장이 아니다.'),
            'booking': document('예약 취소 안내.md', '# 합성 강남점 예약 규정\n방문 24시간 이전 취소는 예약금 전액 환불한다. 방문 당일 노쇼는 예약금의 30%를 차감한다. 실제 결제 기록 확인은 별도 원장을 이용한다.'),
            'closing': document('마감 절차.md', '# 합성 마감 절차\n직원은 매일 오후 10시에 현금을 세고 수납원장과 대조한다. 부족액은 점장에게 보고한다.'),
        }
        other_doc = document('예약 취소 안내.md', '# 홍대점 전용 규정\n당일 노쇼는 예약금의 90%를 차감한다.', second)
        document('예약 취소 안내.md', '# 외부 소유자 규정\n당일 노쇼는 예약금의 99%를 차감한다.', foreign_pid, foreign['access_token'])
        for project, auth in [(pid, token), (second, token), (foreign_pid, foreign['access_token'])]:
            runtime.wait_indexes(lambda method, path: request(method, path, token=auth), f'/api/projects/{project}')
        check('All current-store tables indexed', rag.schema_index_coverage(uid, pid), {'total': 9, 'indexed': 9, 'missing': 0, 'updating': 0})
        wrong = client.delete(f'/api/projects/{pid}/documents/{other_doc}', headers={'Authorization': 'Bearer ' + token})
        check('Cross-store document delete rejected', wrong.status_code, 404)
        check('Other-store document retained', len(request('GET', f'/api/projects/{second}/documents', token=token)['documents']), 1)
        print('HTTP seed: 9 tables, 3 documents plus two isolated stores indexed with real embeddings', flush=True)

        goldens = [
            ('schema', '01_gangnam_pg.csv를 반영한 장부', 'pg'),
            ('schema', '03_gangnam_pg_overlap.csv 원본 파일', 'pg'),
            ('schema', '가상PG 승인 취소 거래 내역', 'pg'),
            ('schema', '온라인 결제원장의 전체 순결제액', 'pg'),
            ('schema', '현금으로 받은 돈 기록', 'cash'),
            ('schema', '08_cash_first.csv 원본', 'cash'),
            ('schema', '09_cash_review.csv가 반영된 자료', 'cash'),
            ('schema', '정산 입금액과 수수료', 'settle'),
            ('schema', '10_settlement_reference.csv', 'settle'),
            ('schema', '방문하지 않은 예약의 예약금과 미납 잔금', 'booking'),
            ('schema', '가게 월세와 직원 급여 지출', 'expense'),
            ('schema', '지난 8월 마감 집계표', 'august'),
            ('schema', '2026년 9월 월간 요약 집계', 'september'),
            ('schema', '매장 물품 들어오고 나간 수량', 'stock'),
            ('schema', '단골 쿠폰 발급과 사용수', 'campaign'),
            ('document', '부분 환불이 음수면 순결제액에서 또 빼야 하나', 'refund'),
            ('document', '정산 입금과 매출을 더해도 되는지 계산 기준', 'refund'),
            ('document', '당일 예약에 오지 않은 손님의 예약금 차감 비율', 'booking'),
            ('document', '하루 전 방문 취소의 예약금 환불 규정', 'booking'),
            ('document', '현금 시재를 언제 세고 누구에게 보고하는가', 'closing'),
        ]
        query_usage = TurnLedger()
        if args.browser_only:
            goldens = []
        for kind, query, target in goldens:
            start_at = time.monotonic()
            hits = (rag.hybrid_search_schema(uid, pid, query, top_k=3, ledger=query_usage) if kind == 'schema'
                    else rag.hybrid_search_documents(uid, query, project_id=pid, top_k=3, ledger=query_usage))
            field, wanted = ('table_meta_id', tables[target]) if kind == 'schema' else ('file_id', docs[target])
            ids = [str(h[field]) for h in hits]
            allowed = set(tables.values()) if kind == 'schema' else set(docs.values())
            rank = ids.index(wanted) + 1 if wanted in ids else None
            case = {'kind': kind, 'query': query, 'target': target, 'rank': rank, 'hit_at_1': rank == 1,
                    'hit_at_3': rank is not None, 'scope_passed': set(ids) <= allowed,
                    'seconds': round(time.monotonic() - start_at, 3), 'results': hits}
            report['retrieval'].append(case)
            dump(out / 'report.json', report)
            print(f'Retrieval {len(report["retrieval"]):02}/{len(goldens)}: {target} rank={rank}', flush=True)
        report['retrieval_usage'] = query_usage.summary()
        if report['retrieval']:
            check('No retrieval crosses store/owner scope', all(c['scope_passed'] for c in report['retrieval']), True)
        check('Empty store returns no_matches', ToolExecutor(uid, empty_pid).execute('search_schema', '{"query":"매출"}')['status'], 'no_matches')
        with db._connect() as conn:
            conn.execute('DELETE FROM schema_embeddings WHERE table_meta_id=%s', (tables['stock'],))
        check('Missing index explicitly reported', ToolExecutor(uid, pid).execute('search_schema', '{"query":"재고"}')['status'], 'index_incomplete')
        check('Reindex repairs missing entry', rag.upsert_schema_embedding(uid, pid, tables['stock']), True)
        check('Document listing stays in store', len(request('GET', f'/api/projects/{pid}/documents', token=token)['documents']), 3)
        # Exercise an actual SQL failure in this disposable DB, then restore it.
        with db._connect() as conn:
            conn.execute('ALTER TABLE schema_embeddings RENAME TO schema_embeddings_test_unavailable')
        try:
            result = ToolExecutor(uid, pid).execute('search_schema', '{"query":"결제"}')
            check('DB search failure is not no data', result.get('error'), 'rag_unavailable')
        finally:
            with db._connect() as conn:
                conn.execute('ALTER TABLE schema_embeddings_test_unavailable RENAME TO schema_embeddings')

        questions = [
            ('net', '의미 검색으로 01_gangnam_pg.csv가 반영된 결제 장부를 먼저 찾고, 전체 기간 순결제액 합계를 미리 보여줘. 저장하지 마.'),
            ('policy', '업로드한 문서를 검색해서 우리 가게의 당일 노쇼 예약금 차감 비율을 알려줘. 근거 파일명도 적어줘.'),
            ('missing', '의미 검색으로 내일 강남점 날씨에 따른 예상 매출 지표를 만들어 저장해줘. 지금 올린 자료만으로 가능한지 먼저 확인해줘.'),
        ]
        if args.browser_only:
            questions = []
        for key, question in questions:
            result = run_agent(uid, pid, 'RAG 검증 강남점', db.list_table_metas(pid, uid), [], question)
            payload = asdict(result)
            used = [s.tool_name for s in result.steps if s.type == 'tool_call']
            automatic = (('search_schema' in used and '1,358,000' in result.answer and not result.mutations_performed) if key == 'net'
                else ('search_documents' in used and '30%' in result.answer and '예약 취소 안내.md' in result.answer and '90%' not in result.answer and '99%' not in result.answer) if key == 'policy'
                else ('search_schema' in used and not result.mutations_performed))
            report['agent'].append({'case': key, 'question': question, 'automatic_passed': automatic, 'result': payload})
            dump(out / 'report.json', report)
            print(f'Real agent {key}: automatic={automatic}, tools={used}', flush=True)

        if args.browser:
            dump(out / 'browser-input.json', {'email': email, 'password': password, 'project_id': pid})
            node = shutil.which('node')
            web_built = True
            build = start([node, 'node_modules/next/dist/bin/next', 'build'], ROOT / 'web', 'build')
            if build.wait(timeout=240):
                raise RuntimeError('Web build failed; see build.log')
            web = start([node, 'node_modules/next/dist/bin/next', 'start', '-p', str(web_port), '-H', '127.0.0.1'], ROOT / 'web', 'web')
            runtime.wait_http(os.environ['LIVE_UI_URL'], web)
            browser = start([node, 'rag-chat.cjs'], ROOT / 'scripts/ui-eval', 'browser')
            if browser.wait(timeout=420):
                raise RuntimeError('Browser acceptance failed; see browser.log')
            report['browser'] = json.loads((out / 'browser.json').read_text(encoding='utf-8'))
            with db._connect() as conn:
                messages = conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at", (uid,)).fetchall()
                widget = conn.execute('SELECT * FROM dashboard_widgets WHERE project_id=%s', (pid,)).fetchall()
            report['browser_messages'] = messages
            check('Browser saved one metric', len(widget), 1)
            check('Browser saved correct value', str(widget[0]['widget_data']['value']), '1358000')
            check('Follow-up changed same metric to hourly', widget[0]['refresh_interval_seconds'], 3600)
            check('Streaming query embedding recorded', messages[0]['usage']['by_role']['embedding']['calls'] >= 1, True)
        report['hit_at_1'] = sum(c['hit_at_1'] for c in report['retrieval'])
        report['hit_at_3'] = sum(c['hit_at_3'] for c in report['retrieval'])
        report['passed'] = (all(c['passed'] for c in report['checks']) and report['hit_at_3'] == len(goldens)
                            and all(c['automatic_passed'] for c in report['agent']))
    finally:
        runtime.stop(browser)
        runtime.stop(build)
        runtime.stop(web)
        runtime.stop(api)
        db.close_pool()
        if created:
            assert name.startswith('dataez_rag_eval_') and len(name) == 48
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['temporary_database_removed'] = True
        # Restore the ordinary frontend build; do not leave its API URL pointing at a dead test port.
        if web_built:
            with (out / 'restore-build.log').open('w', encoding='utf-8') as log:
                restored = subprocess.run([shutil.which('node'), 'node_modules/next/dist/bin/next', 'build'],
                    cwd=ROOT / 'web', env=original_env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=runtime.HIDDEN, timeout=240)
            report['ordinary_web_build_restored'] = restored.returncode == 0
            if restored.returncode:
                report['passed'] = False
        for log in logs:
            log.close()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        dump(out / 'report.json', report)
        print(f'Report: {out / "report.json"}', flush=True)
    print(f'F automatic acceptance: {report["passed"]}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
