"""Tests for api/app/router.py — Orchestrator tool selection."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agent_tools import TOOL_SPECS
from app.router import (
    SAFE_FALLBACK_TOOLS,
    OrchestratorResult,
    _is_pure_greeting,
    select_tools_via_orchestrator,
)

# Derived from the real specs rather than hand-listed. The previous literal
# had gone stale, omitting search_schema and search_documents, so tests could
# not observe routing decisions involving the RAG tools at all.
ALL_TOOLS = [spec["function"]["name"] for spec in TOOL_SPECS]


# ---------------------------------------------------------------------------
# _is_pure_greeting
# ---------------------------------------------------------------------------

class TestIsPureGreeting:
    def test_pure_greeting_korean(self):
        assert _is_pure_greeting("안녕하세요") is True

    def test_pure_greeting_english(self):
        assert _is_pure_greeting("hello") is True
        assert _is_pure_greeting("Hi there") is True

    def test_greeting_with_data_keyword(self):
        """Greeting + data keyword → NOT pure greeting."""
        assert _is_pure_greeting("안녕, 데이터 보여줘") is False

    def test_data_only(self):
        """Data keyword without greeting → NOT pure greeting."""
        assert _is_pure_greeting("매출 데이터 보여줘") is False

    def test_no_keywords(self):
        """Neither greeting nor data → NOT pure greeting."""
        assert _is_pure_greeting("오늘 날씨 어때?") is False

    def test_empty_string(self):
        assert _is_pure_greeting("") is False

    def test_usage_help(self):
        assert _is_pure_greeting("사용법 알려줘") is False  # "알려" is data kw

    def test_usage_help_pure(self):
        assert _is_pure_greeting("도움말") is True  # greeting kw only

    def test_case_insensitive(self):
        assert _is_pure_greeting("HELLO") is True
        assert _is_pure_greeting("Hello") is True


# ---------------------------------------------------------------------------
# select_tools_via_orchestrator — pre-filter paths
# ---------------------------------------------------------------------------

class TestOrchestratorPreFilters:
    def test_pure_greeting_skips_llm(self):
        """Pure greeting should return empty tools without calling LLM."""
        result = select_tools_via_orchestrator("안녕하세요", False, ALL_TOOLS)
        assert isinstance(result, OrchestratorResult)
        assert result.tools == []
        assert result.intent == "general"

    def test_attachment_forces_import(self):
        """Attachment present → force import_file tools, no LLM call."""
        result = select_tools_via_orchestrator("파일 올려줘", True, ALL_TOOLS)
        assert isinstance(result, OrchestratorResult)
        assert "import_file" in result.tools
        assert "list_tables" in result.tools
        assert result.intent == "crud"

    @patch("app.router.settings")
    def test_no_api_key_returns_safe_fallback(self, mock_settings):
        """No API key → degraded routing over the read-only safe set."""
        mock_settings.openai_api_key = ""
        result = select_tools_via_orchestrator("매출 보여줘", False, ALL_TOOLS)
        assert result.degraded is True
        assert set(result.tools) == set(SAFE_FALLBACK_TOOLS)
        assert result.intent == "general"


# ---------------------------------------------------------------------------
# select_tools_via_orchestrator — LLM response parsing
# ---------------------------------------------------------------------------

class TestOrchestratorLLMParsing:
    def _mock_openai_response(self, content: str):
        """Create a mock OpenAI chat completion response."""
        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    @patch("app.router.get_openai_client")
    def test_new_format_dict(self, mock_get_client):
        """New JSON dict format: {"intent": "...", "tools": [...]}."""
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            json.dumps({"intent": "crud", "tools": ["query_data", "insert_rows"]})
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("매출 추가해줘", False, ALL_TOOLS)
        assert result.intent == "crud"
        assert set(result.tools) == {"query_data", "insert_rows"}

    @patch("app.router.get_openai_client")
    def test_bare_array_is_now_rejected(self, mock_get_client):
        """The old bare-array format is no longer accepted.

        The response schema requires an object, so an array is malformed and
        routing degrades rather than silently guessing an intent.
        """
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            json.dumps(["query_data", "generate_chart"])
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("차트 보여줘", False, ALL_TOOLS)
        # The bare-array format is no longer accepted: the response schema
        # requires an object, so an array is a malformed response.
        assert result.degraded is True

    @patch("app.router.get_openai_client")
    def test_invalid_tool_names_filtered(self, mock_get_client):
        """Tool names not in valid list should be filtered out."""
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            json.dumps({"intent": "analysis", "tools": ["query_data", "nonexistent_tool"]})
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("분석해줘", False, ALL_TOOLS)
        assert "nonexistent_tool" not in result.tools
        assert "query_data" in result.tools

    @patch("app.router.get_openai_client")
    def test_invalid_intent_defaults_to_general(self, mock_get_client):
        """Invalid intent string should default to 'general'."""
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            json.dumps({"intent": "invalid_intent", "tools": ["query_data"]})
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("뭔가 해줘", False, ALL_TOOLS)
        assert result.intent == "general"

    @patch("app.router.get_openai_client")
    def test_json_parse_failure_degrades_to_read_only_tools(self, mock_get_client):
        """Malformed JSON → retry, then the read-only safe set.

        Handing back all 14 tools (the previous behaviour) meant a parse
        failure exposed delete_rows and alter_table while the caller was also
        forcing a tool call.
        """
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            "이건 JSON이 아닙니다"
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("매출 보여줘", False, ALL_TOOLS)
        assert result.degraded is True
        assert set(result.tools) == set(SAFE_FALLBACK_TOOLS)
        assert "delete_rows" not in result.tools
        assert "alter_table" not in result.tools
        assert client.chat.completions.create.call_count == 2  # one retry

    @patch("app.router.get_openai_client")
    def test_api_exception_degrades_after_retry(self, mock_get_client):
        """OpenAI API exception → one retry, then the read-only safe set."""
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("API down")
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("매출 보여줘", False, ALL_TOOLS)
        assert result.degraded is True
        assert set(result.tools) == set(SAFE_FALLBACK_TOOLS)
        assert client.chat.completions.create.call_count == 2

    @patch("app.router.get_openai_client")
    def test_transient_failure_recovers_on_retry(self, mock_get_client):
        """A single bad response must not discard routing for the whole turn."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            self._mock_openai_response("not json"),
            self._mock_openai_response(
                json.dumps({"intent": "analysis", "tools": ["query_data"]})
            ),
        ]
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("매출 보여줘", False, ALL_TOOLS)
        assert result.degraded is False
        assert result.tools == ["query_data"]
        assert result.intent == "analysis"

    @patch("app.router.get_openai_client")
    def test_empty_tools_list(self, mock_get_client):
        """LLM returns empty tools → general intent, no tools."""
        client = MagicMock()
        client.chat.completions.create.return_value = self._mock_openai_response(
            json.dumps({"intent": "general", "tools": []})
        )
        mock_get_client.return_value = client

        result = select_tools_via_orchestrator("오늘 날씨 어때?", False, ALL_TOOLS)
        assert result.tools == []
        assert result.intent == "general"
