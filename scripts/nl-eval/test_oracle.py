"""Reject false positives in the benchmark before making model calls."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from cases import CASES, single, stores
from grading import grade, shape
from oracle import expected, fixture, normalized_values
from run import selection

TODAY = date(2026, 9, 8)
ROWS = fixture(TODAY)
TABLES = {key: 'table-'+key for key in ROWS}
STORES = {key: 'store-'+key for key in ['main', 'hong', 'empty', 'usd', 'foreign']}


def test_all_50_unique_and_dependencies_are_explicit():
    assert [c['id'] for c in CASES] == [f'{i:02}' for i in range(1, 51)]
    assert [c['id'] for c in selection('42')] == ['37', '38', '39', '40', '41', '42']
    with pytest.raises(ValueError): selection('51')


@pytest.mark.parametrize('period,wanted', [('all', '232000'), ('this_month', '172000'), ('last_month', '60000')])
def test_korean_month_boundary_and_signed_refunds(period, wanted):
    assert expected(single(period=period), ROWS, TODAY) == {None: Decimal(wanted)}


def test_exact_formula_values_and_zero_denominator():
    assert expected(CASES[22]['plan'], ROWS, TODAY)[None] == Decimal('225040')
    assert expected(CASES[23]['plan'], ROWS, TODAY)[None] == Decimal('11.4504')
    assert expected(CASES[24]['plan'], ROWS, TODAY)[None] == Decimal('40.0000')
    assert expected(CASES[26]['plan'], ROWS, TODAY)[None] is None


def test_missing_groups_and_explicit_zero_are_distinct():
    assert expected(CASES[28]['plan'], ROWS, TODAY)['방문'] is None
    assert expected(CASES[29]['plan'], ROWS, TODAY)['계좌이체'] == 0
    assert expected(CASES[30]['plan'], ROWS, TODAY)['매장'] is None


def test_empty_store_never_becomes_partial_total():
    assert expected(stores(keys=('main', 'empty')), ROWS, TODAY) == {None: None}
    assert expected(stores(group='store', keys=('main', 'empty')), ROWS, TODAY) == {'main': Decimal('172000'), 'empty': None}


def test_numeric_null_blocks_until_user_explicitly_filters():
    with pytest.raises(ValueError): expected(single('missing', column='fee'), ROWS, TODAY)
    assert expected(CASES[45]['plan'], ROWS, TODAY) == {None: Decimal('600')}


def test_result_parser_rejects_duplicate_dimensions_and_preserves_decimal():
    plan = single(group='channel')
    with pytest.raises(ValueError):
        normalized_values({'data': [{'dimension': 'x', 'value': '1'}, {'dimension': 'x', 'value': '2'}]}, plan, TABLES, STORES)
    assert normalized_values({'value': '9007199254740993.01'}, single(), TABLES, STORES) == {None: Decimal('9007199254740993.01')}


def evidence():
    definition = dict(version=1, table_id=TABLES['pg'], operation='sum', column='amount', time_range='all', filters=[])
    return dict(answer='전체 순결제액 232,000원입니다.', steps=[dict(type='tool_call', tool_name='preview_metric',
        tool_output=dict(metric_definition=definition, value='232000', execution={'sql': 'SELECT sum(amount) FROM fixture'}))])


@pytest.mark.parametrize('fault,failed_check', [('value', 'exact_result_cells'), ('scope', 'definition_scope_period_filters'), ('filter', 'definition_scope_period_filters'), ('write', 'only_requested_widget_write_tools'), ('raw', 'no_raw_write_tool'), ('state', 'source_state_unchanged')])
def test_grader_detects_plausible_but_wrong_outputs(fault, failed_check):
    result = evidence()
    if fault == 'value': result['steps'][0]['tool_output']['value'] = '1232000'  # Contains the correct number as a substring.
    if fault == 'scope': result['steps'][0]['tool_output']['metric_definition']['table_id'] = TABLES['hong']
    if fault == 'filter': result['steps'][0]['tool_output']['metric_definition']['filters'] = [dict(column='event_kind', operator='=', value='payment')]
    if fault in {'write', 'raw'}: result['steps'].append(dict(type='tool_call', tool_name='save_metric' if fault == 'write' else 'insert_rows', tool_output={}))
    checks, _ = grade(CASES[0], result, [], [], fault != 'state', ROWS, TODAY, TABLES, STORES)
    assert not checks[failed_check]
    assert not all(checks.values())


def test_grader_accepts_correct_result_and_rejects_empty_execution():
    result = evidence()
    # describe_table returns real PostgreSQL Decimal/timestamp sample cells.
    result['steps'].insert(0, dict(type='tool_call', tool_name='describe_table', tool_output={'sample': [{'amount': Decimal('100000'), 'day': TODAY}]}))
    checks, _ = grade(CASES[0], result, [], [], True, ROWS, TODAY, TABLES, STORES)
    assert all(checks.values())
    result['steps'] = []
    checks, _ = grade(CASES[0], result, [], [], True, ROWS, TODAY, TABLES, STORES)
    assert not checks['executed_metric_result']


def test_only_enforced_managed_currency_constraint_is_equivalent():
    plan = dict(version=1, table_id=TABLES['pg'], operation='sum', column='amount',
                filters=[dict(column='currency', operator='=', value='KRW')])
    assert shape(plan, TABLES, STORES, actual=True) == shape(single(), TABLES, STORES)
    plan['table_id'] = TABLES['missing']
    assert shape(plan, TABLES, STORES, actual=True) != shape(single('missing'), TABLES, STORES)
