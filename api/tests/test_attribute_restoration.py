"""H restoration against real PostgreSQL; no mocked transactions or parsers."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from uuid import uuid4, UUID

import psycopg
import pytest
from pydantic import ValidationError
from psycopg import sql

from app import attribute_restoration as restore, db, ledger_imports as ledger, dashboard_metrics as metrics
from app.exceptions import AppException
from app.payment_imports import prepare_payment_import, PaymentImportMapping
from app.ledger_routes import RowDecision
from .test_import_postgres import live, DSN
from .test_ledger_imports_postgres import env as base_env, source, upload, preview, commit, state
from .test_event_review_postgres import legacy, adopt

pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for H verification")
HEAD = 'id,money,day,method,channel,fee\n'
BODY = '001,100,2026-09-01,카드,예약웹,3\n002,-20,2026-09-02,카드,예약웹,-0.6\n003,50,2026-09-03,현금,매장,\n'
ADDITIONS = {'payment_method_column': 'method', 'channel_column': 'channel', 'fee_column': 'fee'}


@pytest.fixture
def env(base_env, monkeypatch):
    monkeypatch.setattr(restore, '_connect', base_env[0])
    return base_env


def setup(env, body=BODY):
    src = source(env)
    batch = commit(env, preview(env, upload(env, src, (HEAD + body).encode())))
    return src, batch


def plan(env, src, additions=ADDITIONS):
    return restore.preview_restoration(env[2], str(src['project_id']), str(src['id']), restore.RestoreAttributesRequest(**additions), env[1])


def apply(env, src, checked):
    return restore.apply_restoration(env[2], str(src['project_id']), str(src['id']), checked['id'], env[1])


def physical(env, src):
    with env[0]() as conn:
        return conn.execute(sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(db.get_user_table_name(env[2], str(src['table_id']))))).fetchall()


def test_restores_exact_origins_keeps_money_widgets_and_historical_decisions(env):
    src, batch = setup(env)
    saved = metrics.create_saved_metric(env[3], env[2], metrics.CreateMetricRequest(title='기존 순결제액', definition=metrics.MetricDefinition(table_id=src['table_id'], column='amount'), refresh_interval_seconds=3600))
    before = physical(env, src)
    historical = ledger.list_rows(env[2], env[3], batch['id'])['rows']
    checked = plan(env, src)
    assert checked['status'] == 'ready'
    assert checked['report']['attributes']['fee'] == {'column': 'fee', 'provided': 2, 'missing': 1}
    assert physical(env, src) == before  # preview only
    result = apply(env, src, checked)
    assert result['result']['rows_verified'] == 3 and result['result']['rule_version'] == 2
    after = physical(env, src)
    assert [{k: r[k] for k in before[0]} for r in after] == before
    assert after[1]['fee'] == Decimal('-0.6') and after[2]['fee'] is None
    assert after[0]['payment_method'] == '카드' and after[0]['channel'] == '예약웹'
    assert ledger.list_rows(env[2], env[3], batch['id'])['rows'] == historical
    refreshed = metrics.refresh_metric(UUID(env[3]), UUID(str(saved['id'])), {'id': env[2]})
    assert refreshed['widget_data']['value'] == '130'
    changes = restore.list_changes(env[2], env[3], src['id'], checked['id'])
    assert changes['total'] == 3 and changes['changes'][0]['origin_batch_id'] == str(batch['id'])
    assert changes['changes'][0]['origin_row_number'] == 2
    assert changes['changes'][0]['origin_filename'] == 'payments.csv'
    assert 'fee' not in changes['changes'][0]['before_normalized']
    assert changes['changes'][0]['after_normalized']['fee'] == '3'


def test_retry_concurrent_apply_and_original_commit_retry_remain_idempotent(env):
    src, _ = setup(env)
    key = str(uuid4())
    batch = upload(env, src, (HEAD + BODY).encode(), request_key=key)
    checked = plan(env, src)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(env, src, checked), range(2)))
    assert sorted(r['replayed'] for r in results) == [False, True]
    assert apply(env, src, checked)['replayed']
    retry = upload(env, src, (HEAD + BODY).encode(), request_key=key)
    assert retry['id'] == batch['id'] and retry['replayed']
    with pytest.raises(AppException) as exc:
        upload(env, src, (HEAD + BODY + '004,5,2026-09-04,카드,매장,0\n').encode(), request_key=key)
    assert exc.value.code == 'idempotency_mismatch'
    with env[0]() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_attribute_restorations WHERE status='applied'").fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM source_attribute_changes').fetchone()['n'] == 3


def test_upgrade_invalidates_pending_and_new_overlap_keeps_dedup(env):
    src, _ = setup(env)
    pending = preview(env, upload(env, src, (HEAD + '004,20,2026-09-04,카드,매장,0.6\n').encode()))
    checked = plan(env, src)
    assert apply(env, src, checked)['result']['invalidated_uploads'] == 1
    assert ledger.get_batch(env[2], env[3], pending['id'])['requires_reupload']
    with pytest.raises(AppException) as exc:
        preview(env, pending)
    assert exc.value.code == 'mapping_changed'
    with pytest.raises(AppException):
        commit(env, pending)
    duplicate = commit(env, preview(env, upload(env, src, (HEAD + BODY).encode())))
    assert duplicate['rows_added'] == 0 and duplicate['result']['duplicates_skipped'] == 3
    new = commit(env, preview(env, upload(env, src, (HEAD + BODY + '004,20,2026-09-04,카드,매장,0.6\n').encode())))
    assert new['rows_added'] == 1
    conflict = preview(env, upload(env, src, (HEAD + '001,100,2026-09-01,현금,예약웹,3\n').encode()))
    assert conflict['status'] == 'failed'


@pytest.mark.parametrize('cause', ['missing_file', 'changed_file', 'missing_column', 'invalid_fee', 'missing_origin', 'physical_change', 'registry_key'])
def test_unprovable_restoration_blocks_all_rows(env, cause):
    body = BODY.replace(',3\n', ',bad\n') if cause == 'invalid_fee' else BODY
    src, batch = setup(env, body)
    key = env[1].staged_key(str(batch['id']))
    if cause == 'missing_file':
        env[1].delete_staged(key)
    if cause == 'changed_file':
        env[1].write_staged(key, (HEAD + BODY + '\n').encode())
    if cause == 'missing_origin':
        with env[0]() as conn:
            conn.execute('UPDATE source_events SET first_batch_id=NULL WHERE source_id=%s', (src['id'],))
    if cause == 'physical_change':
        with env[0]() as conn:
            conn.execute(sql.SQL('UPDATE {} SET amount=999 WHERE _row_id=1').format(sql.Identifier(db.get_user_table_name(env[2], str(src['table_id'])))))
    if cause == 'registry_key':
        with env[0]() as conn:
            conn.execute('UPDATE source_events SET event_key_hash=%s WHERE source_id=%s AND target_row_id=1', ('0'*64, src['id']))
    before = physical(env, src)
    checked = plan(env, src, {'fee_column': 'absent'} if cause == 'missing_column' else ADDITIONS)
    assert checked['status'] == 'blocked' and checked['report']['issue_count']
    with pytest.raises(AppException):
        apply(env, src, checked)
    assert physical(env, src) == before


@pytest.mark.parametrize('cause', ['new_upload', 'committed_rows', 'file_change', 'expired', 'schema_change'])
def test_stale_or_changed_proof_cannot_be_applied(env, cause):
    src, first = setup(env)
    checked = plan(env, src)
    if cause in {'new_upload', 'committed_rows'}:
        batch = upload(env, src, (HEAD + '004,1,2026-09-04,현금,매장,0\n').encode())
        if cause == 'committed_rows':
            commit(env, preview(env, batch))
    elif cause == 'file_change':
        env[1].write_staged(env[1].staged_key(str(first['id'])), (HEAD + BODY.replace(',3\n', ',4\n')).encode())
    elif cause == 'expired':
        with env[0]() as conn:
            conn.execute("UPDATE source_attribute_restorations SET expires_at=now()-interval '1 second'")
    else:
        with env[0]() as conn:
            conn.execute("UPDATE table_meta SET columns_schema=columns_schema || '[{\"name\":\"changed\",\"type\":\"TEXT\"}]'::jsonb")
    with pytest.raises(AppException):
        apply(env, src, checked)
    assert 'fee' not in physical(env, src)[0]


def test_failure_after_ddl_and_registry_update_rolls_back_everything(env):
    src, _ = setup(env)
    checked = plan(env, src)
    with env[0]() as conn:
        conn.execute("ALTER TABLE source_attribute_restorations ADD CHECK (status<>'applied')")
    with pytest.raises(psycopg.errors.CheckViolation):
        apply(env, src, checked)
    assert 'fee' not in physical(env, src)[0]
    with env[0]() as conn:
        assert conn.execute('SELECT rule_version FROM ledger_sources').fetchone()['rule_version'] == 1
        assert conn.execute('SELECT count(*) AS n FROM source_attribute_changes').fetchone()['n'] == 0
        assert all('fee' not in r['normalized'] for r in conn.execute('SELECT normalized FROM source_events').fetchall())
        assert conn.execute('SELECT columns_schema FROM table_meta').fetchone()['columns_schema'][-1]['name'] == 'currency'


def test_idless_accepted_rows_use_provenance_not_similar_event_or_excluded_row(env):
    src = source(env, mapping={'amount_column': 'money', 'occurred_at_column': 'day'})
    first = commit(env, preview(env, upload(env, src, (HEAD + 'a,100,2026-09-01,현금,매장,1\n').encode())))
    batch = preview(env, upload(env, src, (HEAD + 'b,100,2026-09-01,카드,예약웹,bad\nc,100,2026-09-01,간편결제,예약웹,2\n').encode()))
    batch = ledger.decide_rows(env[2], env[3], batch['id'], batch['preview_token'], [RowDecision(row_number=2, decision='exclude'), RowDecision(row_number=3, decision='include')])
    commit(env, batch)
    checked = plan(env, src)
    assert checked['status'] == 'ready'
    apply(env, src, checked)
    assert [(r['payment_method'], r['fee']) for r in physical(env, src)] == [('현금', Decimal(1)), ('간편결제', Decimal(2))]


def test_original_storage_enables_preserved_columns_without_rewriting_rows(env):
    src = adopt(env, legacy(env, (HEAD + BODY).encode()))
    extra = commit(env, preview(env, upload(env, src, (HEAD + '004,10,2026-09-04,카드,매장,0.3\n').encode())))
    env[1].delete_staged(env[1].staged_key(str(extra['id'])))
    before = physical(env, src)
    checked = plan(env, src)
    assert checked['status'] == 'ready' and checked['report']['origin'] == 'original' and checked['report']['file_count'] == 0
    apply(env, src, checked)
    assert physical(env, src) == before
    audit = restore.list_changes(env[2], env[3], src['id'], checked['id'])['changes']
    assert audit[-1]['origin_batch_id'] is None and audit[-1]['origin_row_number'] == 4
    duplicate = commit(env, preview(env, upload(env, src, (HEAD + BODY).encode())))
    assert duplicate['rows_added'] == 0


def test_second_attribute_upgrade_retains_first_and_exact_large_fee(env):
    src, _ = setup(env, BODY.replace(',3\n', ',9007199254740993.01\n'))
    apply(env, src, plan(env, src, {'fee_column': 'fee'}))
    apply(env, src, plan(env, src, {'channel_column': 'channel', 'payment_method_column': 'method'}))
    assert physical(env, src)[0]['fee'] == Decimal('9007199254740993.01')
    assert physical(env, src)[0]['channel'] == '예약웹'
    with pytest.raises(AppException):
        plan(env, src, {'fee_column': 'fee'})


def test_preview_and_history_scoped_to_store_and_owner(env):
    src, _ = setup(env)
    checked = plan(env, src)
    for user, store in [(str(uuid4()), env[3]), (env[2], env[4])]:
        for action in [lambda: restore.preview_restoration(user, store, src['id'], restore.RestoreAttributesRequest(**ADDITIONS), env[1]),
                       lambda: restore.apply_restoration(user, store, src['id'], checked['id'], env[1]),
                       lambda: restore.list_restorations(user, store, src['id']),
                       lambda: restore.list_changes(user, store, src['id'], checked['id'])]:
            with pytest.raises(AppException) as exc:
                action()
            assert exc.value.status_code == 404


@pytest.mark.parametrize('action', ['preview', 'apply'])
def test_file_read_releases_source_lock_and_rechecks_snapshot(env, monkeypatch, action):
    src, _ = setup(env)
    checked = plan(env, src) if action == 'apply' else None
    read = env[1].read_staged
    def change_during_read(key):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(upload, env, src, (HEAD + '004,1,2026-09-04,현금,매장,0\n').encode())
            future.result(timeout=5)
        return read(key)
    monkeypatch.setattr(env[1], 'read_staged', change_during_read)
    with pytest.raises(AppException) as exc:
        apply(env, src, checked) if action == 'apply' else plan(env, src)
    assert exc.value.code == 'stale_restoration'


def test_empty_source_upgrade_and_request_validation(env):
    src = source(env)
    checked = plan(env, src)
    assert apply(env, src, checked)['result']['rows_verified'] == 0
    assert commit(env, preview(env, upload(env, src, (HEAD + BODY).encode())))['rows_added'] == 3
    for payload in [{}, {'amount_column': 'other'}, {'fee_column': '   '}]:
        with pytest.raises(ValidationError):
            restore.RestoreAttributesRequest(**payload)
