"""Store-scoped, persisted metric definitions. No generated SQL is accepted.

Versioned definitions are stored alongside widgets, keeping old static widgets
intact. Every execution revalidates both store ownership and source membership.
"""

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg import sql

from .metric_definitions import MetricDefinition, MetricFilter, MultiMetricDefinition, FormulaMetricDefinition, GroupedFormulaMetricDefinition, MultiStoreMetricDefinition, DashboardMetricDefinition, parse_metric_definition
from .auth import get_current_user
from .config import settings
from .db import _connect, get_project, get_table_meta, get_user_table_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}/metrics", tags=["dashboard"])
MAX_GROUPS = 1000
RefreshInterval = Literal[0, 3600, 86400]


class CreateMetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    save_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{1,120}$")
    title: str = Field(min_length=1, max_length=120)
    definition: DashboardMetricDefinition
    refresh_interval_seconds: RefreshInterval = 0


class MetricScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_interval_seconds: RefreshInterval


class PreviewMetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: DashboardMetricDefinition


def owned_store(project_id: str, user_id: str):
    if not get_project(project_id, user_id):
        raise HTTPException(404, "가게를 찾을 수 없습니다.")


def resolve_source(project_id: str, user_id: str, definition: MetricDefinition, cur=None):
    if cur is None:
        meta = get_table_meta(str(definition.table_id), user_id)
    else:
        # Refresh already holds a connection/row lock. Reusing it avoids pool
        # exhaustion when many workers would otherwise request a second one.
        cur.execute("SELECT * FROM table_meta WHERE id=%s AND user_id=%s AND deleted_at IS NULL",
                    (str(definition.table_id), user_id))
        meta = cur.fetchone()
    if not meta or str(meta["project_id"]) != project_id:
        raise HTTPException(404, "선택한 가게의 장부를 찾을 수 없습니다.")
    columns = {c["name"]: c["type"].upper() for c in meta["columns_schema"]}
    for name in (definition.column, definition.group_by, definition.date_column, *(f.column for f in definition.filters)):
        if name is not None and name not in columns:
            raise HTTPException(422, f"컬럼이 변경되었거나 없습니다: {name}")
    if definition.operation != "count":
        dtype = columns[definition.column]
        if not dtype.startswith(("NUMERIC", "DECIMAL", "BIGINT", "INTEGER", "SMALLINT", "REAL", "DOUBLE", "INT")):
            raise HTTPException(422, "합계·평균·최솟값·최댓값은 숫자 컬럼에만 사용할 수 있습니다.")
    if definition.date_grain and not columns[definition.group_by].startswith(("DATE", "TIMESTAMP")):
        raise HTTPException(422, "날짜 단위는 날짜 컬럼에만 사용할 수 있습니다.")
    if definition.date_column and not columns[definition.date_column].startswith(("DATE", "TIMESTAMP")):
        raise HTTPException(422, "기간 필터에는 날짜 컬럼을 선택해주세요.")
    return meta


def metric_identifier(name: str):
    # execute(query, params) parses percent placeholders even inside identifiers.
    # Double literal percent signs for that driver pass, after which PostgreSQL
    # sees the original quoted column/table name. Always pass params (even []).
    return sql.Identifier(name.replace("%", "%%"))


def compile_filters(filters):
    conditions, params = [], []
    for item in filters:
        if item.operator in {"is_null", "is_not_null"}:
            conditions.append(sql.SQL("{} {}").format(metric_identifier(item.column),
                sql.SQL("IS NULL" if item.operator == "is_null" else "IS NOT NULL")))
        else:
            conditions.append(sql.SQL("{} {} %s").format(metric_identifier(item.column), sql.SQL(item.operator)))
            params.append(item.value)
    return conditions, params


def compile_metric(table_name: str, definition: MetricDefinition):
    """Quoted identifiers and an allowlisted grammar; aggregate before limiting."""
    value = sql.SQL("*") if definition.operation == "count" else metric_identifier(definition.column)
    aggregate = sql.SQL("{}({})").format(sql.SQL(definition.operation.upper()), value)
    params: list = []
    conditions, filter_params = compile_filters(definition.filters)
    quality = sql.SQL("") if definition.operation == "count" else sql.SQL(
        ", COUNT(*) FILTER (WHERE {} IS NULL) AS missing_values").format(value)
    # Expressions are fixed server constants. Dates are evaluated by PostgreSQL
    # in the store timezone on EVERY run, including month boundaries.
    bounds = {
        "this_month": ("date_trunc('month', CURRENT_DATE)", "date_trunc('month', CURRENT_DATE) + interval '1 month'"),
        "last_month": ("date_trunc('month', CURRENT_DATE) - interval '1 month'", "date_trunc('month', CURRENT_DATE)"),
        "last_30_days": ("CURRENT_DATE - interval '29 days'", "CURRENT_DATE + interval '1 day'"),
    }
    if definition.time_range in bounds:
        start, end = bounds[definition.time_range]
        col = metric_identifier(definition.date_column)
        conditions.append(sql.SQL("{} >= {} AND {} < {}").format(col, sql.SQL(start), col, sql.SQL(end)))
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
    if definition.group_by:
        group = metric_identifier(definition.group_by)
        if definition.date_grain:
            group = sql.SQL("date_trunc(%s, {})::date").format(group)
            params.append(definition.date_grain)
        query = sql.SQL(
            "SELECT {} AS dimension, {} AS value{} FROM {}{} "
            "GROUP BY 1 ORDER BY 1 NULLS LAST LIMIT %s"
        ).format(group, aggregate, quality, metric_identifier(table_name), where)
        params.extend(filter_params)
        params.append(MAX_GROUPS + 1)
    else:
        query = sql.SQL("SELECT {} AS value{} FROM {}{}").format(aggregate, quality, metric_identifier(table_name), where)
        params.extend(filter_params)
    return query, params


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)  # Preserve money precision in storage and transport.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def calculate(cur, user_id: str, definition: DashboardMetricDefinition, meta: dict | list[dict]):
    from .file_snapshots import source_scope
    result = _calculate(cur, user_id, definition, meta)
    sources = {}
    def visit(node):
        if isinstance(node, list):
            for item in node: visit(item)
        elif isinstance(node, dict):
            if node.get('id') and 'columns_schema' in node:
                sources[str(node['id'])] = {'table_id':str(node['id']), 'table_name':node['name'], **source_scope(node)}
            else:
                for item in node.values(): visit(item)
    visit(meta)
    if sources:
        result['analysis_sources'] = list(sources.values())
        result['scope_label'] = ' · '.join(dict.fromkeys(s['scope_label'] for s in sources.values()))
        result['refresh_note'] = ' '.join(dict.fromkeys(s['refresh_note'] for s in sources.values()))
    return result


def _calculate(cur, user_id: str, definition: DashboardMetricDefinition, meta: dict | list[dict]):
    if isinstance(definition, MultiStoreMetricDefinition):
        from .store_metrics import calculate_store_metric
        return calculate_store_metric(cur, user_id, definition, meta)
    if isinstance(definition, GroupedFormulaMetricDefinition):
        from .grouped_formula_metrics import calculate_grouped_formula
        return calculate_grouped_formula(cur, user_id, definition, meta)
    if isinstance(definition, FormulaMetricDefinition):
        from .formula_metrics import calculate_formula
        return calculate_formula(cur, user_id, definition, meta)
    if isinstance(definition, MultiMetricDefinition):
        from .multi_metrics import calculate_multi
        return calculate_multi(cur, user_id, definition, meta)
    cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(settings.query_timeout_ms),))
    cur.execute("SELECT set_config('TimeZone', 'Asia/Seoul', true)")
    query, params = compile_metric(get_user_table_name(user_id, str(meta["id"])), definition)
    cur.execute(query, params)
    rows = cur.fetchall()
    if len(rows) > MAX_GROUPS:
        raise HTTPException(422, "그룹이 1,000개를 초과합니다. 더 큰 날짜 단위를 선택해주세요.")
    missing = sum(row.get("missing_values", 0) for row in rows)
    if missing:
        raise HTTPException(422, f"{definition.column} 값이 미제공인 행 {missing}건이 있어 계산을 중단했습니다. "
                            "빈칸은 0이 아닙니다. 미제공 건수를 확인하거나, 제공된 값만 계산하려면 해당 범위를 명시해주세요.")
    data = [{k: json_value(v) for k, v in row.items() if k != "missing_values"} for row in rows]
    result = {
        "execution": {"sql": query.as_string(), "parameters": params, "timezone": "Asia/Seoul", "dialect": "PostgreSQL", "parameterized": True},
        "metric_definition": definition.model_dump(mode="json"),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "source_table_name": meta["name"],
        "source_updated_at": json_value(meta.get("updated_at")),
        "refresh_error": None,
        "period_label": {"all": "전체 기간", "this_month": "이번 달", "last_month": "지난달", "last_30_days": "최근 30일"}[definition.time_range],
        "label": f"{meta['name']} · {definition.operation}",
        "calculation_label": {"sum": "합계", "count": "행 건수", "avg": "평균", "min": "최솟값", "max": "최댓값"}[definition.operation]
            + (f" ({definition.column})" if definition.operation != "count" else "")
            + (" · " + ", ".join(f"{f.column} " + ({"is_null": "미제공", "is_not_null": "제공됨"}.get(f.operator)
                                or f"{f.operator} {f.value}") for f in definition.filters) if definition.filters else ""),
    }
    if definition.unit:
        result['unit'] = definition.unit
    elif definition.operation == 'count':
        result['unit'] = 'count'
    result['suggested_title'] = (meta['name'][:65] + ' · ' + {'sum':'합계','count':'건수','avg':'평균','min':'최솟값','max':'최댓값'}[definition.operation]
        + (' · ' + {'day':'일별','week':'주별','month':'월별'}.get(definition.date_grain, definition.group_by or '') if definition.group_by else ''))[:120]
    if definition.group_by:
        result.update(chart_type=definition.chart_type, x_key="dimension", y_key="value", data=data)
    else:
        value = data[0]["value"] if data else None
        result.update(value=value, formatted="데이터 없음" if value is None else str(value))
    return result


def resolve_definition(project_id: str, user_id: str, definition: DashboardMetricDefinition, cur=None):
    if isinstance(definition, MultiStoreMetricDefinition):
        from .store_metrics import resolve_stores
        return resolve_stores(project_id, user_id, definition, cur=cur)
    if isinstance(definition, GroupedFormulaMetricDefinition):
        from .grouped_formula_metrics import resolve_grouped_formula
        return resolve_grouped_formula(project_id, user_id, definition, cur=cur)
    if isinstance(definition, FormulaMetricDefinition):
        from .formula_metrics import resolve_formula
        return resolve_formula(project_id, user_id, definition, cur=cur)
    if isinstance(definition, MultiMetricDefinition):
        from .multi_metrics import resolve_sources
        return resolve_sources(project_id, user_id, definition, cur=cur)
    return resolve_source(project_id, user_id, definition, cur=cur)


def has_groups(definition: DashboardMetricDefinition):
    if isinstance(definition, MultiStoreMetricDefinition):
        return definition.group_by == "store"
    if isinstance(definition, GroupedFormulaMetricDefinition):
        return True
    if isinstance(definition, FormulaMetricDefinition):
        return False
    return definition.group_by != "none" if isinstance(definition, MultiMetricDefinition) else bool(definition.group_by)


def preview_saved_metric(project_id: str, user_id: str, definition: DashboardMetricDefinition):
    owned_store(project_id, user_id)
    meta = None if isinstance(definition, MultiStoreMetricDefinition) else resolve_definition(project_id, user_id, definition)
    try:
        with _connect() as conn, conn.cursor() as cur:
            if isinstance(definition, MultiStoreMetricDefinition):
                meta = resolve_definition(project_id, user_id, definition, cur=cur)
            return calculate(cur, user_id, definition, meta)
    except psycopg.Error:
        raise HTTPException(422, "미리보기를 계산하지 못했습니다. 컬럼과 필터 값 형식을 확인해주세요.") from None


def create_saved_metric(project_id: str, user_id: str, body: CreateMetricRequest):
    pid = str(project_id)
    owned_store(pid, user_id)
    from .widget_saves import fingerprint, replay, record
    digest = fingerprint(body.model_dump(mode="json", exclude={"save_key"})) if body.save_key else None
    meta = None if body.save_key or isinstance(body.definition, MultiStoreMetricDefinition) else resolve_definition(pid, user_id, body.definition)
    wid = str(uuid4())
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                existing = replay(cur, user_id, pid, body.save_key, digest)
                if existing:
                    return {"id": str(existing["id"]), "widget_data": existing["widget_data"], "refresh_interval_seconds": existing["refresh_interval_seconds"], "save_key": body.save_key}
                if body.save_key or isinstance(body.definition, MultiStoreMetricDefinition):
                    meta = resolve_definition(pid, user_id, body.definition, cur=cur)
                result = calculate(cur, user_id, body.definition, meta)
                cur.execute(
                    """INSERT INTO dashboard_widgets
                    (id, user_id, project_id, widget_type, title, widget_data, layout,
                     refresh_interval_seconds, next_refresh_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
                            CASE WHEN %s > 0 THEN now() + %s * interval '1 second' ELSE NULL END)""",
                    (wid, user_id, pid, "chart" if has_groups(body.definition) else "kpi",
                     body.title, json.dumps(result, ensure_ascii=False), json.dumps({"x": 0, "y": 0, "w": 6, "h": 7 if has_groups(body.definition) else 5}),
                     body.refresh_interval_seconds, body.refresh_interval_seconds, body.refresh_interval_seconds),
                )
                record(cur, wid, body.save_key, digest)
            conn.commit()
    except psycopg.Error:
        logger.exception("Metric creation failed")
        raise HTTPException(422, "지표를 계산하지 못했습니다. 장부 구조와 데이터 형식을 확인해주세요.") from None
    return {"id": wid, "widget_data": result, "refresh_interval_seconds": body.refresh_interval_seconds}


@router.post("", status_code=201)
def create_metric(project_id: UUID, body: CreateMetricRequest, user: dict = Depends(get_current_user)):
    return create_saved_metric(str(project_id), user["id"], body)


@router.post("/preview")
def preview_metric(project_id: UUID, body: PreviewMetricRequest, user: dict = Depends(get_current_user)):
    return preview_saved_metric(str(project_id), user["id"], body.definition)


def refresh_locked(conn, cur, row: dict, metric_id: str, user_id: str, project_id: str):
    """The caller must hold the widget row lock until this transaction commits."""
    result = dict(row["widget_data"])
    failure = None
    try:
        with conn.transaction():
            definition = parse_metric_definition(result["metric_definition"])
            meta = resolve_definition(project_id, user_id, definition, cur=cur)
            result = calculate(cur, user_id, definition, meta)
            result["definition_revision"] = row["widget_data"].get("definition_revision", 1)
    except (HTTPException, ValueError, psycopg.Error) as exc:
        failure = str(exc.detail) if isinstance(exc, HTTPException) else "계산에 실패했습니다. 장부와 지표 정의를 확인해주세요."
        result["refresh_error"] = failure
        result["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
    interval = row.get("refresh_interval_seconds") or 0
    failures = (row.get("refresh_failures") or 0) + 1 if failure else 0
    # Two bounded retries (60s, 120s), then pause until user action. A successful
    # manual refresh or changing the schedule resumes it.
    delay = min(interval, 60 * 2 ** min(failures - 1, 6)) if failure and interval else interval
    delay = delay if interval and failures < 3 else 0
    cur.execute(
        """UPDATE dashboard_widgets SET widget_data=%s::jsonb, refresh_failures=%s,
        next_refresh_at=CASE WHEN %s > 0 THEN now() + %s * interval '1 second' ELSE NULL END
        WHERE id=%s AND user_id=%s AND project_id=%s""",
        (json.dumps(result, ensure_ascii=False), failures, delay, delay, metric_id, user_id, project_id),
    )
    return result, failure


@router.post("/{metric_id}/refresh")
def refresh_metric(project_id: UUID, metric_id: UUID, user: dict = Depends(get_current_user)):
    pid = str(project_id)
    owned_store(pid, user["id"])
    failure = None
    with _connect() as conn:
        with conn.cursor() as cur:
            # Serialize refreshes and deletion; never replace a newer result with
            # a calculation that started before it.
            cur.execute(
                "SELECT widget_data, refresh_interval_seconds, refresh_failures FROM dashboard_widgets WHERE id=%s AND user_id=%s AND project_id=%s FOR UPDATE",
                (str(metric_id), user["id"], pid),
            )
            row = cur.fetchone()
            if not row or "metric_definition" not in row["widget_data"]:
                raise HTTPException(404, "갱신 가능한 지표를 찾을 수 없습니다.")
            result, failure = refresh_locked(conn, cur, row, str(metric_id), user["id"], pid)
        conn.commit()
    if failure:
        raise HTTPException(422, failure)
    return {"id": str(metric_id), "widget_data": result}


def list_saved_metrics(project_id: str, user_id: str):
    owned_store(project_id, user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, title, widget_data->'metric_definition' AS definition,
                    coalesce((widget_data->>'definition_revision')::integer,1) AS definition_revision,
                    refresh_interval_seconds, next_refresh_at, refresh_failures
                    FROM dashboard_widgets WHERE user_id=%s AND project_id=%s
                    AND widget_data ? 'metric_definition' ORDER BY created_at DESC LIMIT 100""", (user_id, project_id))
        return [dict(r, id=str(r["id"]), next_refresh_at=json_value(r["next_refresh_at"])) for r in cur.fetchall()]


def set_saved_metric_schedule(project_id: str, user_id: str, metric_id: str, interval: RefreshInterval):
    interval = MetricScheduleRequest(refresh_interval_seconds=interval).refresh_interval_seconds
    owned_store(project_id, user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE dashboard_widgets SET refresh_interval_seconds=%s, refresh_failures=0,
                    next_refresh_at=CASE WHEN %s > 0 THEN now() + %s * interval '1 second' ELSE NULL END
                    WHERE id=%s AND user_id=%s AND project_id=%s AND widget_data ? 'metric_definition'
                    RETURNING id, refresh_interval_seconds, next_refresh_at""",
                    (interval, interval, interval, metric_id, user_id, project_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "갱신 가능한 지표를 찾을 수 없습니다.")
        conn.commit()
    return {"id": str(row["id"]), "refresh_interval_seconds": interval, "next_refresh_at": json_value(row["next_refresh_at"])}


@router.patch("/{metric_id}/schedule")
def update_schedule(project_id: UUID, metric_id: UUID, body: MetricScheduleRequest, user: dict = Depends(get_current_user)):
    return set_saved_metric_schedule(str(project_id), user["id"], str(metric_id), body.refresh_interval_seconds)


@router.get("")
def list_metrics(project_id: UUID, user: dict = Depends(get_current_user)):
    return {"metrics": list_saved_metrics(str(project_id), user["id"])}
