"""An older requested batch must remain reachable after context compaction."""
import json
import pytest
from uuid import uuid4

from app.agent import _tool_result_content
from app.prompts import build_system_prompt


def test_history_context_pages_preserve_all_batches_without_cutting_json():
    batches = [{'id': str(uuid4()), 'filename': f'{i:02}_업로드.csv', 'status': 'failed' if i == 0 else 'committed',
                'summary': {'counts': {'new': i, 'duplicate': 12}, 'amount': '12345678901234567890.01', 'row_count': 26},
                'result': {'rows_inserted': 14, 'duplicates_skipped': 12},
                'error': {'message': '검증 실패', 'issues': [{'raw': 'x' * 1000}] * 50} if i == 0 else None,
                'review_url': '/dashboard?batch=' + str(uuid4())} for i in range(27)]
    offset, seen = 0, []
    while True:
        response = {'offset': offset, 'limit': 20, 'total': len(batches), 'batches': batches[offset:offset + 20]}
        content = _tool_result_content('list_import_history', response)
        assert len(content) < 4000
        page = json.loads(content)
        assert page['returned_count'] == len(page['batches']) > 0
        seen.extend(b['id'] for b in page['batches'])
        assert page['batches'][0]['summary']['amount'] == '12345678901234567890.01'
        if page['next_offset'] is None:
            break
        assert page['next_offset'] > offset
        offset = page['next_offset']
    assert seen == [b['id'] for b in batches]


def test_history_error_and_empty_page_remain_readable():
    error = {'error': 'not_found', 'message': '업로드를 찾을 수 없습니다.'}
    assert json.loads(_tool_result_content('list_import_history', error)) == error
    empty = json.loads(_tool_result_content('list_import_history', {'total': 0, 'offset': 0, 'batches': []}))
    assert empty['next_offset'] is None and empty['returned_count'] == 0


def test_large_chart_context_is_valid_sample_without_losing_full_evidence():
    rows = [{'dimension':str(i),'value':'9007199254740993.01','undefined_reason':None} for i in range(1000)]
    output = {'metric_definition':{'version':4,'left':{'definition':{'table_id':str(uuid4())}}},
              'data':rows,'execution':{'sql':'SELECT '+ 'x'*10000},'undefined_groups':0,'warnings':['빈 그룹은 제외']}
    page = json.loads(_tool_result_content('preview_metric',output))
    assert page['data_is_sample'] and page['total_groups']==1000 and len(page['data'])==5
    assert page['metric_definition']==output['metric_definition'] and 'execution' not in page
    assert len(output['data'])==1000 and 'execution' in output


def test_scalar_preview_context_keeps_exact_facts_and_explains_missing_counts():
    output = {'metric_definition': {'version': 1, 'table_id': str(uuid4()), 'time_range': 'this_month'},
              'value': '9007199254740993.01', 'execution': {'sql': 'SELECT sum(amount)'}}
    page = json.loads(_tool_result_content('preview_metric', output))
    assert page['value'] == output['value'] and page['metric_definition'] == output['metric_definition']
    assert 'row_count' not in page and 'included_rows' not in page
    assert 'sample_rows' in page['evidence_limits'] and '포함 건수가 아닙니다' in page['evidence_limits']
    assert 'evidence_limits' not in output  # Model context notes never rewrite persisted facts.


def test_current_store_context_supplies_real_table_ids_for_multi_store_metrics():
    table_id = str(uuid4())
    prompt = build_system_prompt('현재 가게', [{'id': table_id, 'name': '결제', 'row_count': 700,
                                               'columns_schema': [{'name': 'amount', 'type': 'NUMERIC'}]}])
    assert f'[table_id={table_id}]' in prompt
    assert '전체 700행, 기간 필터 적용 전' in prompt


def test_many_store_metric_definitions_do_not_break_list_json():
    metrics=[{'id':str(uuid4()),'title':f'비교{i}','definition_revision':2,'definition':{'stores':['x'*4000]*10}} for i in range(10)]
    page=json.loads(_tool_result_content('list_metrics',{'metrics':metrics}))
    assert len(page['metrics'])==10 and all('definition' not in m for m in page['metrics'])
    assert 'get_metric_history' in page['hint'] and all(m['definition_revision']==2 for m in page['metrics'])


@pytest.mark.parametrize('tool,collection',[('get_metric_history','revisions'),('list_cash_entries','entries')])
def test_metric_and_cash_history_remain_pageable_json(tool,collection):
    entries=[{'id':str(uuid4()),'revision':i,'memo':'긴 메모 '*100,'definition':{'filters':[{'column':'channel','value':'매장'}]*5}} for i in range(25)]
    offset=0; seen=[]
    while True:
        output={'total':len(entries),'offset':offset,collection:entries[offset:offset+20],
                'metric':{'id':str(uuid4()),'title':'매출','definition_revision':25,'widget_data':{'huge':'x'*10000}}}
        page=json.loads(_tool_result_content(tool,output))
        assert page['returned_count']>0 and 'widget_data' not in page['metric']
        seen.extend(item['id'] for item in page[collection])
        if page['next_offset'] is None: break
        offset=page['next_offset']
    assert seen==[item['id'] for item in entries]
