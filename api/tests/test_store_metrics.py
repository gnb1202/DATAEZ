"""M: actual SQL, ownership boundaries, explicit selection and saved lifecycle."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from threading import Event
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg import sql
from app import db, table_imports, dashboard_metrics as metrics, metric_revisions as revisions, store_metric_tools
from app.metric_definitions import MultiStoreMetricDefinition, parse_metric_definition, MetricDefinition
from app.storage import StorageService
from tests.test_formula_revisions import env, create, edit, preview
from tests.test_rag_postgres import vector_db, DSN

pytestmark=pytest.mark.skipif(not DSN,reason='Set DATAEZ_RAG_TEST_DATABASE_URL')


def source(env,pid,csv='amount,day\n100,2026-09-01\n-20,2026-09-02\n',uid=None,name='결제원장'):
    return table_imports.create_imported_table(uid or env[1],pid,name,csv.encode(),'store.csv',StorageService())


def mapping(table,**kw):
    return {'table_id':str(table['id']),'column':'amount','date_column':'day','label':table['name'],**kw}


def definition(env,a,b,**kw):
    return MultiStoreMetricDefinition(stores=[{'project_id':env[2],'sources':[mapping(a)]},{'project_id':env[3],'sources':[mapping(b)]}],**kw)


def test_selected_stores_same_table_names_and_exact_total(env):
    a=source(env,env[2]); b=source(env,env[3],'amount,day\n9007199254740993.01,2026-09-01\n')
    source(env,env[5],'amount,day\n999999999,2026-09-01\n',uid=env[4])
    result=preview(env,definition(env,a,b))
    assert [r['value'] for r in result['data']]==['80','9007199254740993.01']
    # Both fixtures have the same store name; grouping is by UUID, not name.
    assert len(result['data'])==2 and len({r['project_id'] for r in result['data']})==2
    total=preview(env,definition(env,a,b,group_by='none'))
    assert Decimal(total['value'])==Decimal('9007199254741073.01')
    assert total['scope']=='selected_stores' and len(total['sources'])==2
    assert 'UNION ALL' in result['execution']['sql'] and result['execution']['timezone']=='Asia/Seoul'


def test_disjoint_cash_card_refund_sources_within_store(env):
    a=source(env,env[2]); cash=source(env,env[2],'amount,day\n30,2026-09-01\n',name='현금')
    b=source(env,env[3],'amount,day\n200,2026-09-01\n')
    refunds=source(env,env[3],'amount,day\n50,2026-09-01\n',name='취소')
    d=definition(env,a,b).model_dump(); d['stores'][0]['sources'].append(mapping(cash)); d['stores'][1]['sources'].append(mapping(refunds,amount_mode='refund'))
    result=preview(env,parse_metric_definition(d))
    assert [r['value'] for r in result['data']]==['110','150']
    assert [s['included_rows'] for s in result['sources']]==[2,1,1,1]


@pytest.mark.parametrize('period', ['this_month','last_month','last_30_days'])
def test_common_period_kst_boundaries(env,period):
    with env[0]() as conn:
        conn.execute("SET TIME ZONE 'Asia/Seoul'")
        bounds={'this_month':("date_trunc('month',CURRENT_DATE)","date_trunc('month',CURRENT_DATE)+interval '1 month'"),
                'last_month':("date_trunc('month',CURRENT_DATE)-interval '1 month'","date_trunc('month',CURRENT_DATE)"),
                'last_30_days':("CURRENT_DATE-interval '29 days'","CURRENT_DATE+interval '1 day'")}
        start,end=bounds[period]
        dates=conn.execute(f"SELECT ({start}-interval '1 second')::timestamptz AS before,({start})::timestamptz AS start,({end}-interval '1 second')::timestamptz AS last,({end})::timestamptz AS after").fetchone()
    csv='amount,day\n'+''.join(f'{amount},{dates[key].isoformat()}\n' for key,amount in [('before',999),('start',100),('last',-20),('after',999)])
    a=source(env,env[2],csv); b=source(env,env[3],csv)
    assert preview(env,definition(env,a,b,group_by='none',time_range=period))['value']=='160'


def test_empty_store_preserved_and_total_not_partial(env):
    a=source(env,env[2]); b=source(env,env[3],'amount,day\n100,2026-09-01\n')
    d=definition(env,a,b).model_dump(); d['stores'][1]['sources'][0]['filters']=[{'column':'amount','operator':'>','value':'500'}]
    chart=preview(env,parse_metric_definition(d))
    assert len(chart['data'])==2 and chart['data'][1]['value'] is None and chart['undefined_groups']==1
    d['group_by']='none'; total=preview(env,parse_metric_definition(d))
    assert total['value'] is None and total['undefined_reason'] and total['store_data'][0]['value']=='80'


@pytest.mark.parametrize('column,csv,period',[('amount','amount,day\n100,2026-09-01\n,2026-09-01\n','all'),('day','amount,day\n100,2026-09-01\n10,\n','this_month')])
def test_missing_values_reject_entire_comparison(env,column,csv,period):
    a=source(env,env[2]); b=source(env,env[3],csv)
    with pytest.raises(HTTPException) as error: preview(env,definition(env,a,b,time_range=period))
    assert error.value.status_code==422


@pytest.mark.parametrize('bad',['duplicate_store','duplicate_table','foreign_currency','missing_date','different_period','unsupported_basis','unsupported_chart','one_store','too_many_sources'])
def test_definition_rejects_incompatible_selection(env,bad):
    a=source(env,env[2]); b=source(env,env[3]); d=definition(env,a,b).model_dump()
    if bad=='duplicate_store': d['stores'][1]['project_id']=d['stores'][0]['project_id']
    if bad=='duplicate_table': d['stores'][1]['sources'][0]['table_id']=d['stores'][0]['sources'][0]['table_id']
    if bad=='foreign_currency': d['stores'][0]['sources'][0]['currency']='USD'
    if bad=='missing_date': d['time_range']='this_month'; d['stores'][1]['sources'][0]['date_column']=None
    if bad=='different_period': d['stores'][1]['time_range']='last_month'
    if bad=='unsupported_basis': d['basis']='settlement'
    if bad=='unsupported_chart': d['chart_type']='line'
    if bad=='one_store': d['stores']=d['stores'][:1]
    if bad=='too_many_sources': d['stores'][0]['sources']=d['stores'][0]['sources']*6
    with pytest.raises(ValidationError): parse_metric_definition(d)


@pytest.mark.parametrize('bad',['foreign_store','wrong_table_membership','foreign_table','deleted_store','deleted_table','foreign_anchor'])
def test_scope_cannot_be_widened_or_substituted(env,bad):
    a=source(env,env[2]); b=source(env,env[3]); f=source(env,env[5],uid=env[4]); d=definition(env,a,b).model_dump(); anchor=env[2]
    if bad=='foreign_store': d['stores'][1]={'project_id':env[5],'sources':[mapping(f)]}
    if bad=='wrong_table_membership': d['stores'][0]['project_id'],d['stores'][1]['project_id']=d['stores'][1]['project_id'],d['stores'][0]['project_id']
    if bad=='foreign_table': d['stores'][1]['sources'][0]['table_id']=f['id']
    if bad=='deleted_store': db.delete_project(env[3],env[1])
    if bad=='deleted_table': db.delete_table_meta(str(b['id']),env[1])
    if bad=='foreign_anchor': anchor=env[5]
    with pytest.raises(HTTPException) as error: metrics.preview_saved_metric(anchor,env[1],parse_metric_definition(d))
    assert error.value.status_code==404


def test_new_stores_not_auto_added_and_source_deletion_preserves_last_good_chart(env):
    a=source(env,env[2]); b=source(env,env[3]); d=definition(env,a,b); saved=create(env,d)
    new=str(uuid4()); db.create_project(new,env[1],'추가 가게'); source(env,new,'amount,day\n90000,2026-09-01\n')
    import app.metric_scheduler as scheduler
    def run():
        with env[0]() as conn: conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(saved['id'],))
        with patch.object(scheduler,'_connect',env[0]): assert scheduler.refresh_one_due()
        return revisions.history(env[1],env[2],saved['id'])['metric']['widget_data']
    with env[0]() as conn:
        conn.execute(sql.SQL('INSERT INTO {} (amount,day) VALUES (30,%s)').format(sql.Identifier(db.get_user_table_name(env[1],str(b['id'])))),('2026-09-01',))
    result=run(); assert [r['value'] for r in result['data']]==['80','110']
    assert len(result['metric_definition']['stores'])==2
    db.delete_project(env[3],env[1]); failed=run()
    assert failed['refresh_error'] and failed['data']==result['data'] and failed['metric_definition']==result['metric_definition']


def test_edit_selection_restore_and_scope_preserve_id_layout_schedule(env):
    a=source(env,env[2]); b=source(env,env[3]); saved=create(env,definition(env,a,b))
    with env[0]() as conn: conn.execute('UPDATE dashboard_widgets SET layout=%s::jsonb WHERE id=%s',(json.dumps({'x':2,'y':3,'w':8,'h':9}),saved['id']))
    changed=edit(env,saved,definition(env,a,b,group_by='none'))
    assert changed['widget_type']=='kpi' and changed['widget_data']['value']=='160'
    restored=revisions.edit_metric(env[1],env[2],saved['id'],revisions.RestoreMetricRequest(revision=1,expected_revision=2,request_key=uuid4()))
    assert restored['id']==saved['id'] and restored['widget_type']=='chart' and restored['refresh_interval_seconds']==3600
    with env[0]() as conn:
        row=conn.execute('SELECT layout FROM dashboard_widgets WHERE id=%s',(saved['id'],)).fetchone()
    assert row['layout']=={'x':2,'y':3,'w':8,'h':9}
    with pytest.raises(HTTPException): revisions.history(env[1],env[3],saved['id'])


def test_other_store_read_tools_and_original_scope_are_isolated(env):
    from app.agent_tools import ToolExecutor
    a=source(env,env[2]); b=source(env,env[3]); f=source(env,env[5],uid=env[4])
    executor=ToolExecutor(env[1],env[2])
    stores=executor.execute('list_stores','{}')['stores']; assert {s['id'] for s in stores}=={env[2],env[3]}
    tables=executor.execute('list_store_tables',json.dumps({'project_id':env[3]})); assert tables['tables'][0]['id']==str(b['id'])
    details=executor.execute('inspect_store_table',json.dumps({'project_id':env[3],'table_id':str(b['id'])})); assert details['table_name']=='결제원장' and len(details['sample_rows'])==2
    assert 'error' in executor.execute('inspect_store_table',json.dumps({'project_id':env[2],'table_id':str(b['id'])}))
    assert 'error' in executor.execute('search_store_schema',json.dumps({'project_id':env[5],'query':'매출'}))
    assert 'error' in executor.execute('list_store_tables',json.dumps({'project_id':env[5]}))
    result=executor.execute('preview_metric',json.dumps(definition(env,a,b).model_dump(mode='json'))); assert result['scope']=='selected_stores'
    # Old single-store definitions retain their isolation.
    with pytest.raises(HTTPException): preview(env,MetricDefinition(table_id=b['id'],column='amount'))


def test_names_filters_and_quoted_columns_are_bound_data(env):
    odd='금액" %s'; csv='"금액"" %s",day,channel\n100,2026-09-01,x\n'
    a=source(env,env[2],csv); b=source(env,env[3],csv)
    # Import normalizes headers. Rename explicitly to exercise the SQL compiler
    # against a legal pre-existing PostgreSQL identifier containing quotes/%s.
    for table in [a,b]:
        original=table['columns_schema'][0]['name']
        with env[0]() as conn:
            conn.execute(sql.SQL('ALTER TABLE {} RENAME COLUMN {} TO {}').format(sql.Identifier(db.get_user_table_name(env[1],str(table['id']))),sql.Identifier(original),sql.Identifier(odd)))
        db.update_table_meta(str(table['id']),env[1],columns_schema=[{**c,'name':odd} if c['name']==original else c for c in table['columns_schema']])
    malicious="x'; DROP TABLE users; --%"
    db.update_project(env[3],env[1],name=malicious)
    d=definition(env,a,b).model_dump()
    for store in d['stores']:
        store['sources'][0].update(column=odd,filters=[{'column':'channel','operator':'=','value':'x'}])
    result=preview(env,parse_metric_definition(d))
    assert [r['value'] for r in result['data']]==['100','100'] and malicious in result['execution']['parameters']
    assert malicious not in result['execution']['sql']


def test_project_deletion_waits_for_validated_metric_transaction(env):
    a=source(env,env[2]); b=source(env,env[3]); entered,release=Event(),Event()
    original=metrics.calculate
    def calculating(*args): entered.set(); assert release.wait(5); return original(*args)
    with ThreadPoolExecutor(max_workers=2) as pool,patch.object(metrics,'calculate',side_effect=calculating):
        running=pool.submit(preview,env,definition(env,a,b)); assert entered.wait(5)
        deleting=pool.submit(db.delete_project,env[3],env[1])
        assert not deleting.done()
        release.set(); assert len(running.result(timeout=5)['data'])==2
        assert deleting.result(timeout=5)


def test_store_and_table_discovery_paginates_without_omissions(env):
    for i in range(21): db.create_project(str(uuid4()),env[1],f'가게{i:02}')
    page=store_metric_tools.list_stores(env[1],{}); assert len(page['stores'])==20 and page['next_offset']==20
    rest=store_metric_tools.list_stores(env[1],{'offset':20}); assert len(rest['stores'])==3 and rest['next_offset'] is None
    assert len({s['id'] for s in page['stores']+rest['stores']})==23
    for i in range(11): source(env,env[2],name=f'원장{i:02}')
    first=store_metric_tools.list_store_tables(env[1],{'project_id':env[2]}); assert len(first['tables'])==10
    last=store_metric_tools.list_store_tables(env[1],{'project_id':env[2],'offset':first['next_offset']}); assert len(last['tables'])==1 and last['next_offset'] is None


@pytest.mark.parametrize('currency',['USD',''])
def test_actual_currency_column_is_checked_even_if_not_explicitly_mapped(env,currency):
    a=source(env,env[2]); b=source(env,env[3],f'amount,day,currency\n100,2026-09-01,KRW\n100,2026-09-01,{currency}\n')
    with pytest.raises(HTTPException) as error: preview(env,definition(env,a,b))
    assert error.value.status_code==422 and '통화' in error.value.detail
