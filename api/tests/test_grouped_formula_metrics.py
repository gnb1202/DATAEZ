"""Real PostgreSQL checks for grouped formulas and their saved lifecycle."""
from decimal import Decimal
import json
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from psycopg import sql
from app import db, dashboard_metrics as metrics, metric_revisions as revisions
from app.metric_definitions import GroupedFormulaMetricDefinition, MetricDefinition, parse_metric_definition
from tests.test_formula_revisions import env, source, operand, preview, create, edit
from tests.test_rag_postgres import vector_db, DSN

pytestmark = pytest.mark.skipif(not DSN, reason='Set DATAEZ_RAG_TEST_DATABASE_URL')


def grouped(meta, right=None, **kw):
    return GroupedFormulaMetricDefinition(operation='difference', dimension_label='채널',
        left=operand(meta, group_by='channel'), right=operand(right or meta, 'fee', group_by='channel'), **kw)


def test_independent_aggregates_no_raw_join_multiplication_and_exact_precision(env):
    left = source(env, 'amount,channel\n9007199254740993.01,매장\n100,매장\n-20,매장\n')
    right = source(env, 'fee,channel\n0.01,매장\n3,매장\n-0.6,매장\n')
    result = preview(env, grouped(left, right))
    row = result['data'][0]
    assert Decimal(row['value']) == Decimal('9007199254741070.60')
    assert Decimal(row['left_value']) == Decimal('9007199254741073.01')
    assert result['point_count'] == 1 and result['unit'] == 'KRW'
    assert 'UNION ALL' in result['execution']['sql'] and '%s' in result['execution']['sql']
    assert '매장' not in result['execution']['sql']


@pytest.mark.parametrize('policy,expected', [('undefined', None), ('zero', '100')])
def test_absent_group_explicit_policy_null_category_and_literal_are_distinct(env, policy, expected):
    a = source(env, 'amount,channel\n100,매장\n20,\n40,미제공\n')
    b = source(env, 'fee,channel\n2,\n4,미제공\n5,배달\n')
    result = preview(env, grouped(a, b, missing_group=policy))
    rows = {r['dimension']: r for r in result['data']}
    assert rows['매장']['value'] == expected
    assert rows[None]['value'] == '18' and rows['미제공']['value'] == '36'
    assert rows['매장']['zero_filled'] == (['right'] if policy == 'zero' else [])
    assert result['undefined_groups'] == (2 if policy == 'undefined' else 0)
    assert len(rows) == 4


def test_zero_denominator_stays_gap_even_when_missing_group_zero(env):
    meta = source(env, 'amount,fee,channel\n10,0,매장\n-10,100,배달\n')
    payload = grouped(meta).model_dump(); payload.update(operation='ratio', missing_group='zero')
    payload['left']['absolute'] = True
    result = preview(env, parse_metric_definition(payload))
    rows = {r['dimension']: r for r in result['data']}
    assert rows['매장']['value'] is None and '분모가 0' in rows['매장']['undefined_reason']
    assert rows['배달']['value'] == '10.0000'


def test_numeric_null_is_not_empty_group_or_zero(env):
    meta = source(env, 'amount,fee,channel\n100,3,매장\n200,,배달\n')
    with pytest.raises(HTTPException) as err: preview(env, grouped(meta, missing_group='zero'))
    assert err.value.status_code == 422 and '미제공' in err.value.detail


@pytest.mark.parametrize('grain,expected', [
    ('day', [('2026-08-30', '97'), ('2026-08-31', '194'), ('2026-09-01', '291')]),
    ('week', [('2026-08-24', '97'), ('2026-08-31', '485')]),
    ('month', [('2026-08-01', '291'), ('2026-09-01', '291')]),
])
def test_date_buckets_use_kst_and_monday_week_start(env, grain, expected):
    meta = source(env, 'amount,fee,day\n100,3,2026-08-30T14:59:59Z\n200,6,2026-08-30T15:00:00Z\n300,9,2026-08-31T15:00:00Z\n')
    definition = GroupedFormulaMetricDefinition(operation='difference', dimension_label='날짜', chart_type='line',
        left=operand(meta, group_by='day', date_grain=grain), right=operand(meta, 'fee', group_by='day', date_grain=grain))
    result = preview(env, definition)
    assert [(r['dimension'], r['value']) for r in result['data']] == expected
    assert result['execution']['timezone'] == 'Asia/Seoul'


def test_channel_period_growth_and_count_ratio(env):
    with env[0]() as conn:
        dates=conn.execute("SELECT date_trunc('month',CURRENT_DATE)::date current,(date_trunc('month',CURRENT_DATE)-interval '1 month')::date previous").fetchone()
    meta=source(env, f"amount,day,channel\n100,{dates['previous']},매장\n125,{dates['current']},매장\n50,{dates['current']},배달\n")
    d=GroupedFormulaMetricDefinition(operation='percent_change', dimension_label='채널',
        left=operand(meta, group_by='channel', date_column='day', time_range='this_month'),
        right=operand(meta, group_by='channel', date_column='day', time_range='last_month'))
    rows={r['dimension']:r for r in preview(env,d)['data']}
    assert rows['매장']['value']=='25.0000' and rows['배달']['value'] is None
    count={'label':'건수','unit':'count','definition':{'table_id':meta['id'],'operation':'count','group_by':'channel'}}
    d=GroupedFormulaMetricDefinition(operation='ratio',dimension_label='채널',left=count,right=count,as_percent=False)
    assert all(r['value']=='1.0000' for r in preview(env,d)['data'])


@pytest.mark.parametrize('bad', ['unit','no_group','mixed_grain','date_period','zero_avg','code','pie'])
def test_grammar_rejects_ambiguous_or_unsupported_definitions(env,bad):
    meta=source(env,'amount,fee,channel\n1,1,매장\n'); d=grouped(meta).model_dump()
    if bad=='unit': d['right']['unit']='number'
    if bad=='no_group': d['right']['definition']['group_by']=None
    if bad=='mixed_grain': d['left']['definition']['date_grain']='day'
    if bad=='date_period':
        for side in ['left','right']: d[side]['definition'].update(date_grain='month',date_column='channel')
        d['right']['definition']['time_range']='last_month'
    if bad=='zero_avg': d['missing_group']='zero'; d['left']['definition']['operation']='avg'
    if bad=='code': d['expression']='eval(x)'
    if bad=='pie': d['chart_type']='pie'
    with pytest.raises(ValidationError): parse_metric_definition(d)


def test_numeric_group_requires_supported_type_and_isolation(env):
    meta=source(env,'amount,fee,channel\n100,3,매장\n'); d=grouped(meta)
    for uid,pid in [(env[1],env[3]),(env[4],env[5])]:
        with pytest.raises(HTTPException): metrics.preview_saved_metric(pid,uid,d)
    for side in [d.left,d.right]: side.definition.group_by='amount'
    with pytest.raises(HTTPException) as err: preview(env,d)
    assert err.value.status_code==422


def test_group_limit_empty_and_bound_parameters(env):
    meta=source(env,'amount,fee,channel\n'+'\n'.join(f'100,3,c{i:04}' for i in range(1001)))
    with pytest.raises(HTTPException) as err: preview(env,grouped(meta))
    assert '1,000' in err.value.detail
    payload=grouped(meta).model_dump()
    for side in ['left','right']: payload[side]['definition']['filters']=[{'column':'channel','operator':'<','value':'c1000'}]
    assert len(preview(env,parse_metric_definition(payload))['data'])==1000
    malicious="x%'; DROP TABLE users; --"
    for side in ['left','right']: payload[side]['definition']['filters']=[{'column':'channel','operator':'=','value':malicious}]
    result=preview(env,parse_metric_definition(payload))
    assert result['data']==[] and malicious not in result['execution']['sql']
    assert result['execution']['parameters'].count(malicious)==2


def test_saved_chart_edit_restore_scheduler_refresh_and_failure(env):
    meta=source(env,'amount,fee,channel\n100,3,매장\n'); saved=create(env,MetricDefinition(table_id=meta['id'],column='amount'))
    with env[0]() as conn: conn.execute('UPDATE dashboard_widgets SET layout=%s::jsonb WHERE id=%s',(json.dumps({'x':1,'y':2,'w':7,'h':10}),saved['id']))
    changed=edit(env,saved,grouped(meta))
    assert changed['definition_revision']==2 and changed['widget_data']['data'][0]['value']=='97'
    with env[0]() as conn:
        row=conn.execute('SELECT widget_type,layout,refresh_interval_seconds FROM dashboard_widgets WHERE id=%s',(saved['id'],)).fetchone()
        conn.execute(sql.SQL('INSERT INTO {} (amount,fee,channel) VALUES (200,6,%s)').format(sql.Identifier(db.get_user_table_name(env[1],str(meta['id'])))),('매장',))
        conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(saved['id'],))
    assert row=={'widget_type':'chart','layout':{'x':1,'y':2,'w':7,'h':10},'refresh_interval_seconds':3600}
    import app.metric_scheduler as scheduler
    with patch.object(scheduler,'_connect',env[0]): assert scheduler.refresh_one_due()
    result=revisions.history(env[1],env[2],saved['id'])['metric']['widget_data']
    assert result['data'][0]['value']=='291' and result['definition_revision']==2
    restored=revisions.edit_metric(env[1],env[2],saved['id'],revisions.RestoreMetricRequest(revision=1,expected_revision=2,request_key=uuid4()))
    assert restored['widget_data']['value']=='300'
    edit(env,saved,grouped(meta),revision=3)
    db.update_table_meta(str(meta['id']),env[1],columns_schema=[c for c in meta['columns_schema'] if c['name']!='fee'])
    with env[0]() as conn: conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s",(saved['id'],))
    with patch.object(scheduler,'_connect',env[0]): assert scheduler.refresh_one_due()
    result=revisions.history(env[1],env[2],saved['id'])['metric']['widget_data']
    assert result['refresh_error'] and result['data'][0]['value']=='291'


def test_tool_resolves_grouped_formula_from_observed_names(env):
    from app.agent_tools import ToolExecutor
    meta=source(env,'amount,fee,channel\n100,3,매장\n'); args=grouped(meta).model_dump(mode='json')
    for side in ['left','right']:
        args[side]['definition'].pop('table_id'); args[side]['definition']['table_name']='결제'
    result=ToolExecutor(env[1],env[2]).execute('preview_metric',json.dumps(args))
    assert result['metric_definition']['version']==4 and result['data'][0]['value']=='97'
