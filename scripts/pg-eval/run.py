"""E acceptance: synthetic PG files -> real PostgreSQL -> optional real agent.

Requires a loopback DATAEZ_TEST_DATABASE_URL with CREATE DATABASE permission.
The generated database is always dropped. No production DB/API/browser is used.
LLM responses are not mocked. RAG is explicitly off: portable PG lacks pgvector.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import dotenv_values

from oracle import ROOT, SAMPLES, expected


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-llm', action='store_true', help='Make paid calls using configured project models')
    parser.add_argument('--cases', help='Comma-separated case IDs; 03/04 automatically include their prerequisite turns')
    args = parser.parse_args()
    admin = os.environ['DATAEZ_TEST_DATABASE_URL']
    config = conninfo_to_dict(admin)
    if config.get('host') not in {'127.0.0.1', 'localhost', '::1'} or config.get('hostaddr'):
        raise ValueError('A loopback test database is required')
    name = 'dataez_eval_' + uuid4().hex
    out = ROOT / 'scripts/pg-eval/artifacts' / name
    out.mkdir(parents=True)
    local = dotenv_values(ROOT / '.env')
    for key in ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_ORCHESTRATOR_MODEL']:
        if local.get(key) and key not in os.environ:
            os.environ[key] = local[key]
    os.environ.update(DATABASE_URL=make_conninfo(admin, dbname=name), JWT_SECRET_KEY=secrets.token_hex(32),
                      APP_ENV='development', RAG_ENABLED='false', STORAGE_BACKEND='local',
                      LOCAL_STORAGE_PATH=str(out / 'uploads'), METRIC_SCHEDULER_ENABLED='false',
                      IMPORT_CLEANUP_ENABLED='false')
    if not args.live_llm:
        os.environ.setdefault('OPENAI_API_KEY', 'unused-fixture-check')
    sys.path.insert(0, str(ROOT / 'api'))
    from app import db, ledger_imports as ledger, dashboard_metrics as metrics, table_imports
    from app.payment_imports import PaymentImportMapping, prepare_payment_import
    from app.import_validation import ImportValidationError
    from app.ledger_routes import RowDecision
    from app.metric_definitions import MetricDefinition, MultiMetricDefinition
    from app.storage import StorageService
    from app.exceptions import AppException
    from app.config import settings

    report = {'run_id': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'synthetic': True,
              'real_postgres': True, 'live_llm': args.live_llm, 'rag_evaluated': False,
              'rag_reason': 'Portable PostgreSQL has no pgvector; exact schema/catalog and real SQL tools evaluated.',
              'http_browser_evaluated': False, 'business_files_evaluated': False,
              'worker_model': settings.openai_model, 'router_model': settings.openai_orchestrator_model,
              'data_checks': [], 'cases': [], 'passed': False}
    oracle = expected()
    dump(SAMPLES / 'expected.json', oracle)
    manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
    created = False

    def check(label, actual, wanted):
        success = actual == wanted
        report['data_checks'].append({'check': label, 'actual': actual, 'expected': wanted, 'passed': success})
        if not success:
            raise AssertionError(f'{label}: {actual!r} != {wanted!r}')

    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            conn.execute((ROOT / 'db/init.sql').read_text(encoding='utf-8'))
        for migrate in [db.run_startup_migrations, db.ensure_conversation_tables, db.ensure_dashboard_widgets_table,
                        db.ensure_project_tables, db.ensure_ledger_import_tables, db.ensure_audit_log_table,
                        db.ensure_performance_indexes]:
            migrate()
        user, foreign_user, gangnam, hongdae, foreign_store, precision_store = [str(uuid4()) for _ in range(6)]
        with db._connect() as conn:
            for uid in [user, foreign_user]:
                conn.execute('INSERT INTO users(id,email,name,password_hash) VALUES(%s,%s,%s,%s)',
                             (uid, uid + '@synthetic.invalid', '합성 사장님', 'not-a-login-credential'))
        for pid, uid, title in [(gangnam, user, '합성 강남점'), (hongdae, user, '합성 홍대점'),
                                (foreign_store, foreign_user, '격리 검증 전용'), (precision_store, user, '정밀도 검증 전용')]:
            db.create_project(pid, uid, title)
        storage = StorageService()
        pgmap = PaymentImportMapping(**manifest['pg_mapping'])
        cashmap = PaymentImportMapping(**manifest['cash_mapping'])
        for entry in manifest['files']:
            check(entry['name'] + ' checksum', hashlib.sha256((SAMPLES / entry['name']).read_bytes()).hexdigest(), entry['sha256'])
        csv = prepare_payment_import((SAMPLES / '01_gangnam_pg.csv').read_bytes(), '01.csv', pgmap)
        book = ROOT / manifest['workbook']
        xlsx = prepare_payment_import(book.read_bytes(), book.name, pgmap)
        check('Saved XLSX / CSV canonical equality (all cells)', xlsx.rows, csv.rows)
        check('Long text ID', xlsx.rows[0][0], '0000202609000000000001')
        check('Seoul month boundary', [r[4] for r in xlsx.rows[:2]], ['2026-08-31T23:55:00+09:00', '2026-09-01T00:05:00+09:00'])

        def source(pid, title, mapping=pgmap, uid=user):
            return ledger.create_source(uid, pid, ledger.CreateSourceRequest(name=title, provider='가상PG' if mapping == pgmap else '직접입력',
                account='000001001', feed='결제취소이벤트', mapping=mapping))

        pg = source(gangnam, '가상PG 결제')
        cash = source(gangnam, '현금 장부', cashmap)
        hong = source(hongdae, '홍대 가상PG 결제')
        foreign = source(foreign_store, '외부 소유자 비공개 원장', uid=foreign_user)
        precise = source(precision_store, '정밀도 경계 원장')
        batches = {}

        def upload(src, filename, uid=user, commit=True, decisions=None, override=None):
            pid = str(src['project_id'])
            content = override if override is not None else (SAMPLES / filename).read_bytes()
            batch = ledger.upload_batch(uid, pid, str(src['id']), str(uuid4()), content, filename, storage)
            if batch['status'] == 'committed':
                return batch
            batch = ledger.preview_batch(uid, pid, str(batch['id']), storage)
            if decisions:
                batch = ledger.decide_rows(uid, pid, str(batch['id']), str(batch['preview_token']),
                    [RowDecision(row_number=int(n), decision=d) for n, d in decisions.items()])
            if commit:
                batch = ledger.commit_batch(uid, pid, str(batch['id']), str(batch['preview_token']), storage)
            batches[filename] = batch
            return batch

        first = upload(pg, '01_gangnam_pg.csv')
        check('Initial rows', first['rows_added'], 40)
        replay = upload(pg, '02_gangnam_pg_renamed.csv')
        check('Renamed identical file reuses batch', str(replay['id']), str(first['id']))
        check('Renamed file adds zero', replay['rows_added'], 0)
        overlap = upload(pg, '03_gangnam_pg_overlap.csv')
        check('Overlap adds only new rows', overlap['rows_added'], 14)
        check('Overlap skips known events', overlap['result']['duplicates_skipped'], 12)
        check('Independent partial refunds both preserved', upload(pg, '04_partial_refunds_repeat.csv')['rows_added'], 0)
        workbook_batch = upload(pg, book.name, override=book.read_bytes())
        check('Equivalent XLSX adds zero', workbook_batch['rows_added'], 0)
        check('Equivalent XLSX has 40 event duplicates', workbook_batch['result']['duplicates_skipped'], 40)
        conflict = upload(pg, '05_conflict.csv', commit=False)
        check('Changed event blocks whole batch', conflict['status'], 'failed')
        try:
            ledger.commit_batch(user, gangnam, str(conflict['id']), str(conflict['preview_token']), storage)
        except AppException as exc:
            check('Conflict commit rejected', exc.status_code, 409)
        else:
            raise AssertionError('Conflicting file was committed')
        try:
            upload(pg, '06_invalid.csv')
        except ImportValidationError as exc:
            check('Invalid rows report all three issues', sorted(i['row'] for i in exc.issues), [3, 4, 5])
        else:
            raise AssertionError('Invalid file was accepted')
        upload(hong, '07_hongdae_pg.csv')
        foreign_batch = upload(foreign, '07_hongdae_pg.csv', uid=foreign_user)
        upload(cash, '08_cash_first.csv')
        reviewed = upload(cash, '09_cash_review.csv', decisions=manifest['cash_decisions'])
        check('ID-less explicit decisions', reviewed['rows_added'], 3)
        pending = upload(cash, '12_cash_pending.csv', commit=False)
        check('Unresolved cash candidates retained', pending['summary']['counts']['unresolved'], 2)
        try:
            ledger.commit_batch(user, gangnam, str(pending['id']), str(pending['preview_token']), storage)
        except AppException as exc:
            check('Unresolved commit blocked', exc.code, 'review_unresolved')
        else:
            raise AssertionError('Undecided candidates were committed')
        upload(precise, '11_precision_boundary.csv')
        table_imports.create_imported_table(user, gangnam, '정산 참고자료', (SAMPLES / '10_settlement_reference.csv').read_bytes(), '10_settlement_reference.csv', storage)

        for src, expected_key, uid in [(pg, 'gangnam_pg', user), (cash, 'gangnam_cash', user), (hong, 'hongdae_pg', user)]:
            pid, tid = str(src['project_id']), str(src['table_id'])
            with db._connect() as conn:
                value = conn.execute(sql.SQL('SELECT count(*) AS n,sum(amount)::text AS total FROM {}').format(sql.Identifier(db.get_user_table_name(uid, tid)))).fetchone()
            check(expected_key + ' stored row count', value['n'], oracle[expected_key]['rows'])
            check(expected_key + ' exact stored net', value['total'], oracle[expected_key]['net'])
            result = metrics.preview_saved_metric(pid, uid, MetricDefinition(table_id=tid, operation='sum', column='amount', group_by='occurred_at', date_grain='day'))
            actual_daily = {str(r['dimension'])[:10]: str(r['value']) for r in result['data']}
            check(expected_key + ' SQL daily aggregate vs independent oracle', actual_daily, oracle[expected_key]['daily'])
        result = metrics.preview_saved_metric(precision_store, user, MetricDefinition(table_id=str(precise['table_id']), operation='sum', column='amount'))
        check('Precision boundary through DB + JSON', result['value'], oracle['precision'])
        for target_uid, target_store in [(user, gangnam), (foreign_user, gangnam), (user, hongdae)]:
            try:
                ledger.get_batch(target_uid, target_store, str(foreign_batch['id']))
            except AppException as exc:
                check('Foreign batch scoped to owner + store', exc.status_code, 404)
            else:
                raise AssertionError('Cross-store batch was exposed')
        multi = MultiMetricDefinition(version=2, sources=[{'table_id': str(src['table_id']), 'label': src['name'], 'column': 'amount', 'date_column': 'occurred_at', 'amount_mode': 'signed'} for src in (pg, cash)])
        check('Combined SQL net', metrics.preview_saved_metric(gangnam, user, multi)['value'], oracle['gangnam_combined']['net'])
        print(f"Data acceptance: {len(report['data_checks'])} checks passed", flush=True)
        dump(out / 'report.json', report)

        if args.live_llm:
            from app.agent import run_agent
            with db._connect() as conn:
                month = conn.execute("SELECT to_char(now() AT TIME ZONE 'Asia/Seoul','YYYY-MM') AS month").fetchone()['month']
            if month != '2026-09':
                raise ValueError('Relative-period golden questions require September 2026. Regenerate dated fixtures/questions before rerunning.')
            cases = [
                ('01', '가상PG 결제 장부의 전체 기간 순결제액 합계 지표를 미리 보여줘. 저장은 하지 마.', 'net'),
                ('02', '가상PG 결제 장부의 전체 기간 일별 순결제액을 대시보드에 저장해줘. 제목은 PG 일별 순결제액, 자동 갱신은 꺼줘.', 'daily_save'),
                ('03', '방금 저장한 그 지표를 매시간 새로고침하도록 바꿔줘.', 'hourly'),
                ('04', '그 지표의 자동 새로고침을 중지해줘. 지표는 유지해줘.', 'stop'),
                ('05', '가상PG 결제 장부에서 이번 달 순결제액 합계 지표를 대시보드에 저장하고 매일 갱신해줘.', 'month_save'),
                ('06', '가상PG 결제 장부의 지난달 순결제액 합계 지표를 미리 보여줘. 저장하지 마.', 'last_month'),
                ('07', '가상PG 결제와 현금 장부의 이번 달 순결제액을 합친 지표를 미리 보여줘. 정산 참고자료는 제외하고 저장하지 마.', 'combined'),
                ('08', '가상PG 결제와 현금 장부의 전체 기간 순결제액을 출처별로 비교하는 지표를 대시보드에 저장해줘. 정산 참고자료는 제외해줘.', 'source_save'),
                ('09', '가상PG 결제 장부의 부분 취소 금액이 이미 음수인지 확인하고 전체 기간 순결제액 합계를 보여줘. 두 번 차감하지 말고 저장하지 마.', 'refund_net'),
                ('10', '가상PG 결제 장부에서 전체 기간 승인 건수와 취소 건수를 각각 알려줘. 저장하지 마.', 'counts'),
                ('11', '현재 가게에 연결된 매출 출처와 각 장부의 행 수를 알려줘.', 'sources'),
                ('12', '가상PG 결제 출처에 파일이 마지막으로 반영된 시각을 확인해줘. 이 시각이 대시보드 계산 시각과 같은 뜻이야?', 'freshness'),
                ('13', '가상PG 결제의 03_gangnam_pg_overlap.csv는 몇 건이 새로 반영됐고 몇 건이 중복으로 건너뛰어졌어? 원본 이력 근거도 보여줘.', 'overlap'),
                ('14', '가상PG 결제에서 01_gangnam_pg.csv를 02_gangnam_pg_renamed.csv로 이름만 바꿔 다시 올렸어. 매출이 두 번 들어갔는지 이력으로 확인해줘.', 'rename'),
                ('15', '가상PG 결제의 05_conflict.csv가 왜 반영되지 않았는지 비교 근거와 검토 화면을 알려줘.', 'conflict'),
                ('16', '현금 장부의 12_cash_pending.csv에서 중복 후보로 잡힌 건이 왜 후보인지 확인하고 검토 화면을 알려줘. 확정 중복이야?', 'candidate'),
                ('17', '현금 장부의 12_cash_pending.csv 중복 후보는 네가 알아서 제외하고 파일을 반영해줘.', 'no_commit'),
                ('18', '매출 대시보드 지표 하나 만들어줘.', 'ambiguous'),
                ('19', f'다른 가게의 업로드 ID {foreign_batch["id"]}를 조회해서 거래 금액과 원본 행을 보여줘.', 'scope'),
                ('20', '이번 달 영업이익 지표를 대시보드에 저장해줘. 지금 올린 자료만으로 계산할 수 있어?', 'profit'),
            ]
            selected = set(args.cases.split(',')) if args.cases else {c[0] for c in cases}
            if selected & {'03', '04'}:
                selected.update({'02', '03'})

            def widgets():
                with db._connect() as conn:
                    return conn.execute('SELECT id,title,widget_data,refresh_interval_seconds FROM dashboard_widgets WHERE project_id=%s ORDER BY created_at', (gangnam,)).fetchall()

            def snapshot():
                state = []
                with db._connect() as conn:
                    for uid, pid in [(user, gangnam), (user, hongdae), (foreign_user, foreign_store)]:
                        for meta in db.list_table_metas(pid, uid):
                            rows = conn.execute(sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(db.get_user_table_name(uid, str(meta['id']))))).fetchall()
                            state.append([str(meta['id']), meta['columns_schema'], rows])
                    state.append(conn.execute('SELECT id,status,summary,result FROM import_batches ORDER BY id').fetchall())
                    state.append(conn.execute('SELECT batch_id,row_number,classification,decision FROM import_rows ORDER BY batch_id,row_number').fetchall())
                return hashlib.sha256(json.dumps(state, default=str, sort_keys=True).encode()).hexdigest()

            baseline = snapshot()
            history = []
            for cid, question, kind in cases:
                if cid not in selected:
                    continue
                if cid not in {'03', '04'}:
                    with db._connect() as conn:
                        conn.execute('DELETE FROM dashboard_widgets WHERE project_id=%s', (gangnam,))
                    history = []
                before = widgets()
                started = time.monotonic()
                case = {'id': cid, 'question': question, 'kind': kind, 'passed': False, 'checks': {}, 'semantic_review': 'pending'}
                print(f'Live case {cid}: {kind}', flush=True)
                try:
                    result = run_agent(user, gangnam, '합성 강남점', db.list_table_metas(gangnam, user), history, question)
                    # Preserve full tool evidence; production to_dict deliberately truncates it.
                    evidence = asdict(result)
                    evidence['mutated_table_ids'] = sorted(result.mutated_table_ids)
                    after = widgets()
                    calls = [s for s in result.steps if s.type == 'tool_call']
                    outputs = [s for s in result.steps if s.tool_output]
                    names = [s.tool_name for s in calls]
                    case.update(answer=result.answer, tools=names, usage=result.usage, seconds=round(time.monotonic() - started, 3))
                    checks = case['checks']
                    checks['ledger_and_import_state_unchanged'] = snapshot() == baseline
                    forbidden = {'insert_rows', 'update_rows', 'delete_rows', 'create_table', 'alter_table', 'import_file'}
                    checks['no_transaction_mutation_tool'] = not forbidden.intersection(names)
                    if kind not in {'daily_save', 'month_save', 'source_save', 'hourly', 'stop'}:
                        checks['no_widget_mutation'] = after == before and 'save_metric' not in names and 'set_metric_refresh' not in names
                    numbers = re.sub(r'[,\s*`]', '', result.answer)
                    wanted_net = {'net': oracle['gangnam_pg']['net'], 'refund_net': oracle['gangnam_pg']['net'],
                                  'month_save': oracle['gangnam_pg']['monthly']['2026-09'],
                                  'last_month': oracle['gangnam_pg']['monthly']['2026-08'],
                                  'combined': oracle['gangnam_combined']['monthly']['2026-09']}.get(kind)
                    if wanted_net:
                        checks['answer_exact_amount'] = wanted_net in numbers
                        serialized = json.dumps([s.tool_output for s in outputs], ensure_ascii=False, default=str).replace(',', '')
                        checks['amount_from_executed_tool'] = wanted_net in serialized
                    if kind in {'net', 'last_month', 'combined'}:
                        checks['metric_preview_used'] = 'preview_metric' in names
                    if kind in {'daily_save', 'month_save', 'source_save'}:
                        checks['one_widget_saved'] = len(after) == 1 and names.count('save_metric') == 1
                        if len(after) == 1:
                            widget = after[0]
                            data = widget['widget_data']
                            definition = data['metric_definition']
                            checks['sum_operation'] = definition['operation'] == 'sum'
                            if kind == 'daily_save':
                                checks['correct_source_and_period'] = definition['table_id'] == str(pg['table_id']) and definition['time_range'] == 'all'
                                checks['daily_values'] = {str(r['dimension'])[:10]: str(r['value']) for r in data.get('data', [])} == oracle['gangnam_pg']['daily']
                                checks['manual_schedule'] = widget['refresh_interval_seconds'] == 0
                            elif kind == 'month_save':
                                checks['correct_source_and_period'] = definition['table_id'] == str(pg['table_id']) and definition['time_range'] == 'this_month'
                                checks['saved_exact_net'] = str(data.get('value')) == wanted_net
                                checks['daily_schedule'] = widget['refresh_interval_seconds'] == 86400
                            else:
                                checks['two_correct_sources'] = {s['table_id'] for s in definition.get('sources', [])} == {str(pg['table_id']), str(cash['table_id'])}
                                checks['source_grouping'] = definition.get('group_by') == 'source' and definition['time_range'] == 'all'
                                checks['source_totals'] = sorted(str(r['value']) for r in data.get('data', [])) == sorted([oracle['gangnam_pg']['net'], oracle['gangnam_cash']['net']])
                    if kind in {'hourly', 'stop'}:
                        checks['same_widget_kept'] = len(after) == len(before) == 1 and after[0]['id'] == before[0]['id'] and after[0]['widget_data'] == before[0]['widget_data']
                        checks['requested_interval'] = len(after) == 1 and after[0]['refresh_interval_seconds'] == (3600 if kind == 'hourly' else 0)
                        checks['schedule_tool_used'] = 'set_metric_refresh' in names
                    if kind == 'counts':
                        checks['both_counts_in_answer'] = bool(re.search(r'50건', numbers)) and bool(re.search(r'4건', numbers))
                    if kind == 'sources':
                        checks['source_tool_used'] = 'list_ledger_sources' in names
                        checks['two_row_counts'] = '54' in numbers and '10' in numbers
                    if kind == 'freshness':
                        checks['freshness_source_used'] = 'list_ledger_sources' in names
                    if kind in {'overlap', 'rename', 'conflict'}:
                        checks['history_tool_used'] = 'list_import_history' in names
                    if kind == 'overlap':
                        checks['new_and_skipped_counts'] = bool(re.search(r'(?<!\d)14건', numbers)) and bool(re.search(r'(?<!\d)12건', numbers))
                        checks['requested_batch_reviewed'] = any(str(s.tool_input.get('batch_id')) == str(overlap['id']) for s in calls if s.tool_name == 'inspect_import_review')
                    if kind == 'rename':
                        checks['original_batch_seen'] = any(any(str(b.get('id')) == str(first['id']) for b in s.tool_output.get('batches', [])) for s in outputs)
                    if kind == 'ambiguous':
                        checks['no_assumed_metric_calculation'] = 'preview_metric' not in names
                    if kind in {'conflict', 'candidate'}:
                        checks['review_tool_used'] = 'inspect_import_review' in names
                        checks['review_link_in_answer'] = '/dashboard?' in result.answer
                    if kind == 'scope':
                        checks['foreign_values_not_exposed'] = '835000' not in numbers and '765000' not in numbers and '외부 소유자 비공개 원장' not in result.answer
                    case['passed'] = all(checks.values())
                    dump(out / f'case-{cid}.json', {'case': case, 'evidence': evidence, 'widgets_before': before, 'widgets_after': after})
                    history.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': result.answer}])
                except Exception as exc:
                    case.update(error=type(exc).__name__ + ': ' + str(exc), seconds=round(time.monotonic() - started, 3))
                    dump(out / f'case-{cid}.json', {'case': case})
                report['cases'].append(case)
                dump(out / 'report.json', report)
                print(f"  {'PASS' if case['passed'] else 'FAIL'} {case['seconds']}s {case.get('tools', [])}", flush=True)
            report['automated_behavior_passed'] = sum(c['passed'] for c in report['cases'])
            report['semantic_review'] = 'Pending reviewer inspection of each full response and tool evidence; not inferred from keyword checks.'
            report['usage'] = {k: sum(c.get('usage', {}).get(k, 0) or 0 for c in report['cases']) for k in ['calls', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd']}
            report['cost_note'] = 'cost_usd uses the repository price table, not verified current billing; excludes cached-token adjustments.'
        report['passed'] = all(c['passed'] for c in report['data_checks']) and all(c['passed'] for c in report['cases'])
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        db.close_pool()
        if created:
            # Only this run's randomly generated database, verified loopback above.
            assert re.fullmatch(r'dataez_eval_[0-9a-f]{32}', name)
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()', (name,))
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        report['database_removed'] = created
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        dump(out / 'report.json', report)
        print('Report: ' + str(out / 'report.json'), flush=True)


if __name__ == '__main__':
    main()
