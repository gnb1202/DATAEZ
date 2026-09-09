"""K: real SQL snapshots and concurrent definition edits, no external models."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import db, dashboard_metrics as metrics, metric_revisions as revisions, table_imports
from app.metric_definitions import FormulaMetricDefinition, MetricDefinition, MetricFilter
from app.storage import StorageService
from tests.test_rag_postgres import vector_db, DSN

pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_RAG_TEST_DATABASE_URL')


@pytest.fixture
def env(vector_db, monkeypatch):
    monkeypatch.setattr(metrics, '_connect', vector_db[0])
    db.ensure_dashboard_widgets_table()
    db.ensure_project_tables()
    revisions.ensure_metric_revisions()
    return vector_db


def source(env, content='amount,fee,method\n100,3,card\n200,6,cash\n-20,-0.6,card\n'):
    return table_imports.create_imported_table(env[1], env[2], '결제', content.encode(), 'source.csv', StorageService())


def operand(meta, column='amount', **kw):
    return {'label':column,'unit':'KRW','definition':{'table_id':str(meta['id']),'column':column,**kw}}


def formula(meta, operation='difference', **kw):
    return FormulaMetricDefinition(operation=operation,left=operand(meta),right=operand(meta,'fee'),**kw)


def preview(env, definition):
    return metrics.preview_saved_metric(env[2],env[1],definition)


def create(env, definition):
    return metrics.create_saved_metric(env[2],env[1],metrics.CreateMetricRequest(title='기존 지표',definition=definition,refresh_interval_seconds=3600))


def edit(env, metric, definition, revision=1, key=None, title='수정 지표'):
    return revisions.edit_metric(env[1],env[2],str(metric['id']),revisions.EditMetricRequest(
        title=title,definition=definition,expected_revision=revision,request_key=key or uuid4()))


def test_difference_preserves_signed_fees_and_large_exact_decimals(env):
    meta=source(env,'amount,fee\n9007199254740993.01,0.01\n-20,-0.6\n')
    result=preview(env,formula(meta))
    assert Decimal(result['value']) == Decimal('9007199254740973.60')
    assert result['unit']=='KRW' and '−' in result['calculation_label']


def test_amount_refund_ratio_and_count_ratio(env):
    meta=source(env)
    definition=FormulaMetricDefinition(operation='ratio',left={**operand(meta,filters=[{'column':'amount','operator':'<','value':'0'}]),'absolute':True},
        right=operand(meta,filters=[{'column':'amount','operator':'>','value':'0'}]))
    result=preview(env,definition)
    assert result['value']=='6.6667' and result['formatted']=='6.6667%'
    count={'label':'건수','unit':'count','definition':{'table_id':str(meta['id']),'operation':'count'}}
    result=preview(env,FormulaMetricDefinition(operation='ratio',as_percent=False,left=count,right=count))
    assert result['value']=='1.0000' and result['formatted']=='1'


def test_month_comparison_uses_explicit_periods(env):
    with env[0]() as conn:
        dates=conn.execute("SELECT date_trunc('month',CURRENT_DATE)::date AS current,(date_trunc('month',CURRENT_DATE)-interval '1 month')::date AS previous").fetchone()
    meta=source(env,f"amount,day\n200,{dates['previous']}\n250,{dates['current']}\n")
    result=preview(env,FormulaMetricDefinition(operation='percent_change',
        left=operand(meta,date_column='day',time_range='this_month'),right=operand(meta,date_column='day',time_range='last_month')))
    assert result['value']=='25.0000' and result['formatted']=='25%'
    assert result['period_label']=='이번 달 / 지난달' and result['warnings']


@pytest.mark.parametrize('kind', ['zero','empty'])
def test_undefined_ratio_is_saved_without_inventing_zero(env,kind):
    meta=source(env,'amount,fee\n100,0\n')
    definition=formula(meta,'ratio')
    if kind=='empty':
        definition.right.definition.filters=[MetricFilter(column='amount',operator='>',value='500')]
        definition=FormulaMetricDefinition.model_validate(definition.model_dump())
    saved=create(env,definition)
    assert saved['widget_data']['value'] is None and saved['widget_data']['formatted']=='계산 불가'
    assert saved['widget_data']['undefined_reason']


def test_missing_operand_is_not_silently_excluded(env):
    meta=source(env,'amount,fee\n100,3\n200,\n')
    with pytest.raises(HTTPException) as err:
        preview(env,formula(meta))
    assert err.value.status_code==422 and '미제공' in err.value.detail


@pytest.mark.parametrize('invalid', ['units','group','count_unit','code'])
def test_formula_grammar_rejects_unsupported_definitions(env,invalid):
    meta=source(env)
    data=formula(meta).model_dump()
    if invalid=='units': data['right']['unit']='number'
    if invalid=='group': data['left']['definition']['group_by']='method'
    if invalid=='count_unit': data['left']['definition']['operation']='count'
    if invalid=='code': data['expression']='__import__("os")'
    with pytest.raises(ValidationError): FormulaMetricDefinition.model_validate(data)


def test_formula_and_history_scope(env):
    meta=source(env)
    saved=create(env,formula(meta))
    for uid,pid in [(env[1],env[3]),(env[4],env[5])]:
        with pytest.raises(HTTPException): metrics.preview_saved_metric(pid,uid,formula(meta))
        with pytest.raises(HTTPException): revisions.history(uid,pid,saved['id'])
        with pytest.raises(HTTPException): revisions.edit_metric(uid,pid,saved['id'],revisions.EditMetricRequest(title='x',definition=formula(meta),expected_revision=1,request_key=uuid4()))


def test_edit_history_restore_and_replay_preserve_identity_layout_schedule(env):
    meta=source(env)
    initial=MetricDefinition(table_id=meta['id'],column='amount')
    saved=create(env,initial)
    with env[0]() as conn:
        conn.execute('UPDATE dashboard_widgets SET layout=%s::jsonb WHERE id=%s',(json.dumps({'x':2,'y':7,'w':4,'h':6}),saved['id']))
    key=uuid4()
    changed=edit(env,saved,formula(meta),key=key)
    assert changed['definition_revision']==2 and Decimal(changed['widget_data']['value'])==Decimal('271.60')
    assert edit(env,saved,formula(meta),key=key)['replayed']
    assert revisions.history(env[1],env[2],saved['id'])['total']==2
    restored=revisions.edit_metric(env[1],env[2],saved['id'],revisions.RestoreMetricRequest(revision=1,expected_revision=2,request_key=uuid4()))
    assert restored['definition_revision']==3 and restored['widget_data']['value']=='280'
    later_replay=edit(env,saved,formula(meta),key=key)
    assert later_replay['definition_revision']==3 and later_replay['applied_revision']==2
    with env[0]() as conn:
        row=conn.execute('SELECT layout,refresh_interval_seconds FROM dashboard_widgets WHERE id=%s',(saved['id'],)).fetchone()
    assert row['layout']=={'x':2,'y':7,'w':4,'h':6} and row['refresh_interval_seconds']==3600


def test_conflicting_edits_one_wins_and_reused_key_rejects_different_content(env):
    meta=source(env); saved=create(env,formula(meta)); key=uuid4()
    def write(title):
        try: return edit(env,saved,formula(meta),key=key,title=title)
        except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(write,['A','B']))
    assert sum(isinstance(r,dict) for r in results)==1 and 409 in results
    assert revisions.history(env[1],env[2],saved['id'])['total']==2
    with pytest.raises(HTTPException) as err: edit(env,saved,formula(meta))
    assert err.value.status_code==409


def test_failed_edit_and_restore_keep_previous_definition_and_history(env):
    meta=source(env); saved=create(env,formula(meta))
    bad=MetricDefinition(table_id=meta['id'],column='does_not_exist')
    with pytest.raises(HTTPException): edit(env,saved,bad)
    assert revisions.history(env[1],env[2],saved['id'])['total']==1
    edit(env,saved,MetricDefinition(table_id=meta['id'],column='amount'))
    db.update_table_meta(str(meta['id']),env[1],columns_schema=[c for c in meta['columns_schema'] if c['name']!='fee'])
    with pytest.raises(HTTPException): revisions.edit_metric(env[1],env[2],saved['id'],revisions.RestoreMetricRequest(revision=1,expected_revision=2,request_key=uuid4()))
    assert revisions.history(env[1],env[2],saved['id'])['metric']['definition_revision']==2


def test_refresh_retains_revision_and_failed_refresh_preserves_good_value(env):
    meta=source(env); saved=create(env,formula(meta)); edit(env,saved,formula(meta))
    from app.metric_scheduler import refresh_one_due
    import app.metric_scheduler as scheduler
    with env[0]() as conn: conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(saved['id'],))
    with patch.object(scheduler,'_connect',env[0]): assert refresh_one_due()
    assert revisions.history(env[1],env[2],saved['id'])['metric']['definition_revision']==2
    db.update_table_meta(str(meta['id']),env[1],columns_schema=[c for c in meta['columns_schema'] if c['name']!='fee'])
    with env[0]() as conn: conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(saved['id'],))
    with patch.object(scheduler,'_connect',env[0]): assert refresh_one_due()
    row=revisions.history(env[1],env[2],saved['id'])['metric']['widget_data']
    assert Decimal(row['value'])==Decimal('271.60') and row['definition_revision']==2 and row['refresh_error']


def test_natural_tools_resolve_operands_and_use_observed_revision(env):
    meta=source(env); saved=create(env,formula(meta))
    from app.agent_tools import ToolExecutor
    args=formula(meta).model_dump(mode='json')
    for side in ['left','right']:
        args[side]['definition'].pop('table_id'); args[side]['definition']['table_name']='결제'
    executor=ToolExecutor(env[1],env[2])
    result=executor.execute('preview_metric',json.dumps(args))
    assert Decimal(result['value'])==Decimal('271.60')
    edited=executor.execute('update_metric',json.dumps({**args,'metric_id':saved['id'],'expected_revision':1,'title':'자연어 수정'}))
    assert edited['saved'] and edited['definition_revision']==2
