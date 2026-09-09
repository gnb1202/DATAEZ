"""Natural-language tool execution contracts and durable scheduling policy."""

import asyncio
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import dashboard_metrics as metrics
from app import metric_scheduler as scheduler
from app.agent import _select_tools
from app.agent import run_agent
from app.agent_tools import ToolExecutor
from app.metric_agent_tools import METRIC_TOOL_SPECS
from app.prompts import build_conversation_context
from app.router import OrchestratorResult, select_tools_via_orchestrator

USER, STORE, TABLE, WIDGET = [str(uuid4()) for _ in range(4)]
SOURCE = {"id": TABLE, "project_id": STORE, "name": "결제", "columns_schema": [
    {"name": "amount", "type": "NUMERIC(15,2)"}, {"name": "method", "type": "TEXT"}, {"name": "paid_at", "type": "DATE"},
]}
ARGS = {"table_name": "결제", "operation": "sum", "column": "amount", "group_by": "paid_at", "date_grain": "day",
        "time_range": "this_month", "date_column": "paid_at", "filters": [{"column": "method", "value": "카드"}]}


@pytest.fixture
def executor():
    with patch("app.agent_tools.list_table_metas", return_value=[SOURCE]), patch("app.agent_tools.record_audit"):
        yield ToolExecutor(USER, STORE)


def test_preview_then_save_uses_identical_definition_and_store(executor):
    with patch.object(metrics, "preview_saved_metric", return_value={"value": "150000"}) as preview, \
         patch.object(metrics, "create_saved_metric", return_value={"id": WIDGET}) as save:
        result = executor.execute("preview_metric", json.dumps(ARGS))
        assert result["saved"] is False
        saved = executor.execute("save_metric", json.dumps({**ARGS, "title": "이번 달 카드", "refresh_interval_seconds": 3600}))
        assert saved["saved"] is True
        assert preview.call_args.args[:2] == (STORE, USER)
        assert save.call_args.args[:2] == (STORE, USER)
        assert preview.call_args.args[2] == save.call_args.args[2].definition
        assert save.call_args.args[2].refresh_interval_seconds == 3600


def test_worker_turn_previews_and_saves_then_answers(executor):
    from types import SimpleNamespace as NS
    def response(name=None, args=None):
        message = MagicMock()
        message.content = "대시보드에 저장했습니다."
        message.tool_calls = [NS(id=str(uuid4()), function=NS(name=name, arguments=json.dumps(args)))] if name else []
        message.model_dump.return_value = {"role": "assistant", "content": None}
        return NS(usage=None, choices=[NS(message=message, finish_reason="tool_calls" if name else "stop")])
    client = MagicMock()
    client.chat.completions.create.side_effect = [response("preview_metric", ARGS), response("save_metric", {**ARGS, "title": "이번 달 카드", "refresh_interval_seconds": 3600}), response()]
    chart = {"chart_type": "bar", "x_key": "dimension", "y_key": "value", "data": [{"dimension": "2026-09-01", "value": "150000"}], "metric_definition": {"table_id": TABLE, "column": "amount"}}
    with patch("app.agent._select_tools", return_value=(METRIC_TOOL_SPECS, "analysis", False)), \
         patch("app.agent.ToolExecutor", return_value=executor), patch("app.agent.get_openai_client", return_value=client), \
         patch.object(metrics, "preview_saved_metric", return_value=chart), patch.object(metrics, "create_saved_metric", return_value={"id": WIDGET}):
        result = run_agent(USER, STORE, "강남점", [SOURCE], [], "이번 달 일별 카드 매출을 저장하고 매시간 갱신해줘")
    assert result.mutations_performed
    assert result.charts[0]["metric_definition"]["table_id"] == TABLE
    assert [s.tool_name for s in result.steps if s.type == "tool_call"] == ["preview_metric", "save_metric"]
    assert result.steps[1].tool_output["saved"] is True


def test_repeated_tool_save_in_same_turn_is_idempotent(executor):
    with patch.object(metrics, "create_saved_metric", return_value={"id": WIDGET}) as save:
        args = json.dumps({**ARGS, "title": "매출"})
        assert executor.execute("save_metric", args)["metric_id"] == WIDGET
        assert executor.execute("save_metric", args)["metric_id"] == WIDGET
        save.assert_called_once()


def test_no_fuzzy_source_match_or_foreign_table_id(executor):
    with patch.object(metrics, "create_saved_metric") as save:
        result = executor.execute("save_metric", json.dumps({**ARGS, "table_name": "결", "title": "잘못된 대상"}))
        assert "error" in result
        save.assert_not_called()


def test_save_failure_is_not_reported_as_saved(executor):
    with patch.object(metrics, "create_saved_metric", side_effect=HTTPException(422, "invalid")):
        result = executor.execute("save_metric", json.dumps({**ARGS, "title": "매출"}))
    assert "error" in result and not result.get("saved")


def test_schedule_tool_scopes_store_and_validates_id(executor):
    with patch.object(metrics, "set_saved_metric_schedule", return_value={"id": WIDGET}) as schedule:
        result = executor.execute("set_metric_refresh", json.dumps({"metric_id": WIDGET, "refresh_interval_seconds": 0}))
    assert result["id"] == WIDGET
    schedule.assert_called_once_with(STORE, USER, WIDGET, 0)


def test_followup_router_receives_recent_context():
    history = [{"role": "assistant", "content": "일별 카드 매출 지표를 만들었습니다."}]
    with patch("app.router._call_orchestrator", return_value={"intent": "analysis", "tools": ["save_metric"]}) as call:
        result = select_tools_via_orchestrator("그걸 저장해줘", conversation_messages=history)
    payload = json.loads(call.call_args.args[1])
    assert payload["current_request"] == "그걸 저장해줘"
    assert payload["recent_conversation_data"] == history
    assert "save_metric" in result.tools


def test_selected_metric_tool_has_source_and_preview_dependencies():
    with patch("app.agent.select_tools_via_orchestrator", return_value=OrchestratorResult(["save_metric"], "analysis")):
        specs, _, _ = _select_tools("저장해줘")
    names = {s["function"]["name"] for s in specs}
    assert {"save_metric", "preview_metric", "search_schema", "describe_table", "list_metrics"} <= names
    assert "insert_rows" not in names


def test_followup_preserves_filter_definition_after_answer_truncation():
    history = [{"role": "assistant", "content": "a" * 2000, "steps": [
        {"tool_name": "preview_metric", "tool_input": ARGS, "tool_output": {"value": "150000"}},
    ]}]
    content = build_conversation_context(history)[0]["content"]
    assert '"time_range": "this_month"' in content
    assert '"value": "카드"' in content


def test_tool_json_schema_is_self_contained():
    for spec in METRIC_TOOL_SPECS:
        assert '"$ref"' not in json.dumps(spec)


def test_time_filter_requires_date_column_and_rejects_unsupported_interval():
    with pytest.raises(ValidationError):
        metrics.MetricDefinition(table_id=TABLE, column="amount", time_range="this_month")
    with pytest.raises(ValidationError):
        metrics.MetricScheduleRequest(refresh_interval_seconds=1)


def test_relative_period_and_bound_parameters_survive_reexecution():
    definition = metrics.MetricDefinition(table_id=TABLE, column="amount", group_by="paid_at", date_grain="day",
        date_column="paid_at", time_range="this_month", filters=[{"column": "method", "value": "카드' OR 1=1 --"}])
    query, params = metrics.compile_metric("ut_test", definition)
    assert "CURRENT_DATE" in query.as_string()
    assert "카드" not in query.as_string()
    assert params == ["day", "카드' OR 1=1 --", 1001]


@pytest.mark.parametrize("previous_failures,delay", [(0, 60), (1, 120), (2, 0), (99, 0)])
def test_scheduler_bounded_retries_preserve_last_value(previous_failures, delay):
    conn, cur = MagicMock(), MagicMock()
    row = {"widget_data": {"metric_definition": {"table_id": TABLE, "column": "amount"}, "value": "250000"},
           "refresh_interval_seconds": 3600, "refresh_failures": previous_failures}
    with patch.object(metrics, "resolve_source", side_effect=HTTPException(422, "컬럼 변경")):
        result, failure = metrics.refresh_locked(conn, cur, row, WIDGET, USER, STORE)
    assert failure and result["value"] == "250000"
    assert cur.execute.call_args.args[1][2:4] == (delay, delay)


def test_manual_metric_failure_is_never_scheduled():
    cur = MagicMock()
    row = {"widget_data": {"metric_definition": {}}, "refresh_interval_seconds": 0}
    metrics.refresh_locked(MagicMock(), cur, row, WIDGET, USER, STORE)
    assert cur.execute.call_args.args[1][2:4] == (0, 0)


def test_success_resets_failures_and_returns_to_selected_interval():
    cur = MagicMock()
    row = {"widget_data": {"metric_definition": {"table_id": TABLE, "column": "amount"}}, "refresh_interval_seconds": 86400, "refresh_failures": 3}
    with patch.object(metrics, "resolve_source", return_value=SOURCE), patch.object(metrics, "calculate", return_value={"value": "300000"}):
        _, failure = metrics.refresh_locked(MagicMock(), cur, row, WIDGET, USER, STORE)
    assert failure is None
    assert cur.execute.call_args.args[1][1:4] == (0, 86400, 86400)


def test_due_claim_excludes_deleted_stores_and_skips_other_workers():
    with patch.object(scheduler, "_connect") as connect, patch.object(scheduler, "refresh_locked", return_value=({}, None)) as run:
        conn = connect.return_value.__enter__.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"id": WIDGET, "user_id": USER, "project_id": STORE}
        assert scheduler.refresh_one_due() is True
    query = cur.execute.call_args.args[0]
    assert "SKIP LOCKED" in query and "p.deleted_at IS NULL" in query and "p.user_id=w.user_id" in query
    assert run.call_args.args[3:] == (WIDGET, USER, STORE)
    conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_stops_cleanly_after_current_tick():
    stop = asyncio.Event()
    def tick():
        stop.set()
        return False
    with patch.object(scheduler, "refresh_one_due", side_effect=tick) as run:
        await asyncio.wait_for(scheduler.run_metric_scheduler(stop), timeout=2)
    run.assert_called_once()
