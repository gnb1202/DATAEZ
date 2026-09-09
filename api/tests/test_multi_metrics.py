"""Multi-ledger contracts, ownership, exact results and saved refresh behavior."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import dashboard_metrics as metrics
from app import multi_metrics as multi
from app.agent_tools import ToolExecutor
from app.auth import get_current_user
from app.metric_definitions import MultiMetricDefinition, parse_metric_definition

USER, STORE, OTHER_STORE, CASH, CARD, WIDGET = [str(uuid4()) for _ in range(6)]


def definition(**changes):
    return MultiMetricDefinition.model_validate({"sources": [
        {"table_id": CASH, "label": "현금", "column": "금액", "date_column": "일자"},
        {"table_id": CARD, "label": "카드", "column": "승인금액", "date_column": "승인일"},
    ], **changes})


def metadata(table_id=CASH, **changes):
    return {"id": table_id, "project_id": STORE, "name": "현금" if table_id == CASH else "카드",
            "columns_schema": [{"name": name, "type": dtype} for name, dtype in
                [("금액", "NUMERIC"), ("일자", "DATE"), ("승인금액", "NUMERIC"), ("승인일", "TIMESTAMP")]], **changes}


def result(**changes):
    return {"missing_amounts": 0, "invalid_amounts": 0, "missing_dates": 0,
            "data": [{"value": "250000.10"}], "source_counts": {"현금": 2, "카드": 1}, **changes}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(metrics.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    return TestClient(app)


@pytest.mark.parametrize("changes", [{"operation": "avg"}, {"version": 1}, {"chart_type": "pie"},
    {"sources": []}, {"sources": [definition().sources[0]]},
    {"sources": [definition().sources[0]] * 6}, {"sources": [definition().sources[0]] * 2},
    {"sources": [{**s.model_dump(), "label": "중복"} for s in definition().sources]},
    {"sources": [{**s.model_dump(), "currency": "USD"} for s in definition().sources]},
    {"table_id": CASH}, {"group_by": "arbitrary_column"},
])
def test_invalid_multi_contract_is_rejected(changes):
    with pytest.raises(ValidationError):
        definition(**changes)


@pytest.mark.parametrize("changes", [{"group_by": "date"}, {"time_range": "this_month"}])
def test_every_source_needs_a_date_for_date_metrics(changes):
    sources = [s.model_dump() for s in definition().sources]
    sources[1]["date_column"] = None
    with pytest.raises(ValidationError):
        definition(sources=sources, **changes)


def test_versioned_parse_preserves_old_definitions():
    assert parse_metric_definition({"table_id": CASH, "column": "금액"}).version == 1
    assert parse_metric_definition(definition().model_dump(mode="json")).version == 2


def test_foreign_store_preview_rejected_before_any_source(client):
    with patch.object(metrics, "get_project", return_value=None), patch.object(metrics, "get_table_meta") as lookup:
        response = client.post(f"/api/projects/{STORE}/metrics/preview", json={"definition": definition().model_dump(mode="json")})
    assert response.status_code == 404
    lookup.assert_not_called()


def test_mixed_store_sources_rejected_before_any_calculation(client):
    with patch.object(metrics, "get_project", return_value={"id": STORE}), \
         patch.object(metrics, "get_table_meta", side_effect=[metadata(), metadata(CARD, project_id=OTHER_STORE)]), \
         patch.object(metrics, "calculate") as calculate:
        response = client.post(f"/api/projects/{STORE}/metrics/preview", json={"definition": definition().model_dump(mode="json")})
    assert response.status_code == 404
    calculate.assert_not_called()


def test_same_file_imports_rejected():
    file_id = str(uuid4())
    with patch.object(metrics, "get_table_meta", side_effect=[metadata(source_file_id=file_id), metadata(CARD, source_file_id=file_id)]):
        with pytest.raises(HTTPException, match="같은 원본 파일"):
            multi.resolve_sources(STORE, USER, definition())


def test_all_source_schemas_are_validated():
    with patch.object(metrics, "get_table_meta", side_effect=[metadata(), metadata(CARD, columns_schema=[])]):
        with pytest.raises(HTTPException, match="컬럼"):
            multi.resolve_sources(STORE, USER, definition())


def test_queries_bind_values_quote_columns_and_never_join_payments():
    payload = definition(group_by="date").model_dump(mode="json")
    payload["sources"][0].update(column='금액" %s', label="cash'); DROP TABLE users;--",
        filters=[{"column": "결제수단", "value": "현금' OR 1=1 --"}])
    query, params = multi.compile_multi(USER, MultiMetricDefinition.model_validate(payload))
    query = query.as_string()
    assert '"금액"" %%s"::numeric' in query
    assert "UNION ALL" in query and "JOIN" not in query
    assert "DROP TABLE" not in query and "OR 1=1" not in query
    assert params == ["cash'); DROP TABLE users;--", "현금' OR 1=1 --", "카드", "day", 1001]
    assert "jsonb_agg(to_jsonb(r) ORDER BY r.dimension)" in query


@pytest.mark.parametrize("bad_row,message", [
    ({"missing_amounts": 1}, "금액이 비어"), ({"missing_dates": 1}, "날짜가 비어"),
    ({"invalid_amounts": 1}, "정상적인 숫자"),
    ({"data": [{"dimension": "x", "value": "1"}] * 1001}, "1,000개"),
])
def test_bad_data_fails_whole_calculation(bad_row, message):
    cur = MagicMock()
    cur.fetchone.return_value = result(**bad_row)
    with pytest.raises(HTTPException, match=message):
        multi.calculate_multi(cur, USER, definition(group_by="date"), [metadata(), metadata(CARD)])


def test_exact_decimal_and_source_provenance_are_returned():
    cur = MagicMock()
    cur.fetchone.return_value = result(data=[{"value": "9007199254740993.01"}])
    output = multi.calculate_multi(cur, USER, definition(), [metadata(), metadata(CARD)])
    assert output["value"] == "9007199254740993.01"
    assert output["currency"] == "KRW" and output["metric_definition"]["version"] == 2
    assert output["sources"][0]["included_rows"] == 2
    assert output["warnings"]


def test_empty_sources_are_not_reported_as_zero():
    cur = MagicMock()
    cur.fetchone.return_value = result(data=[{"value": None}], source_counts={})
    output = multi.calculate_multi(cur, USER, definition(), [metadata(), metadata(CARD)])
    assert output["value"] is None and output["formatted"] == "데이터 없음"
    assert all(s["included_rows"] == 0 for s in output["sources"])


def test_multi_save_uses_kpi_when_group_is_none(client):
    with patch.object(metrics, "get_project", return_value={"id": STORE}), \
         patch.object(metrics, "get_table_meta", side_effect=[metadata(), metadata(CARD)]), \
         patch.object(metrics, "_connect") as connect:
        conn = connect.return_value.__enter__.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = result()
        response = client.post(f"/api/projects/{STORE}/metrics", json={"title": "통합", "definition": definition().model_dump(mode="json"), "refresh_interval_seconds": 3600})
    assert response.status_code == 201
    assert cur.execute.call_args.args[1][3] == "kpi"
    assert response.json()["widget_data"]["value"] == "250000.10"
    conn.commit.assert_called_once()


def test_multi_refresh_revalidates_sources_and_reuses_definition():
    cur = MagicMock()
    cur.fetchone.side_effect = [metadata(), metadata(CARD), result()]
    saved = definition().model_dump(mode="json")
    row = {"widget_data": {"metric_definition": saved, "value": "1"}, "refresh_interval_seconds": 3600}
    output, error = metrics.refresh_locked(MagicMock(), cur, row, WIDGET, USER, STORE)
    assert error is None and output["value"] == "250000.10"
    assert output["metric_definition"] == saved
    assert cur.execute.call_args_list[0].args[1] == (CASH, USER)
    assert cur.execute.call_args_list[1].args[1] == (CARD, USER)
    assert cur.execute.call_args.args[1][1:4] == (0, 3600, 3600)


def test_multi_refresh_failure_preserves_whole_previous_result():
    cur = MagicMock()
    cur.fetchone.side_effect = [metadata(), metadata(CARD), result(missing_amounts=1)]
    old = {"metric_definition": definition().model_dump(mode="json"), "value": "250000.10", "calculated_at": "last-good"}
    output, error = metrics.refresh_locked(MagicMock(), cur, {"widget_data": old, "refresh_interval_seconds": 3600}, WIDGET, USER, STORE)
    assert error and output["value"] == old["value"]
    assert output["calculated_at"] == "last-good"
    assert cur.execute.call_args.args[1][1:4] == (1, 60, 60)


def test_natural_tools_preview_and_save_same_multi_mapping():
    with patch("app.agent_tools.list_table_metas", return_value=[metadata(), metadata(CARD)]), \
         patch("app.agent_tools.record_audit"), \
         patch.object(metrics, "preview_saved_metric", return_value={"value": "250000.10"}) as preview, \
         patch.object(metrics, "create_saved_metric", return_value={"id": WIDGET}) as save:
        executor = ToolExecutor(USER, STORE)
        args = definition().model_dump(mode="json")
        for source, name in zip(args["sources"], ["현금", "카드"]):
            source.pop("table_id")
            source["table_name"] = name
        assert executor.execute("preview_metric", json.dumps(args))["saved"] is False
        assert executor.execute("save_metric", json.dumps({**args, "title": "통합"}))["saved"] is True
        assert preview.call_args.args[2] == save.call_args.args[2].definition
        args["sources"][1]["table_name"] = "다른 가게 카드"
        assert "error" in executor.execute("preview_metric", json.dumps(args))
        assert preview.call_count == 1
