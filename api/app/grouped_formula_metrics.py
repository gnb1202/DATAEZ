"""Aggregate first, align exact dimensions via UNION ALL, evaluate per group."""
from datetime import datetime, timezone
from fastapi import HTTPException
from psycopg import sql

from .config import settings
from .db import get_user_table_name
from .formula_math import evaluate, result_unit, calculation_label


def resolve_grouped_formula(project_id, user_id, definition, cur=None):
    from .dashboard_metrics import resolve_source
    operands = [definition.left, definition.right]
    metas = [resolve_source(project_id, user_id, operand.definition, cur=cur) for operand in operands]
    for operand, meta in zip(operands, metas):
        dtype = next(c['type'].upper() for c in meta['columns_schema'] if c['name'] == operand.definition.group_by)
        if operand.definition.date_grain:
            continue  # resolve_source validated a DATE/TIMESTAMP column.
        if dtype not in ('TEXT', 'VARCHAR', 'CHARACTER VARYING', 'CHAR', 'CHARACTER') and not dtype.startswith(('VARCHAR(', 'CHARACTER VARYING(', 'CHAR(', 'CHARACTER(')):
            raise HTTPException(422, '그룹별 계산식은 문자 분류 또는 일·주·월 단위를 지정한 날짜 컬럼을 사용합니다.')
    return metas


def compile_grouped_formula(user_id, definition, metas):
    from .dashboard_metrics import compile_metric, MAX_GROUPS
    operands = [definition.left, definition.right]
    queries = [compile_metric(get_user_table_name(user_id, str(meta['id'])), operand.definition) for meta, operand in zip(metas, operands)]
    missing = [sql.SQL('0') if operand.definition.operation == 'count' else sql.SQL('missing_values') for operand in operands]
    # Never join raw transactions: N payments and M fees in one group must not
    # multiply either total. GROUP BY also aligns NULL classification safely.
    query = sql.SQL('''WITH left_groups AS ({}), right_groups AS ({}), combined AS (
        SELECT dimension, value::numeric AS left_value, NULL::numeric AS right_value,
               {} AS left_missing, 0::bigint AS right_missing, true AS left_present, false AS right_present FROM left_groups
        UNION ALL
        SELECT dimension, NULL::numeric, value::numeric, 0::bigint, {}, false, true FROM right_groups
    ) SELECT dimension, max(left_value) AS left_value, max(right_value) AS right_value,
        sum(left_missing) AS left_missing, sum(right_missing) AS right_missing,
        bool_or(left_present) AS left_present, bool_or(right_present) AS right_present
      FROM combined GROUP BY dimension ORDER BY dimension NULLS LAST LIMIT %s''').format(queries[0][0], queries[1][0], *missing)
    return query, queries[0][1]+queries[1][1]+[MAX_GROUPS+1]


def calculate_grouped_formula(cur, user_id, definition, metas):
    from .dashboard_metrics import MAX_GROUPS, json_value
    query, params = compile_grouped_formula(user_id, definition, metas)
    cur.execute("SELECT set_config('statement_timeout',%s,true)", (str(settings.query_timeout_ms),))
    cur.execute("SELECT set_config('TimeZone','Asia/Seoul',true)")
    cur.execute(query, params)
    rows = cur.fetchall()
    if len(rows) > MAX_GROUPS:
        raise HTTPException(422, '그룹이 1,000개를 초과합니다. 기간을 줄이거나 더 큰 날짜 단위를 선택해주세요.')
    data = []
    for row in rows:
        for side, operand in [('left', definition.left), ('right', definition.right)]:
            if row[side+'_missing']:
                raise HTTPException(422, f"{operand.label}: 미제공 숫자가 있는 그룹이 있어 계산을 중단했습니다. 빈 그룹과 숫자 NULL은 다릅니다.")
        missing_sides = [side for side in ['left', 'right'] if not row[side+'_present']]
        values = [0 if side in missing_sides and definition.missing_group == 'zero' else row[side+'_value'] for side in ['left', 'right']]
        values, value, reason = evaluate(definition, *values)
        if missing_sides and definition.missing_group == 'undefined':
            reason = ' / '.join(getattr(definition, side).label for side in missing_sides)+'에 해당 그룹의 거래가 없습니다.'
        data.append({'dimension':json_value(row['dimension']), 'value':json_value(value),
            'left_value':json_value(values[0]), 'right_value':json_value(values[1]), 'undefined_reason':reason,
            'zero_filled':missing_sides if definition.missing_group == 'zero' else []})
    periods = {'all':'전체 기간','this_month':'이번 달','last_month':'지난달','last_30_days':'최근 30일'}
    operands = [definition.left, definition.right]
    warnings = ['양쪽 집계에 모두 없는 날짜·분류는 생성하지 않습니다.']
    if definition.missing_group == 'zero':
        warnings.append('한쪽에 거래가 없는 그룹은 저장된 설정에 따라 0으로 계산합니다. 미제공 숫자는 0으로 바꾸지 않습니다.')
    if definition.operation == 'percent_change' and any(o.definition.time_range == 'this_month' for o in operands):
        warnings.append('이번 달은 아직 마감되지 않았을 수 있습니다. 각 항목은 저장한 기간 전체를 사용합니다.')
    return {'metric_definition':definition.model_dump(mode='json'), 'chart_type':definition.chart_type,
        'x_key':'dimension','y_key':'value','data':data,'unit':result_unit(definition),
        'calculation_label':calculation_label(definition),'label':calculation_label(definition),
        'dimension_label':definition.dimension_label,'date_grain':definition.left.definition.date_grain,
        'period_label':' / '.join(dict.fromkeys(periods[o.definition.time_range] for o in operands)),
        'source_table_name':' / '.join(dict.fromkeys(m['name'] for m in metas)),
        'calculated_at':datetime.now(timezone.utc).isoformat(),'refresh_error':None,
        'point_count':len(data),'undefined_groups':sum(r['value'] is None for r in data),'warnings':warnings,
        'formula_operands':[{'label':o.label,'table_id':str(o.definition.table_id),'table_name':m['name'],
            'unit':o.unit,'absolute':o.absolute,'period_label':periods[o.definition.time_range],
            'column':o.definition.column,'date_column':o.definition.date_column,'operation':o.definition.operation,
            'group_by':o.definition.group_by,'date_grain':o.definition.date_grain,
            'filters':[f.model_dump(mode='json') for f in o.definition.filters],'source_updated_at':json_value(m.get('updated_at'))}
            for o,m in zip(operands,metas)],
        'execution':{'sql':query.as_string(),'parameters':[json_value(v) for v in params],
            'timezone':'Asia/Seoul','dialect':'PostgreSQL','parameterized':True}}
