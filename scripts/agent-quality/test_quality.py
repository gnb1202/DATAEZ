"""The evaluator must reject plausible-looking but wrong answers and charts."""
import copy
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parent))
from catalog import load_catalog,select,oracle
from scoring import evaluate,cells,canonical_filters
from run import tool_specs,apply_reviews

CATALOG=load_catalog()


def successful():
    case=CATALOG['cases'][0]
    target='11111111-1111-4111-8111-111111111111'
    definition={'version':1,'table_id':target,'column':'승인금액','operation':'sum','group_by':'거래일시',
                'date_grain':'day','time_range':'all','filters':[],'chart_type':'line','unit':'KRW'}
    chart={'metric_definition':definition,'chart_type':'line','unit':'KRW','x_key':'dimension','y_key':'value',
           'data':[{'dimension':k,'value':v} for k,v in sorted(case['expected'].items())],
           'execution':{'sql':'SELECT day, SUM(amount) FROM fixture GROUP BY day','parameterized':True}}
    arguments={k:v for k,v in definition.items() if k!='table_id'}
    arguments['table_name']='선택한 원본'
    raw={'case':{'checks':{'exact_cells':True},'seconds':1},'evidence':{'content':'일별 매출 미리보기입니다.',
         'steps':[{'type':'tool_call','tool_name':'preview_metric','tool_input':arguments,'tool_output':chart}],
         'charts':[copy.deepcopy(chart)]},'widgets_before':[],'widgets_after':[]}
    return copy.deepcopy(case),raw,{'a':{'original_file':{'table_id':target}}}


def grade(raw=None):
    c,r,ids=successful()
    return evaluate(c,raw or r,ids,tool_specs())


def test_frozen_catalog_and_followup_dependency():
    assert len(CATALOG['cases'])==24
    assert [c['id'] for c in select(CATALOG,ids='Q02')]==['Q01','Q02']
    assert len(select(CATALOG))==6
    assert oracle.expected({'file':'a','scope':'original_file'})=={'__NULL__':'64002.10'}


def test_wrong_frozen_oracle_rejected(tmp_path):
    value=copy.deepcopy(CATALOG);value['cases'][0]['expected']['2026-08-31']='0'
    p=tmp_path/'questions.json';p.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='oracle mismatch'):load_catalog(p)


def test_valid_tool_definition_chart_passes():
    assert grade()['automatic_passed']


@pytest.mark.parametrize('change,failed',[
    ('wrong_value','chart_exact_cells'),('duplicate_chart','exactly_one_chart'),
    ('static_chart','chart_definition'),('wrong_type','chart_type'),('wrong_unit','chart_unit'),
    ('wrong_source','chart_source'),('wrong_group','chart_definition'),
    ('missing_axis','chart_exact_cells'),('duplicate_dimension','chart_exact_cells'),
    ('nonfinite','chart_exact_cells'),('wrong_order','chronological_axis'),
    ('invalid_arg','function_arguments_schema'),('wrong_arg_group','tool_input_semantics'),
    ('unauthorized_write','no_write_tool_attempt'),('http_error','completed_response'),
    ('no_parameterized_sql','parameterized_sql'),
])
def test_mutations_are_detected(change,failed):
    _,raw,_=successful();chart=raw['evidence']['charts'][0];step=raw['evidence']['steps'][0]
    if change=='wrong_value':chart['data'][0]['value']='999999'
    if change=='duplicate_chart':raw['evidence']['charts'].append(copy.deepcopy(chart))
    if change=='static_chart':chart.pop('metric_definition')
    if change=='wrong_type':chart['chart_type']='bar'
    if change=='wrong_unit':chart['unit']='count'
    if change=='wrong_source':chart['metric_definition']['table_id']='other-account-table'
    if change=='wrong_group':chart['metric_definition']['group_by']='결제수단'
    if change=='missing_axis':chart['data'][0].pop('dimension')
    if change=='duplicate_dimension':chart['data'].append(copy.deepcopy(chart['data'][0]))
    if change=='nonfinite':chart['data'][0]['value']='NaN'
    if change=='wrong_order':chart['data'].reverse()
    if change=='invalid_arg':step['tool_input']['unknown_property']=True
    if change=='wrong_arg_group':step['tool_input']['group_by']='결제수단'
    if change=='unauthorized_write':raw['evidence']['steps'].append({'type':'tool_call','tool_name':'save_metric','tool_input':{}})
    if change=='http_error':raw['case']['error']='HTTP 503'
    if change=='no_parameterized_sql':step['tool_output']['execution']['parameterized']=False
    result=grade(raw)
    assert not result['automatic_passed']
    assert failed in result['failed_checks']


@pytest.mark.parametrize('value',['NaN','Infinity','',True])
def test_numeric_cells_do_not_accept_coercion(value):
    with pytest.raises(ValueError):cells({'value':value},{})


def test_null_category_is_not_a_missing_axis():
    assert cells({'x_key':'x','y_key':'y','data':[{'x':None,'y':'5'}]}, {'group':'x'})=={'__NULL__':5}


def test_clarification_needs_review_even_with_matching_words():
    case=CATALOG['cases'][18]
    raw={'case':{'checks':{}},'evidence':{'content':'원가 비용 이익','steps':[],'charts':[]},'widgets_before':[],'widgets_after':[]}
    result=evaluate(case,raw,{},tool_specs())
    assert result['review_status']=='pending'
    assert result['automatic_passed']


def test_clarification_does_not_allow_fabricated_chart():
    case=CATALOG['cases'][18]
    raw={'case':{'checks':{}},'evidence':{'content':'자료가 부족합니다','steps':[],'charts':[{}]},'widgets_before':[],'widgets_after':[]}
    assert not evaluate(case,raw,{},tool_specs())['automatic_passed']


def test_review_must_match_exact_evidence(tmp_path):
    row=grade();p=tmp_path/'reviews.json'
    p.write_text(json.dumps([{'id':row['id'],'evidence_sha256':'outdated','passed':True,'reviewer':'test','reason':'reviewed'}]))
    with pytest.raises(ValueError,match='Stale'):apply_reviews([row],p)


@pytest.mark.parametrize('value',['2026-09-01','2026-09-01 00:00:00','2026-09-01T00:00:00.000','2026-09-01T00:00:00+09:00'])
def test_equivalent_midnight_boundaries(value):
    assert canonical_filters([{'column':'date','operator':'>=','value':value}],'date')==[('date','>=','2026-09-01')]


@pytest.mark.parametrize('value',['2026-09-01 00:00:01','2026-09-01T00:00:00+08:00','2026-09-01T00:00:00Z'])
def test_distinct_date_boundaries_remain_distinct(value):
    assert canonical_filters([{'column':'date','operator':'>=','value':value}],'date')[0][2]==value


def test_non_date_text_and_exclusive_operator_not_normalized():
    assert canonical_filters([{'column':'memo','value':'2026-09-01 00:00:00'}],'date')==[('memo','=','2026-09-01 00:00:00')]
    assert canonical_filters([{'column':'date','operator':'>','value':'2026-09-01'}],'date')[0][1]=='>'
