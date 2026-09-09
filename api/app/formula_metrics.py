"""Two scalar aggregates, one SQL snapshot, fixed Decimal arithmetic."""
from datetime import datetime, timezone
from .formula_math import evaluate, result_unit, calculation_label

from fastapi import HTTPException
from psycopg import sql

from .config import settings
from .db import get_user_table_name


def resolve_formula(project_id, user_id, definition, cur=None):
    from .dashboard_metrics import resolve_source
    return [resolve_source(project_id, user_id, operand.definition, cur=cur)
            for operand in [definition.left, definition.right]]


def calculate_formula(cur, user_id, definition, metas):
    from .dashboard_metrics import compile_metric, json_value
    operands = [definition.left, definition.right]
    compiled = [compile_metric(get_user_table_name(user_id, str(m['id'])), o.definition) for o, m in zip(operands, metas)]
    missing = [sql.SQL('0') if o.definition.operation == 'count' else sql.SQL(alias+'.missing_values')
               for o, alias in zip(operands, ['l', 'r'])]
    query = sql.SQL('''WITH l AS ({}), r AS ({})
        SELECT l.value::numeric AS left_value,r.value::numeric AS right_value,
               {} AS left_missing,{} AS right_missing FROM l CROSS JOIN r''').format(
        compiled[0][0], compiled[1][0], *missing)
    cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
    cur.execute("SELECT set_config('TimeZone','Asia/Seoul',true)")
    cur.execute(query, compiled[0][1]+compiled[1][1])
    row = cur.fetchone()
    for side, operand in zip(['left', 'right'], operands):
        if row[side+'_missing']:
            raise HTTPException(422, f"{operand.label}: 미제공 값 {row[side+'_missing']}건이 있어 계산을 중단했습니다.")
    values, value, reason = evaluate(definition, row['left_value'], row['right_value'])
    unit = result_unit(definition)
    calculation = calculation_label(definition)
    formatted = '계산 불가' if value is None else format(value, ',f')
    if value is not None:
        if '.' in formatted:
            formatted = formatted.rstrip('0').rstrip('.')
        formatted += {'KRW':'원','count':'건','percent':'%'}.get(unit, '')
    periods = {'all':'전체 기간','this_month':'이번 달','last_month':'지난달','last_30_days':'최근 30일'}
    return {
        'metric_definition': definition.model_dump(mode='json'), 'value': json_value(value), 'formatted': formatted,
        'unit': unit, 'undefined_reason': reason, 'calculated_at': datetime.now(timezone.utc).isoformat(), 'refresh_error': None,
        'calculation_label': calculation, 'label': calculation,
        'source_table_name': ' / '.join(dict.fromkeys(m['name'] for m in metas)),
        'period_label': ' / '.join(dict.fromkeys(periods[o.definition.time_range] for o in operands)),
        'formula_operands': [{'label': o.label,'table_id': str(o.definition.table_id),'table_name': m['name'],
            'value': json_value(v),'unit':o.unit,'absolute':o.absolute,'period_label': periods[o.definition.time_range],
            'column':o.definition.column,'date_column':o.definition.date_column,'operation':o.definition.operation,'filters':[f.model_dump(mode='json') for f in o.definition.filters],
            'source_updated_at':json_value(m.get('updated_at'))} for o,m,v in zip(operands,metas,values)],
        'execution': {'sql':query.as_string(),'parameters':compiled[0][1]+compiled[1][1],'timezone':'Asia/Seoul','dialect':'PostgreSQL','parameterized':True},
        'warnings': ['각 항목은 저장한 기간·필터로 계산합니다. 이번 달과 지난달은 각 달 전체 범위이며 이번 달은 아직 마감되지 않았을 수 있습니다.']
                    if definition.operation == 'percent_change' else [],
    }
