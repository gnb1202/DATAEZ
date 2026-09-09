"""Metric contracts, full store isolation, and preservation of failed refreshes."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import dashboard_metrics as metrics
from app.auth import get_current_user

USER = str(uuid4())
STORE = str(uuid4())
OTHER_STORE = str(uuid4())
TABLE = str(uuid4())
WIDGET = str(uuid4())


def definition(**kwargs):
    return metrics.MetricDefinition(table_id=TABLE, column="amount", **kwargs)


def metadata(**kwargs):
    return {
        "id": TABLE, "project_id": STORE, "name": "매출",
        "columns_schema": [
            {"name": "amount", "type": "NUMERIC(15,2)"},
            {"name": "method", "type": "TEXT"},
            {"name": "paid_at", "type": "TIMESTAMP"},
        ], **kwargs,
    }


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(metrics.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    return TestClient(app)


@pytest.fixture
def db():
    with patch.object(metrics, "_connect") as connect:
        conn = connect.return_value.__enter__.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        yield conn, cur


@pytest.mark.parametrize("payload", [
    {"operation": "delete"}, {"operation": "sum", "column": None},
    {"date_grain": "day"}, {"sql": "DELETE FROM users"}, {"version": 2},
])
def test_invalid_definitions_rejected(payload):
    with pytest.raises(ValidationError):
        metrics.MetricDefinition.model_validate({"table_id": TABLE, "column": "amount", **payload})


def test_foreign_store_rejected_before_source_or_query(client, db):
    with patch.object(metrics, "get_project", return_value=None), patch.object(metrics, "get_table_meta") as source:
        res = client.post(f"/api/projects/{STORE}/metrics", json={"title": "매출", "definition": definition().model_dump(mode="json")})
    assert res.status_code == 404
    source.assert_not_called()
    db[1].execute.assert_not_called()


def test_same_owner_other_store_source_rejected(client, db):
    with patch.object(metrics, "get_project", return_value={"id": STORE}), patch.object(metrics, "get_table_meta", return_value=metadata(project_id=OTHER_STORE)):
        res = client.post(f"/api/projects/{STORE}/metrics", json={"title": "매출", "definition": definition().model_dump(mode="json")})
    assert res.status_code == 404
    db[1].execute.assert_not_called()


@pytest.mark.parametrize("changes", [{"column": "missing"}, {"column": "method"}, {"group_by": "method", "date_grain": "month"}])
def test_schema_drift_or_invalid_types_rejected(changes):
    d = metrics.MetricDefinition.model_validate({"table_id": TABLE, "column": "amount", **changes})
    with patch.object(metrics, "get_table_meta", return_value=metadata()), pytest.raises(HTTPException) as caught:
        metrics.resolve_source(STORE, USER, d)
    assert caught.value.status_code == 422


def test_sql_quotes_identifiers_and_aggregates_all_rows():
    d = metrics.MetricDefinition(table_id=TABLE, column='amount"; DROP TABLE users; --')
    query, params = metrics.compile_metric("ut_test", d)
    assert query.as_string() == ('SELECT SUM("amount""; DROP TABLE users; --") AS value, '
                                'COUNT(*) FILTER (WHERE "amount""; DROP TABLE users; --" IS NULL) AS missing_values FROM "ut_test"')
    assert params == []
    assert "LIMIT" not in query.as_string()


def test_daily_grouping_is_parameterized_and_overflow_detectable():
    query, params = metrics.compile_metric("ut_test", definition(group_by="paid_at", date_grain="day"))
    assert "GROUP BY 1 ORDER BY 1" in query.as_string()
    assert params == ["day", metrics.MAX_GROUPS + 1]


def test_count_means_rows_including_null_amounts():
    query, _ = metrics.compile_metric("ut_test", metrics.MetricDefinition(table_id=TABLE, operation="count"))
    assert "COUNT(*)" in query.as_string()


def test_group_overflow_fails_instead_of_silent_partial_chart():
    cur = MagicMock()
    cur.fetchall.return_value = [{"dimension": "x", "value": 1}] * (metrics.MAX_GROUPS + 1)
    with pytest.raises(HTTPException) as caught:
        metrics.calculate(cur, USER, definition(group_by="method"), metadata())
    assert caught.value.status_code == 422


def test_create_persists_definition_and_exact_decimal(client, db):
    conn, cur = db
    cur.fetchall.return_value = [{"value": Decimal("250000.10")}]
    with patch.object(metrics, "get_project", return_value={"id": STORE}), patch.object(metrics, "get_table_meta", return_value=metadata()):
        res = client.post(f"/api/projects/{STORE}/metrics", json={"title": "전체 결제액", "definition": definition().model_dump(mode="json")})
    assert res.status_code == 201
    result = res.json()["widget_data"]
    assert result["value"] == "250000.10"
    assert result["metric_definition"]["table_id"] == TABLE
    assert result["calculated_at"]
    sql_args = cur.execute.call_args.args
    assert sql_args[1][1:3] == (USER, STORE)
    conn.commit.assert_called_once()


def test_refresh_reexecutes_saved_definition(client, db):
    conn, cur = db
    cur.fetchone.side_effect = [{"widget_data": {"metric_definition": definition().model_dump(mode="json"), "value": "100"}}, metadata()]
    cur.fetchall.return_value = [{"value": Decimal("350")}]
    with patch.object(metrics, "get_project", return_value={"id": STORE}), patch.object(metrics, "get_table_meta", return_value=metadata()):
        res = client.post(f"/api/projects/{STORE}/metrics/{WIDGET}/refresh")
    assert res.status_code == 200
    assert res.json()["widget_data"]["value"] == "350"
    first_call = cur.execute.call_args_list[0].args
    assert "FOR UPDATE" in first_call[0]
    assert first_call[1] == (WIDGET, USER, STORE)
    conn.commit.assert_called_once()


def test_refresh_wrong_widget_scope_does_not_run_query(client, db):
    db[1].fetchone.return_value = None
    with patch.object(metrics, "get_project", return_value={"id": STORE}), patch.object(metrics, "calculate") as calculate:
        res = client.post(f"/api/projects/{STORE}/metrics/{WIDGET}/refresh")
    assert res.status_code == 404
    calculate.assert_not_called()


def test_failed_refresh_preserves_last_value_and_records_error(client, db):
    import json
    conn, cur = db
    cur.fetchone.side_effect = [{"widget_data": {"metric_definition": definition().model_dump(mode="json"), "value": "100", "calculated_at": "old-success"}}, None]
    with patch.object(metrics, "get_project", return_value={"id": STORE}), patch.object(metrics, "get_table_meta", return_value=None):
        res = client.post(f"/api/projects/{STORE}/metrics/{WIDGET}/refresh")
    assert res.status_code == 422
    stored = json.loads(cur.execute.call_args.args[1][0])
    assert stored["value"] == "100"
    assert stored["calculated_at"] == "old-success"
    assert stored["refresh_error"]
    conn.commit.assert_called_once()


def test_empty_sum_is_not_misreported_as_zero():
    cur = MagicMock()
    cur.fetchall.return_value = [{"value": None}]
    result = metrics.calculate(cur, USER, definition(), metadata())
    assert result["formatted"] == "데이터 없음"


def test_schedule_endpoint_rejects_other_store_widget(client, db):
    db[1].fetchone.return_value = None
    with patch.object(metrics, "get_project", return_value={"id": STORE}):
        res = client.patch(f"/api/projects/{STORE}/metrics/{WIDGET}/schedule", json={"refresh_interval_seconds": 3600})
    assert res.status_code == 404
    assert db[1].execute.call_args.args[1][-3:] == (WIDGET, USER, STORE)


def test_schedule_endpoint_rejects_arbitrary_fast_interval(client, db):
    res = client.patch(f"/api/projects/{STORE}/metrics/{WIDGET}/schedule", json={"refresh_interval_seconds": 1})
    assert res.status_code == 422
    db[1].execute.assert_not_called()
