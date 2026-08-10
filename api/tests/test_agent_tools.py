"""Tests for api/app/agent_tools.py — tool metadata, structured errors, ToolExecutor."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agent_tools import (
    TOOL_META,
    TOOL_SPECS,
    _error_missing_param,
    _error_table_not_found,
    _error_validation,
    ToolExecutor,
)


# ---------------------------------------------------------------------------
# TOOL_META completeness
# ---------------------------------------------------------------------------

class TestToolMeta:
    def test_all_tool_specs_have_meta(self):
        """Every tool in TOOL_SPECS must have a TOOL_META entry."""
        spec_names = {t["function"]["name"] for t in TOOL_SPECS}
        meta_names = set(TOOL_META.keys())
        assert spec_names == meta_names, f"Missing meta: {spec_names - meta_names}"

    def test_meta_has_required_keys(self):
        for name, meta in TOOL_META.items():
            assert "read_only" in meta, f"{name} missing read_only"
            assert "needs_table" in meta, f"{name} missing needs_table"
            assert "mutation" in meta, f"{name} missing mutation"

    def test_mutation_tools_are_not_read_only(self):
        """Mutation tools should not be marked read_only."""
        for name, meta in TOOL_META.items():
            if meta["mutation"]:
                assert not meta["read_only"], f"{name}: mutation=True but read_only=True"

    def test_read_only_tools_no_mutation(self):
        """Read-only tools should have mutation=False."""
        for name, meta in TOOL_META.items():
            if meta["read_only"]:
                assert not meta["mutation"], f"{name}: read_only=True but mutation=True"

    def test_known_mutation_tools(self):
        expected_mutations = {"insert_rows", "update_rows", "delete_rows", "create_table", "alter_table", "import_file"}
        actual_mutations = {name for name, meta in TOOL_META.items() if meta["mutation"]}
        assert actual_mutations == expected_mutations

    def test_known_read_only_tools(self):
        expected_reads = {
            "list_tables", "describe_table", "query_data",
            "generate_chart", "recommend_charts", "cross_query",
            "search_schema", "search_documents",
        }
        actual_reads = {name for name, meta in TOOL_META.items() if meta["read_only"]}
        assert actual_reads == expected_reads


# ---------------------------------------------------------------------------
# Structured error helpers
# ---------------------------------------------------------------------------

class TestStructuredErrors:
    def test_error_table_not_found(self):
        err = _error_table_not_found("매출", ["매출관리", "비용"])
        assert err["error"] == "table_not_found"
        assert "매출" in err["message"]
        assert err["available_tables"] == ["매출관리", "비용"]
        assert "recovery" in err

    def test_error_missing_param(self):
        err = _error_missing_param("table_name")
        assert err["error"] == "missing_parameter"
        assert "table_name" in err["message"]

    def test_error_missing_param_with_detail(self):
        err = _error_missing_param("rows", "행 데이터를 지정하세요.")
        assert err["detail"] == "행 데이터를 지정하세요."

    def test_error_validation(self):
        err = _error_validation("WHERE 조건이 필요합니다.", recovery="조건을 지정하세요.")
        assert err["error"] == "validation_error"
        assert "WHERE" in err["message"]
        assert err["recovery"] == "조건을 지정하세요."

    def test_error_validation_extra_kwargs(self):
        err = _error_validation("잘못됨", count=5, detail="추가정보")
        assert err["count"] == 5
        assert err["detail"] == "추가정보"


# ---------------------------------------------------------------------------
# ToolExecutor — mocked DB
# ---------------------------------------------------------------------------

MOCK_TABLES = [
    {
        "id": "table-001",
        "name": "매출",
        "row_count": 100,
        "columns_schema": [
            {"name": "날짜", "type": "DATE"},
            {"name": "품목", "type": "TEXT"},
            {"name": "금액", "type": "BIGINT"},
        ],
    },
    {
        "id": "table-002",
        "name": "비용",
        "row_count": 50,
        "columns_schema": [
            {"name": "날짜", "type": "DATE"},
            {"name": "항목", "type": "TEXT"},
            {"name": "금액", "type": "BIGINT"},
        ],
    },
]


@pytest.fixture
def executor():
    """ToolExecutor with mocked DB calls."""
    with patch("app.agent_tools.list_table_metas", return_value=MOCK_TABLES), \
         patch("app.agent_tools.get_user_table_name", side_effect=lambda uid, tid: f"ut_{uid}_{tid}"):
        ex = ToolExecutor(user_id="user-1", project_id="proj-1")
    return ex


class TestToolExecutorRouting:
    def test_unknown_tool(self, executor):
        result = executor.execute("nonexistent_tool", "{}")
        assert result["error"] == "validation_error"
        assert "알 수 없는 도구" in result["message"]

    def test_invalid_json_args(self, executor):
        result = executor.execute("list_tables", "not json")
        assert result["error"] == "validation_error"
        assert "JSON" in result["message"]

    def test_empty_args(self, executor):
        """Empty string args should be treated as empty dict."""
        result = executor.execute("list_tables", "")
        assert "tables" in result


class TestToolListTables:
    def test_returns_all_tables(self, executor):
        result = executor.execute("list_tables", "{}")
        assert result["total"] == 2
        names = [t["name"] for t in result["tables"]]
        assert "매출" in names
        assert "비용" in names

    def test_table_info_fields(self, executor):
        result = executor.execute("list_tables", "{}")
        table = result["tables"][0]
        assert "name" in table
        assert "row_count" in table
        assert "columns" in table
        assert "column_count" in table


class TestToolDescribeTable:
    def test_missing_table_name(self, executor):
        result = executor.execute("describe_table", json.dumps({}))
        assert result["error"] == "missing_parameter"

    @patch("app.agent_tools.get_sample_rows", return_value=[{"날짜": "2025-01-01", "품목": "커피", "금액": 5000}])
    def test_describe_existing_table(self, mock_sample, executor):
        result = executor.execute("describe_table", json.dumps({"table_name": "매출"}))
        assert result["table_name"] == "매출"
        assert result["row_count"] == 100
        assert len(result["columns"]) == 3
        assert "sample_rows" in result

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_describe_records_in_described_set(self, mock_sample, executor):
        """After describe, table should be in _described_tables."""
        assert "매출" not in executor._described_tables
        executor.execute("describe_table", json.dumps({"table_name": "매출"}))
        assert "매출" in executor._described_tables

    def test_describe_nonexistent_table(self, executor):
        result = executor.execute("describe_table", json.dumps({"table_name": "없는장부"}))
        assert result["error"] == "table_not_found"
        assert "available_tables" in result


class TestReadBeforeWrite:
    """Tests for the _auto_describe_if_needed mechanism."""

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_insert", return_value={"inserted": 1})
    def test_auto_describe_before_insert(self, mock_insert, mock_sample, executor):
        """insert_rows on un-described table should trigger auto describe."""
        assert "매출" not in executor._described_tables
        executor.execute("insert_rows", json.dumps({
            "table_name": "매출",
            "rows": [{"품목": "커피", "금액": 5000}],
        }))
        # After execution, table should be described
        assert "매출" in executor._described_tables
        mock_insert.assert_called_once()

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_insert", return_value={"inserted": 1})
    def test_skip_describe_if_already_described(self, mock_insert, mock_sample, executor):
        """If table was already described, don't describe again."""
        executor._described_tables.add("매출")
        executor.execute("insert_rows", json.dumps({
            "table_name": "매출",
            "rows": [{"품목": "커피", "금액": 5000}],
        }))
        # get_sample_rows should NOT be called (describe skipped)
        mock_sample.assert_not_called()

    def test_auto_describe_nonexistent_table_blocks_mutation(self, executor):
        """Auto-describe on nonexistent table should block the mutation."""
        result = executor.execute("insert_rows", json.dumps({
            "table_name": "없는장부",
            "rows": [{"a": 1}],
        }))
        assert result["error"] == "table_not_found"

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_no_auto_describe_for_read_tools(self, mock_sample, executor):
        """Read-only tools should NOT trigger auto describe."""
        with patch("app.agent_tools.safe_select", return_value={"rows": [], "columns": [], "total_count": 0}):
            executor.execute("query_data", json.dumps({"table_name": "매출"}))
        # get_sample_rows not called via auto_describe (query_data is read-only)
        mock_sample.assert_not_called()

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_update", return_value={"updated": 1})
    def test_auto_describe_before_update(self, mock_update, mock_sample, executor):
        """update_rows should also trigger auto describe."""
        executor.execute("update_rows", json.dumps({
            "table_name": "매출",
            "set_values": {"금액": 6000},
            "where": [{"column": "품목", "operator": "=", "value": "커피"}],
        }))
        assert "매출" in executor._described_tables

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_delete", return_value={"deleted": 1})
    def test_auto_describe_before_delete(self, mock_delete, mock_sample, executor):
        """delete_rows should also trigger auto describe."""
        executor.execute("delete_rows", json.dumps({
            "table_name": "매출",
            "where": [{"column": "품목", "operator": "=", "value": "커피"}],
        }))
        assert "매출" in executor._described_tables


class TestToolInsertRows:
    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_insert", return_value={"inserted": 2})
    def test_insert_success(self, mock_insert, mock_sample, executor):
        result = executor.execute("insert_rows", json.dumps({
            "table_name": "매출",
            "rows": [{"품목": "커피", "금액": 5000}, {"품목": "케이크", "금액": 8000}],
        }))
        assert result["inserted"] == 2
        assert executor.mutations_performed is True
        assert "table-001" in executor.mutated_table_ids

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_insert_empty_rows(self, mock_sample, executor):
        result = executor.execute("insert_rows", json.dumps({
            "table_name": "매출",
            "rows": [],
        }))
        assert result["error"] == "missing_parameter"


class TestToolUpdateRows:
    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_update_no_where(self, mock_sample, executor):
        result = executor.execute("update_rows", json.dumps({
            "table_name": "매출",
            "set_values": {"금액": 6000},
            "where": [],
        }))
        assert result["error"] == "validation_error"
        assert "WHERE" in result["message"]

    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_update_no_set_values(self, mock_sample, executor):
        result = executor.execute("update_rows", json.dumps({
            "table_name": "매출",
            "set_values": {},
            "where": [{"column": "품목", "operator": "=", "value": "커피"}],
        }))
        assert result["error"] == "missing_parameter"


class TestToolDeleteRows:
    @patch("app.agent_tools.get_sample_rows", return_value=[])
    def test_delete_no_where(self, mock_sample, executor):
        result = executor.execute("delete_rows", json.dumps({
            "table_name": "매출",
            "set_values": {"금액": 6000},
            "where": [],
        }))
        assert result["error"] == "validation_error"
        assert "WHERE" in result["message"]


class TestToolGenerateChart:
    def test_no_data_no_last_query(self, executor):
        result = executor.execute("generate_chart", json.dumps({
            "chart_type": "bar",
            "title": "테스트",
            "x_column": "품목",
            "y_column": "금액",
        }))
        assert result["error"] == "validation_error"
        assert "recovery" in result

    def test_uses_last_query_result(self, executor):
        executor.last_query_result = [
            {"품목": "커피", "금액": 5000},
            {"품목": "케이크", "금액": 8000},
        ]
        result = executor.execute("generate_chart", json.dumps({
            "chart_type": "bar",
            "title": "매출 비교",
            "x_column": "품목",
            "y_column": "금액",
        }))
        assert result["chart_type"] == "bar"
        assert result["data"] is not None

    def test_explicit_data(self, executor):
        result = executor.execute("generate_chart", json.dumps({
            "chart_type": "pie",
            "title": "구성비",
            "x_column": "품목",
            "y_column": "금액",
            "data": [{"품목": "A", "금액": 100}],
        }))
        assert result["chart_type"] == "pie"


class TestToolCreateTable:
    @patch("app.agent_tools.create_user_data_table")
    @patch("app.agent_tools.create_table_meta", return_value={"id": "new-id"})
    @patch("app.agent_tools.list_table_metas", return_value=MOCK_TABLES)
    def test_create_success(self, mock_list, mock_meta, mock_create, executor):
        result = executor.execute("create_table", json.dumps({
            "table_name": "재고",
            "columns": [
                {"name": "품목", "type": "TEXT"},
                {"name": "수량", "type": "BIGINT"},
            ],
        }))
        assert result["success"] is True
        assert result["table_name"] == "재고"
        assert executor.schema_changed is True

    def test_create_duplicate_name(self, executor):
        result = executor.execute("create_table", json.dumps({
            "table_name": "매출",
            "columns": [{"name": "x", "type": "TEXT"}],
        }))
        assert result["error"] == "validation_error"
        assert "이미 존재" in result["message"]

    def test_create_no_columns(self, executor):
        result = executor.execute("create_table", json.dumps({
            "table_name": "새장부",
            "columns": [],
        }))
        assert result["error"] == "missing_parameter"

    def test_create_too_many_columns(self, executor):
        cols = [{"name": f"col{i}", "type": "TEXT"} for i in range(51)]
        result = executor.execute("create_table", json.dumps({
            "table_name": "새장부",
            "columns": cols,
        }))
        assert result["error"] == "validation_error"


class TestToolImportFile:
    def test_no_attached_files(self, executor):
        result = executor.execute("import_file", json.dumps({
            "action": "create_new",
            "table_name": "새장부",
        }))
        assert result["error"] == "validation_error"
        assert "첨부" in result["message"]

    def test_invalid_file_index(self, executor):
        executor.attached_files = [{"filename": "test.csv", "content": b"a,b\n1,2"}]
        result = executor.execute("import_file", json.dumps({
            "action": "create_new",
            "table_name": "새장부",
            "file_index": 5,
        }))
        assert result["error"] == "validation_error"

    def test_missing_action(self, executor):
        result = executor.execute("import_file", json.dumps({
            "table_name": "새장부",
        }))
        assert result["error"] == "missing_parameter"


class TestToolResolveTable:
    def test_exact_match(self, executor):
        resolved = executor._resolve_table("매출")
        assert resolved is not None
        pg_name, meta = resolved
        assert meta["name"] == "매출"

    def test_case_insensitive(self, executor):
        """Lookup should work case-insensitively."""
        # Korean doesn't have cases but the code supports it
        resolved = executor._resolve_table("매출")
        assert resolved is not None

    def test_substring_match(self, executor):
        """Fuzzy: substring matching should work."""
        # "매" is a substring of "매출"
        resolved = executor._resolve_table("매")
        assert resolved is not None

    def test_no_match(self, executor):
        resolved = executor._resolve_table("없는장부XYZ")
        assert resolved is None


class TestMutationTracking:
    @patch("app.agent_tools.get_sample_rows", return_value=[])
    @patch("app.agent_tools.safe_insert", return_value={"inserted": 1})
    def test_insert_sets_mutation_flag(self, mock_insert, mock_sample, executor):
        assert executor.mutations_performed is False
        executor.execute("insert_rows", json.dumps({
            "table_name": "매출",
            "rows": [{"품목": "커피", "금액": 5000}],
        }))
        assert executor.mutations_performed is True
        assert "table-001" in executor.mutated_table_ids

    def test_read_does_not_set_mutation_flag(self, executor):
        executor.execute("list_tables", "{}")
        assert executor.mutations_performed is False
        assert len(executor.mutated_table_ids) == 0
