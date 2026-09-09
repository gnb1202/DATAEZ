"""Normalize disjoint payment-event ledgers and aggregate in ONE DB snapshot.

No joins between transaction ledgers: UNION ALL avoids multiplying payments.
The explicit source mapping is persisted, never rediscovered at refresh time.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg import sql

from .config import settings
from .db import get_user_table_name
from .metric_definitions import MetricDefinition, MultiMetricDefinition


def resolve_sources(project_id: str, user_id: str, definition: MultiMetricDefinition, cur=None):
    from .dashboard_metrics import resolve_source
    metas = []
    file_ids = set()
    for source in definition.sources:
        single = MetricDefinition(table_id=source.table_id, column=source.column,
                                  date_column=source.date_column, time_range=definition.time_range,
                                  filters=source.filters)
        meta = resolve_source(project_id, user_id, single, cur=cur)
        fid = str(meta.get("original_file_id") or meta.get("source_file_id") or "") or None
        if fid and fid in file_ids:
            raise HTTPException(422, "같은 원본 파일에서 만든 장부가 중복 선택되었습니다. 출처를 확인해주세요.")
        if fid:
            file_ids.add(fid)
        metas.append(meta)
    return metas


def compile_multi(user_id: str, definition: MultiMetricDefinition):
    from .dashboard_metrics import MAX_GROUPS, metric_identifier, compile_filters
    branches = []
    params = []
    for source in definition.sources:
        amount = sql.SQL("{}::numeric").format(metric_identifier(source.column))
        if source.amount_mode == "refund":
            amount = sql.SQL("-abs({})").format(amount)
        occurred = sql.SQL("{}::timestamp").format(metric_identifier(source.date_column)) if source.date_column else sql.SQL("NULL::timestamp")
        conditions, filter_params = compile_filters(source.filters)
        where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
        branches.append(sql.SQL("SELECT {} AS amount, {} AS occurred_at, %s::text AS source FROM {}{}").format(
            amount, occurred, metric_identifier(get_user_table_name(user_id, str(source.table_id))), where))
        params.append(source.label)
        params.extend(filter_params)

    bounds = {
        "all": "TRUE",
        "this_month": "occurred_at >= date_trunc('month',CURRENT_DATE) AND occurred_at < date_trunc('month',CURRENT_DATE) + interval '1 month'",
        "last_month": "occurred_at >= date_trunc('month',CURRENT_DATE) - interval '1 month' AND occurred_at < date_trunc('month',CURRENT_DATE)",
        "last_30_days": "occurred_at >= CURRENT_DATE - interval '29 days' AND occurred_at < CURRENT_DATE + interval '1 day'",
    }
    if definition.group_by == "date":
        dimension = sql.SQL("date_trunc(%s, occurred_at)::date")
        params.append(definition.date_grain)
    else:
        dimension = sql.SQL("source")
    if definition.group_by == "none":
        aggregate = sql.SQL("SELECT sum(amount)::text AS value FROM selected")
    else:
        aggregate = sql.SQL("SELECT {} AS dimension, sum(amount)::text AS value FROM selected GROUP BY 1 ORDER BY 1 LIMIT %s").format(dimension)
        params.append(MAX_GROUPS + 1)
    # Materialization makes quality, counts and totals use exactly the same
    # source rows, even if another transaction imports data concurrently.
    result_order = sql.SQL(" ORDER BY r.dimension") if definition.group_by != "none" else sql.SQL("")
    query = sql.SQL("""WITH normalized AS MATERIALIZED ({}),
        selected AS (SELECT * FROM normalized WHERE {}),
        results AS ({}),
        source_counts AS (SELECT source, count(*) AS n FROM selected GROUP BY source)
        SELECT (SELECT count(*) FROM normalized WHERE amount IS NULL) AS missing_amounts,
               (SELECT count(*) FROM normalized WHERE amount::text IN ('NaN', 'Infinity', '-Infinity')) AS invalid_amounts,
               (SELECT count(*) FROM normalized WHERE occurred_at IS NULL) AS missing_dates,
               coalesce((SELECT jsonb_agg(to_jsonb(r){}) FROM results r), '[]'::jsonb) AS data,
               coalesce((SELECT jsonb_object_agg(source,n) FROM source_counts), '{{}}'::jsonb) AS source_counts
    """).format(sql.SQL(" UNION ALL ").join(branches), sql.SQL(bounds[definition.time_range]), aggregate, result_order)
    return query, params


def calculate_multi(cur, user_id: str, definition: MultiMetricDefinition, metas: list[dict]):
    from .dashboard_metrics import MAX_GROUPS, json_value
    cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(settings.query_timeout_ms),))
    cur.execute("SELECT set_config('TimeZone', 'Asia/Seoul', true)")
    query, params = compile_multi(user_id, definition)
    cur.execute(query, params)
    row = cur.fetchone()
    if row["missing_amounts"]:
        raise HTTPException(422, f"금액이 비어 있는 행 {row['missing_amounts']}건이 있습니다. 원본 장부를 수정해주세요.")
    if row["invalid_amounts"]:
        raise HTTPException(422, "정상적인 숫자가 아닌 금액이 있습니다. 원본 장부를 수정해주세요.")
    if (definition.group_by == "date" or definition.time_range != "all") and row["missing_dates"]:
        raise HTTPException(422, f"날짜가 비어 있는 행 {row['missing_dates']}건이 있습니다. 기간 누락을 막기 위해 계산을 중단했습니다.")
    if len(row["data"]) > MAX_GROUPS:
        raise HTTPException(422, "그룹이 1,000개를 초과합니다. 더 큰 날짜 단위를 선택해주세요.")
    sources = [{"table_id": str(s.table_id), "table_name": m["name"], "label": s.label,
                "column": s.column, "date_column": s.date_column, "amount_mode": s.amount_mode,
                "filters": [f.model_dump(mode="json") for f in s.filters],
                "included_rows": row["source_counts"].get(s.label, 0), "source_updated_at": json_value(m.get("updated_at"))}
               for s, m in zip(definition.sources, metas)]
    result = {
        "execution": {"sql": query.as_string(), "parameters": [json_value(v) for v in params], "timezone": "Asia/Seoul", "dialect": "PostgreSQL", "parameterized": True},
        "metric_definition": definition.model_dump(mode="json"), "calculated_at": datetime.now(timezone.utc).isoformat(),
        "source_table_name": " + ".join(m["name"] for m in metas), "sources": sources,
        "refresh_error": None, "currency": "KRW",
        "period_label": {"all": "전체 기간", "this_month": "이번 달", "last_month": "지난달", "last_30_days": "최근 30일"}[definition.time_range],
        "label": "통합 결제액 (원)", "calculation_label": "원화 결제 이벤트 합계 · 취소 장부는 차감",
        "warnings": ["서로 다른 출처(장부) 사이의 중복 거래는 이 집계에서 추가 제거하지 않습니다. 관리 출처 내부의 업로드 중복 검증과는 별개입니다. 결제 원금과 정산 입금액을 함께 합산하지 마세요."],
    }
    if definition.group_by == "none":
        value = row["data"][0]["value"]
        result.update(value=value, formatted="데이터 없음" if value is None else f"{value}원")
    else:
        result.update(chart_type=definition.chart_type, x_key="dimension", y_key="value", data=row["data"])
    return result
