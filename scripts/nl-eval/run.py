"""N: 50 real-model acceptance questions in a disposable pgvector database.

--live-llm makes paid configured-model calls. Without it only seed/oracle checks
run. API imports and embeddings are real; agents run the production sync loop.
"""
import argparse
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import dotenv_values

from cases import CASES, VERSION
from grading import grade
from oracle import KST, NAMES, STORE_NAMES, TABLE_STORE, csv_bytes, fixture

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('live_runtime', ROOT/'scripts/ui-eval/live-run.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=lambda o: sorted(o) if isinstance(o, set) else str(o))+'\n', encoding='utf-8')


def selection(value):
    selected = set()
    for part in (value or '01-50').split(','):
        bounds = part.split('-')
        selected.update(f'{i:02}' for i in range(int(bounds[0]), int(bounds[-1])+1))
    known = {c['id']: c for c in CASES}
    if not selected or selected-set(known): raise ValueError('Unknown/empty case selection')
    while True:
        added = {known[c]['depends'] for c in selected if known[c].get('depends')}-selected
        if not added: return [c for c in CASES if c['id'] in selected]
        selected |= added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm', action='store_true')
    parser.add_argument('--cases', help='IDs/ranges, e.g. 01-18,43; dependencies included')
    args = parser.parse_args()
    selected = selection(args.cases)
    admin = os.environ['DATAEZ_RAG_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    if config.get('host') not in {'localhost', '127.0.0.1', '::1'} or config.get('hostaddr'):
        raise ValueError('Only a loopback disposable database is accepted')
    name = 'dataez_nl_eval_'+uuid4().hex
    out = ROOT/'scripts/nl-eval/artifacts'/name
    out.mkdir(parents=True)
    local = dotenv_values(ROOT/'.env')
    for key in ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_ORCHESTRATOR_MODEL', 'OPENAI_EMBEDDING_MODEL']:
        if local.get(key) and key not in os.environ: os.environ[key] = local[key]
    if not os.environ.get('OPENAI_API_KEY'): raise ValueError('A real embedding/model API key is required')
    port = runtime.free_port()
    os.environ.update(DATABASE_URL=make_conninfo(admin, dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
        APP_ENV='development', RAG_ENABLED='true', INDEX_WORKER_ENABLED='true', STORAGE_BACKEND='local',
        LOCAL_STORAGE_PATH=str(out/'uploads'), METRIC_SCHEDULER_ENABLED='false', IMPORT_CLEANUP_ENABLED='false',
        UPLOAD_RATE_LIMIT_PER_MINUTE='200', QUERY_RATE_LIMIT_PER_MINUTE='200')
    sys.path.insert(0, str(ROOT/'api'))
    from app import db
    from app.agent import run_agent
    from app.config import settings
    from app.llm_telemetry import TurnLedger
    from app import rag
    logging.basicConfig(filename=str(out/'agent.log'), level=logging.INFO, encoding='utf-8')
    today = datetime.now(KST).date()
    rows = fixture(today)
    benchmark_files = ['cases.py', 'oracle.py', 'grading.py']
    source_files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'api/app').rglob('*.py'))
    digest = lambda paths: hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in paths)).hexdigest()
    report = dict(run_id=name, benchmark_version=VERSION, as_of=str(today), synthetic=True,
        real_postgres=True, real_embeddings=True, real_http_imports=True, real_models=args.live_llm,
        browser_evaluated=False, streaming_evaluated=False, agent_path='production run_agent',
        benchmark_sha256=digest(['scripts/nl-eval/'+p for p in benchmark_files]),
        source_sha256=digest(source_files), worker_model=settings.openai_model,
        router_model=settings.openai_orchestrator_model, embedding_model=settings.openai_embedding_model,
        cases=[], fixture_checks=[], retrieval=[], semantic_review='pending', passed=False,
        cost_note='Repository price-table estimate, not current billing; setup indexing is excluded from per-question usage.')
    dump(out/'fixtures.json', rows)
    api = None
    created = False
    log = (out/'api.log').open('w', encoding='utf-8')
    def check(label, actual, wanted):
        report['fixture_checks'].append(dict(check=label, actual=actual, expected=wanted, passed=actual == wanted))
        if actual != wanted: raise AssertionError(label)
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT/'db/init.sql').read_text(encoding='utf-8'))
        api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                               cwd=ROOT/'api', env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
                               creationflags=runtime.HIDDEN)
        runtime.wait_http(f'http://127.0.0.1:{port}/health', api)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=240) as client:
            def request(method, path, **kw):
                response = client.request(method, path, **kw)
                if response.is_error: raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.text[:800]}')
                return response.json()
            password = secrets.token_urlsafe(24)+'Aa1!'
            owner = request('POST', '/api/auth/signup', json=dict(email=name+'@example.test', password=password, name='자연어 평가'))
            foreign = request('POST', '/api/auth/signup', json=dict(email='foreign-'+name+'@example.test', password=password, name='격리 평가'))
            uid = owner['user_id']
            client.headers['Authorization'] = 'Bearer '+owner['access_token']
            stores, tables, sources = {}, {}, {}
            for key, title in STORE_NAMES.items():
                auth = foreign if key == 'foreign' else owner
                stores[key] = request('POST', '/api/projects', headers={'Authorization': 'Bearer '+auth['access_token']}, json=dict(name=title))['id']
            for key, data in rows.items():
                pid = stores[TABLE_STORE[key]]
                auth = foreign if key == 'foreign' else owner
                headers = {'Authorization': 'Bearer '+auth['access_token']}
                filename = {'pg': 'star-payments.csv', 'cash': 'cash-receipts.csv'}.get(key, key+'-synthetic.csv')
                if key in {'pg', 'cash'}:
                    imported_rows = [dict(event_id=f'{key}-{i:04}', **r) for i, r in enumerate(data)]
                    mapping = dict(amount_column='amount', occurred_at_column='occurred_at', event_id_column='event_id',
                        currency_column='currency', payment_method_column='payment_method', channel_column='channel', fee_column='fee', event_kind='signed')
                    source = request('POST', f'/api/projects/{pid}/ledger-sources', json=dict(name=NAMES[key], provider='합성PG' if key == 'pg' else '직접기록', account=key, feed='독립 결제취소 이벤트', mapping=mapping))
                    sources[key] = source['id']
                    batch = request('POST', f'/api/projects/{pid}/imports',
                                    files={'file': (filename, csv_bytes(imported_rows))}, data={'source_id': source['id'], 'request_key': str(uuid4())})
                    batch = request('POST', f'/api/projects/{pid}/imports/{batch["id"]}/preview')
                    committed = request('POST', f'/api/projects/{pid}/imports/{batch["id"]}/commit', json={'preview_token': batch['preview_token']})
                    check(key+' committed rows', committed['rows_added'], len(data))
                    tables[key] = source['table_id']
                else:
                    tables[key] = request('POST', f'/api/projects/{pid}/tables/import', headers=headers,
                        files={'file': (filename, csv_bytes(data))}, data={'table_name': NAMES[key]})['id']
                if key != 'foreign': runtime.wait_indexes(request, f'/api/projects/{pid}')
            pid = stores['main']
            dump(out/'fixture-ids.json', dict(stores=stores, tables=tables))
            with db._connect() as conn:
                for key in rows:
                    if key == 'settlement': continue
                    user = foreign['user_id'] if key == 'foreign' else uid
                    actual = conn.execute(sql.SQL('SELECT count(*) AS n,sum(amount)::text AS total FROM {}').format(sql.Identifier(db.get_user_table_name(user, tables[key])))).fetchone()
                    check(key+' row count', actual['n'], len(rows[key]))
                    check(key+' exact net', Decimal(actual['total']), sum((Decimal(r['amount']) for r in rows[key]), Decimal(0)))
            forbidden = client.get(f'/api/projects/{stores["foreign"]}/tables/{tables["foreign"]}')
            check('Foreign HTTP table unavailable', forbidden.status_code, 404)
            retrieval_usage = TurnLedger()
            for query, target in [('star-payments.csv 승인 취소 결제', 'pg'), ('cash-receipts.csv 현금 수납 기록', 'cash'), ('정산 입금 참고자료', 'settlement')]:
                hits = rag.hybrid_search_schema(uid, pid, query, top_k=5, ledger=retrieval_usage)
                ids = [str(h['table_meta_id']) for h in hits]
                allowed = {tables[k] for k in tables if TABLE_STORE[k] == 'main'}
                report['retrieval'].append(dict(query=query, target=target, rank=ids.index(tables[target])+1 if tables[target] in ids else None, scoped=set(ids) <= allowed))
                check('RAG recall@5: '+target, tables[target] in ids, True)
                check('RAG scope: '+target, set(ids) <= allowed, True)
            report['retrieval_usage'] = retrieval_usage.summary()
            print(f'{name}: fixture and retrieval checks passed', flush=True)

            def widgets():
                with db._connect() as conn:
                    return conn.execute('SELECT id,project_id,user_id,title,widget_data,layout,refresh_interval_seconds FROM dashboard_widgets ORDER BY id').fetchall()
            def snapshot():
                state = []
                with db._connect() as conn:
                    for key in sorted(tables):
                        user = foreign['user_id'] if key == 'foreign' else uid
                        state.append(conn.execute(sql.SQL('SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(db.get_user_table_name(user, tables[key])))).fetchall())
                    for table in ['projects', 'table_meta', 'ledger_sources', 'import_batches', 'import_rows', 'cash_entries']:
                        state.append(conn.execute(sql.SQL('SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))).fetchall())
                return hashlib.sha256(json.dumps(state, default=str, sort_keys=True).encode()).hexdigest()
            history = []
            if args.live_llm:
                for case in selected:
                    if datetime.now(KST).date() != today: raise RuntimeError('KST date changed; rerun with fresh relative-date fixtures')
                    if not case.get('depends'):
                        history = []
                        with db._connect() as conn: conn.execute('DELETE FROM dashboard_widgets WHERE project_id=%s', (pid,))
                    before = widgets()
                    baseline = snapshot()
                    question = case['question'].format(foreign_store=stores['foreign'], foreign_table=tables['foreign'])
                    record = dict(id=case['id'], question=question, semantic_review='pending', passed=False)
                    start = time.monotonic()
                    print(f"Case {case['id']}: {question}", flush=True)
                    evidence = None
                    try:
                        result = run_agent(uid, pid, STORE_NAMES['main'], db.list_table_metas(pid, uid), history, question)
                        evidence = asdict(result)
                        after = widgets()
                        checks, details = grade(case, evidence, before, after, baseline == snapshot(), rows, today, tables, stores)
                        record.update(checks=checks, answer=result.answer, usage=result.usage,
                            tools=[s.tool_name for s in result.steps if s.type == 'tool_call'], passed=all(checks.values()))
                        dump(out/f'case-{case["id"]}.json', dict(case=record, evidence=evidence, details=details, widgets_before=before, widgets_after=after))
                        history.extend([dict(role='user', content=question), dict(role='assistant', content=result.answer, steps=[s.to_dict() for s in result.steps])])
                    except Exception as exc:
                        record.update(error=type(exc).__name__+': '+str(exc))
                        dump(out/f'case-{case["id"]}.json', dict(case=record, evidence=evidence))
                    record['seconds'] = round(time.monotonic()-start, 3)
                    report['cases'].append(record)
                    dump(out/'report.json', report)
                    print(f"  {'PASS' if record['passed'] else 'FAIL'} {record['seconds']}s {[k for k,v in record.get('checks',{}).items() if not v]} {record.get('error','')}", flush=True)
            report['automatic_passed'] = sum(c['passed'] for c in report['cases'])
            report['usage'] = {k: sum(c.get('usage', {}).get(k, 0) or 0 for c in report['cases']) for k in ['calls', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd']}
            report['source_unchanged_during_run'] = report['source_sha256'] == digest(source_files)
            report['automatic_acceptance'] = all(c['passed'] for c in report['fixture_checks']) and all(c['passed'] for c in report['cases']) and report['source_unchanged_during_run']
    finally:
        runtime.stop(api)
        db.close_pool()
        if created:
            assert re.fullmatch(r'dataez_nl_eval_[0-9a-f]{32}', name)
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            report['temporary_database_removed'] = True
        log.close()
        report['finished_at'] = datetime.now(KST).isoformat()
        dump(out/'report.json', report)
        print('Report: '+str(out/'report.json'), flush=True)
    # Automatic behavior is not full acceptance until responses are reviewed.
    return 0 if report.get('automatic_acceptance') else 1


if __name__ == '__main__': raise SystemExit(main())
