"""Explicit owner-scoped store selection; aggregate all selected stores in one snapshot."""
from datetime import datetime, timezone
from fastapi import HTTPException
from psycopg import sql
from . import db
from .config import settings
from .metric_definitions import MetricDefinition


def resolve_stores(project_id, user_id, definition, cur=None):
    from .dashboard_metrics import resolve_source
    if cur is None:
        with db._connect() as conn, conn.cursor() as cursor:
            return resolve_stores(project_id, user_id, definition, cursor)
    # Stable lock order. Ownership and active membership cannot change between
    # validation and execution. This transaction contains no model/network call.
    cur.execute("SELECT set_config('statement_timeout',%s,true)",(str(settings.query_timeout_ms),))
    ids = sorted({str(s.project_id) for s in definition.stores} | {str(project_id)})
    cur.execute('SELECT id,name FROM projects WHERE id=ANY(%s::uuid[]) AND user_id=%s AND deleted_at IS NULL ORDER BY id FOR SHARE', (ids, user_id))
    projects = {str(p['id']):p for p in cur.fetchall()}
    if len(projects) != len(ids):
        raise HTTPException(404, '선택한 가게를 확인할 수 없습니다. 삭제되었거나 접근할 수 없는 가게를 제외하고 정의를 다시 확인하세요.')
    table_ids = sorted(str(s.table_id) for store in definition.stores for s in store.sources)
    cur.execute('SELECT id FROM table_meta WHERE id=ANY(%s::uuid[]) AND user_id=%s AND deleted_at IS NULL ORDER BY id FOR SHARE', (table_ids, user_id))
    if len(cur.fetchall()) != len(table_ids):
        raise HTTPException(404, '선택한 장부를 확인할 수 없습니다. 출처가 없는 가게를 임의로 제외하지 않습니다.')
    result, files = [], set()
    for store in definition.stores:
        pid = str(store.project_id)
        metas = []
        for source in store.sources:
            single = MetricDefinition(table_id=source.table_id,column=source.column,date_column=source.date_column,time_range=definition.time_range,filters=source.filters)
            meta = resolve_source(pid,user_id,single,cur=cur)
            columns = {c['name']:c['type'].upper() for c in meta['columns_schema']}
            currency_column = source.currency_column or ('currency' if 'currency' in columns else None)
            if currency_column and (currency_column not in columns or not columns[currency_column].startswith(('TEXT','VARCHAR','CHAR'))):
                raise HTTPException(422,'통화 컬럼은 실제 문자 컬럼을 선택해주세요.')
            meta = {**meta,'currency_column':currency_column}
            fid = str(meta['source_file_id']) if meta.get('source_file_id') else None
            if fid and fid in files:
                raise HTTPException(422, '같은 원본 파일에서 만든 장부가 중복 선택되었습니다.')
            if fid: files.add(fid)
            metas.append(meta)
        result.append({'project_id':pid,'project_name':projects[pid]['name'],'tables':metas})
    return result


def compile_store_metric(user_id, definition, metas):
    from .dashboard_metrics import metric_identifier, compile_filters
    values, branches, params = [], [], []
    resolved = {str(t['id']):t for meta in metas for t in meta['tables']}
    for i, meta in enumerate(metas):
        values.append(sql.SQL('(%s::uuid,%s::text,%s::integer)'))
        params.extend([meta['project_id'],meta['project_name'],i])
    for store in definition.stores:
        for source in store.sources:
            amount = sql.SQL('{}::numeric').format(metric_identifier(source.column))
            if source.amount_mode == 'refund': amount = sql.SQL('-abs({})').format(amount)
            occurred = sql.SQL('{}::timestamp').format(metric_identifier(source.date_column)) if source.date_column else sql.SQL('NULL::timestamp')
            currency_column = resolved[str(source.table_id)]['currency_column']
            currency = sql.SQL('upper(trim({}::text))').format(metric_identifier(currency_column)) if currency_column else sql.SQL("'KRW'::text")
            conditions, args = compile_filters(source.filters)
            where = sql.SQL(' WHERE ')+sql.SQL(' AND ').join(conditions) if conditions else sql.SQL('')
            branches.append(sql.SQL('SELECT %s::uuid AS project_id,%s::uuid AS table_id,{} AS amount,{} AS occurred_at,{} AS currency FROM {}{}').format(
                amount,occurred,currency,metric_identifier(db.get_user_table_name(user_id,str(source.table_id))),where))
            params.extend([str(store.project_id),str(source.table_id),*args])
    bounds = {
        'all':'TRUE',
        'this_month':"occurred_at >= date_trunc('month',CURRENT_DATE) AND occurred_at < date_trunc('month',CURRENT_DATE)+interval '1 month'",
        'last_month':"occurred_at >= date_trunc('month',CURRENT_DATE)-interval '1 month' AND occurred_at < date_trunc('month',CURRENT_DATE)",
        'last_30_days':"occurred_at >= CURRENT_DATE-interval '29 days' AND occurred_at < CURRENT_DATE+interval '1 day'",
    }
    query = sql.SQL('''WITH chosen(project_id,project_name,ordinal) AS (VALUES {}),
        normalized AS MATERIALIZED ({}), selected AS (SELECT * FROM normalized WHERE {}),
        totals AS (SELECT project_id,sum(amount)::text AS value,count(*) AS included_rows FROM selected GROUP BY project_id),
        results AS (SELECT c.*,t.value,coalesce(t.included_rows,0) AS included_rows FROM chosen c LEFT JOIN totals t USING(project_id)),
        counts AS (SELECT table_id,count(*) n FROM selected GROUP BY table_id)
        SELECT (SELECT jsonb_agg(to_jsonb(r) ORDER BY r.ordinal) FROM results r) AS stores,
            (SELECT sum(amount)::text FROM selected) AS total,
            (SELECT count(*) FROM normalized WHERE amount IS NULL) AS missing_amounts,
            (SELECT count(*) FROM normalized WHERE amount::text IN ('NaN','Infinity','-Infinity')) AS invalid_amounts,
            (SELECT count(*) FROM normalized WHERE occurred_at IS NULL) AS missing_dates,
            (SELECT count(*) FROM normalized WHERE currency IS NULL OR currency <> 'KRW') AS invalid_currencies,
            coalesce((SELECT jsonb_object_agg(table_id,n) FROM counts),'{{}}'::jsonb) AS source_counts''').format(
                sql.SQL(',').join(values),sql.SQL(' UNION ALL ').join(branches),sql.SQL(bounds[definition.time_range]))
    return query,params


def calculate_store_metric(cur,user_id,definition,metas):
    from .dashboard_metrics import json_value
    query,params = compile_store_metric(user_id,definition,metas)
    cur.execute("SELECT set_config('statement_timeout',%s,true)",(str(settings.query_timeout_ms),))
    cur.execute("SELECT set_config('TimeZone','Asia/Seoul',true)")
    cur.execute(query,params); row = cur.fetchone()
    if row['invalid_currencies']:
        raise HTTPException(422,'원화가 아니거나 통화가 미제공인 거래가 있습니다. 통화가 다른 가게를 함께 합산하지 않습니다.')
    if row['missing_amounts'] or row['invalid_amounts']:
        raise HTTPException(422, '선택한 장부에 미제공 또는 비정상 금액이 있습니다. 일부 가게만으로 계산하지 않습니다.')
    if definition.time_range != 'all' and row['missing_dates']:
        raise HTTPException(422, '선택한 장부에 결제·취소 발생일이 없는 행이 있어 기간 비교를 중단했습니다.')
    stores = row['stores']
    empty = [s['project_name'] for s in stores if s['included_rows'] == 0]
    reason = '선택 기간의 거래가 없는 가게: '+', '.join(empty)+'. 전체 합계를 확정할 수 없습니다.' if empty else None
    sources = []
    for store,meta in zip(definition.stores,metas):
        for source,table in zip(store.sources,meta['tables']):
            sources.append({'project_id':str(store.project_id),'project_name':meta['project_name'],
                'table_id':str(source.table_id),'table_name':table['name'],'label':source.label,
                'column':source.column,'date_column':source.date_column,'amount_mode':source.amount_mode,'currency_column':table['currency_column'],
                'filters':[f.model_dump(mode='json') for f in source.filters],
                'included_rows':row['source_counts'].get(str(source.table_id),0),'source_updated_at':json_value(table.get('updated_at'))})
    data = [{'dimension':s['project_name'],'project_id':s['project_id'],'value':s['value'],
             'included_rows':s['included_rows'],'undefined_reason':'선택 기간의 거래가 없습니다.' if not s['included_rows'] else None} for s in stores]
    result = {'metric_definition':definition.model_dump(mode='json'),'scope':'selected_stores','unit':'KRW','currency':'KRW',
        'stores':stores,'sources':sources,'source_table_name':' / '.join(f"{m['project_name']} ({', '.join(t['name'] for t in m['tables'])})" for m in metas),
        'period_label':{'all':'전체 기간','this_month':'이번 달','last_month':'지난달','last_30_days':'최근 30일'}[definition.time_range],
        'calculation_label':'선택 가게의 원화 순결제액 · 승인·취소 발생일 기준 · 수수료 차감 전',
        'label':'선택 가게 순결제액','dimension_label':'가게','calculated_at':datetime.now(timezone.utc).isoformat(),'refresh_error':None,
        'point_count':len(stores),'undefined_groups':len(empty),'store_data':data,
        'warnings':['선택한 장부만 집계합니다. 다른 장부·가게에 중복 기록된 거래와 내부 이체는 자동으로 제거하지 않습니다. 결제 원금과 정산 입금액을 함께 넣지 마세요.'],
        'execution':{'sql':query.as_string(),'parameters':params,'timezone':'Asia/Seoul','dialect':'PostgreSQL','parameterized':True}}
    if definition.group_by == 'store': result.update(chart_type='bar',x_key='dimension',y_key='value',data=data)
    else: result.update(value=None if empty else row['total'],formatted='계산 불가' if empty else f"{row['total']}원",undefined_reason=reason)
    return result
