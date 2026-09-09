"""L: real transactional cash entry, duplicate review, scope, outbox, and tools."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from psycopg import sql

from app import cash_entries as cash, db, ledger_imports, index_jobs, rag_catalog, dashboard_metrics as metrics
from app.exceptions import AppException
from app.ledger_guards import assert_unmanaged_table
from app.storage import StorageService
from tests.test_rag_postgres import vector_db, DSN

pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_RAG_TEST_DATABASE_URL')


def draft(env, **kw):
    return cash.draft(env[1],env[2],cash.CashDraftRequest(request_key=kw.pop('request_key',uuid4()),amount=kw.pop('amount','30000'),occurred_on='2026-09-08',**kw))


def commit(env, row, **kw):
    return cash.commit(env[1],env[2],str(row['id']),cash.CashCommitRequest(confirmation_token=row['confirmation_token'],**kw))


def records(env):
    with env[0]() as conn:
        source=conn.execute("SELECT * FROM ledger_sources WHERE project_id=%s AND input_mode='cash'",(env[2],)).fetchone()
        if not source: return None, []
        rows=conn.execute(sql.SQL('SELECT * FROM {} ORDER BY _row_id').format(sql.Identifier(source['physical_table_name']))).fetchall()
        return source,rows


@pytest.mark.parametrize('amount',['0','-1','1.001','NaN','Infinity','30,000','1e21','1e-3'])
def test_bad_amounts_rejected(amount):
    with pytest.raises(ValidationError): cash.CashDraftRequest(request_key=uuid4(),amount=amount)


def test_draft_retry_conflict_and_no_ledger_write(vector_db):
    env=vector_db; key=uuid4()
    a=draft(env,request_key=key,memo='점심'); b=draft(env,request_key=key,memo='점심')
    assert a['id']==b['id'] and a['confirmation_token']==b['confirmation_token']
    assert a['payload']['amount']=='30000' and a['status']=='draft' and records(env)==(None,[])
    with pytest.raises(AppException) as exc: draft(env,request_key=key,amount='40000')
    assert exc.value.status_code==409
    assert cash.list_entries(env[1],env[2])['total']==1


def test_commit_exact_value_provenance_metadata_and_index(vector_db):
    env=vector_db
    row=draft(env,amount='9007199254740993.01',channel='매장',memo='직접 기록')
    result=commit(env,row)
    assert result['status']=='committed' and commit(env,row)['replayed']
    source,rows=records(env)
    assert len(rows)==1 and rows[0]['amount']==Decimal('9007199254740993.01')
    assert rows[0]['payment_method']=='현금' and rows[0]['channel']=='매장'
    assert rows[0]['occurred_at'].isoformat().startswith('2026-09-07T15:00:00')
    assert 'fee' not in rows[0] and source['data_revision']==1
    with env[0]() as conn:
        event=conn.execute('SELECT * FROM source_events WHERE source_id=%s',(source['id'],)).fetchone()
        assert event['first_batch_id'] is None and event['target_row_id']==result['target_row_id']
        assert conn.execute('SELECT row_count FROM table_meta WHERE id=%s',(source['table_id'],)).fetchone()['row_count']==1
        assert conn.execute('SELECT count(*) n FROM import_batches').fetchone()['n']==0
        snap=rag_catalog.schema_snapshot(conn.cursor(),env[1],env[2],str(source['table_id']))
        assert any('실제 거래 시각이 아니다' in line for line in rag_catalog.catalog_lines(snap))
    state=index_jobs.list_jobs(env[1],env[2])
    assert state['total']==1 and state['counts']['pending']==1
    assert ledger_imports.list_sources(env[1],env[2])[0]['last_committed_at']


def test_concurrent_same_confirmation_writes_once(vector_db):
    env=vector_db; row=draft(env)
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(lambda _:commit(env,row),range(3)))
    assert sum(r['replayed'] for r in results)==2
    assert len(records(env)[1])==1


def test_concurrent_similar_requires_explicit_separate_transaction(vector_db):
    env=vector_db; a=draft(env,memo='첫 거래'); b=draft(env,memo='둘째 거래')
    def write(row):
        try: return commit(env,row)
        except AppException as exc: return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(write,[a,b]))
    assert 'cash_similar_exists' in results and len(records(env)[1])==1
    pending=next(row for row in [a,b] if cash.get_entry(env[1],env[2],str(row['id']))['status']=='draft')
    current=cash.get_entry(env[1],env[2],str(pending['id']))
    assert current['similar']['count']==1
    assert commit(env,pending,separate_transaction=True)['status']=='committed'
    assert len(records(env)[1])==2


def test_refund_records_signed_amount_and_scoped_original(vector_db):
    env=vector_db; approved=commit(env,draft(env))
    refund=commit(env,draft(env,kind='refund',amount='5000',original_event_id=approved['event_id']))
    assert refund['signed_amount']=='-5000'
    assert records(env)[1][1]['amount']==Decimal('-5000')
    with pytest.raises(AppException) as exc: commit(env,draft(env,kind='refund',amount='100',original_event_id='foreign'))
    assert exc.value.code=='cash_original_missing' and len(records(env)[1])==2


@pytest.mark.parametrize('mode',['cancelled','expired','wrong_token'])
def test_inactive_or_wrong_confirmation_creates_no_source(vector_db,mode):
    env=vector_db; row=draft(env)
    if mode=='cancelled': cash.cancel(env[1],env[2],str(row['id']))
    elif mode=='expired':
        with env[0]() as conn: conn.execute("UPDATE cash_entries SET expires_at=now()-interval '1 second' WHERE id=%s",(row['id'],))
    else: row['confirmation_token']=uuid4()
    with pytest.raises(AppException): commit(env,row)
    assert records(env)==(None,[])


def test_store_owner_isolation_and_managed_write_guards(vector_db):
    env=vector_db; row=draft(env)
    for uid,pid in [(env[1],env[3]),(env[4],env[5])]:
        assert cash.list_entries(uid,pid)['total']==0
        with pytest.raises(AppException): cash.get_entry(uid,pid,str(row['id']))
        with pytest.raises(AppException): cash.commit(uid,pid,str(row['id']),cash.CashCommitRequest(confirmation_token=row['confirmation_token']))
    commit(env,row); source,_=records(env)
    with env[0]() as conn:
        with pytest.raises(AppException): assert_unmanaged_table(conn.cursor(),source['physical_table_name'])
    with pytest.raises(AppException): ledger_imports.upload_batch(env[1],env[2],str(source['id']),str(uuid4()),b'amount\n1\n','x.csv',StorageService())
    with pytest.raises(AppException): ledger_imports.baseline_source(env[1],env[2],str(source['id']))
    from app.attribute_restoration import _snapshot
    with env[0]() as conn:
        with pytest.raises(AppException): _snapshot(conn.cursor(),source)
    with pytest.raises(AppException): cash.cancel(env[1],env[2],str(row['id']))


def test_failed_registry_write_rolls_back_ledger_metadata_and_draft(vector_db):
    env=vector_db; commit(env,draft(env)); before=records(env)
    row=draft(env,amount='40000')
    with env[0]() as conn:
        conn.execute("ALTER TABLE source_events ADD CHECK(normalized->>'amount'<>'40000')")
    import psycopg
    with pytest.raises(psycopg.Error): commit(env,row)
    assert records(env)==before and cash.get_entry(env[1],env[2],str(row['id']))['status']=='draft'


def test_cash_metrics_recalculate_after_new_entry_and_tools_only_draft(vector_db,monkeypatch):
    env=vector_db; commit(env,draft(env)); source,_=records(env)
    db.ensure_dashboard_widgets_table(); db.ensure_project_tables()
    monkeypatch.setattr(metrics,'_connect',env[0])
    from app.metric_definitions import MetricDefinition
    saved=metrics.create_saved_metric(env[2],env[1],metrics.CreateMetricRequest(title='현금 순결제',definition=MetricDefinition(table_id=source['table_id'],column='amount')))
    from app.agent_tools import ToolExecutor,TOOL_SPECS
    assert not any('commit_cash' in tool['function']['name'] for tool in TOOL_SPECS)
    executor=ToolExecutor(env[1],env[2])
    args=json.dumps({'amount':'5000','kind':'refund','occurred_on':'2026-09-08','memo':'잔액 반환'})
    a=executor.execute('draft_cash_entry',args); b=executor.execute('draft_cash_entry',args)
    assert a['id']==b['id'] and a['status']=='draft' and 'confirmation_token' not in a
    assert len(records(env)[1])==1
    commit(env,cash.get_entry(env[1],env[2],str(a['id'])))
    result=metrics.refresh_metric(env[2],saved['id'],{'id':env[1]})
    assert Decimal(result['widget_data']['value'])==Decimal('25000')
