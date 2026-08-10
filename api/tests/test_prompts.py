"""Tests for api/app/prompts.py — System prompt building and context compression."""

import pytest

from app.prompts import (
    INTENT_PROMPT_ADDITIONS,
    MULTI_TABLE_SECTION,
    ONBOARDING_SECTION,
    build_conversation_context,
    build_system_prompt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SINGLE_TABLE = [
    {
        "name": "매출",
        "row_count": 100,
        "columns_schema": [
            {"name": "날짜", "type": "DATE"},
            {"name": "품목", "type": "TEXT"},
            {"name": "금액", "type": "BIGINT"},
        ],
    }
]

TWO_TABLES = SINGLE_TABLE + [
    {
        "name": "비용",
        "row_count": 80,
        "columns_schema": [
            {"name": "날짜", "type": "DATE"},
            {"name": "항목", "type": "TEXT"},
            {"name": "금액", "type": "BIGINT"},
        ],
    }
]


# ---------------------------------------------------------------------------
# build_system_prompt — conditional sections
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_no_tables_includes_onboarding(self):
        """0 tables → onboarding section included."""
        prompt = build_system_prompt("테스트", [])
        assert "온보딩" in prompt or "장부가 없" in prompt
        assert "장부 수: 0" in prompt

    def test_no_tables_excludes_multi_table(self):
        """0 tables → multi-table section NOT included."""
        prompt = build_system_prompt("테스트", [])
        assert "다중 장부 분석" not in prompt

    def test_single_table_no_onboarding(self):
        """1 table → no onboarding, no multi-table."""
        prompt = build_system_prompt("테스트", SINGLE_TABLE)
        assert "온보딩" not in prompt
        assert "다중 장부 분석" not in prompt

    def test_two_tables_includes_multi_table(self):
        """2+ tables → multi-table section included."""
        prompt = build_system_prompt("테스트", TWO_TABLES)
        assert "다중 장부 분석" in prompt

    def test_two_tables_no_onboarding(self):
        """2+ tables → no onboarding."""
        prompt = build_system_prompt("테스트", TWO_TABLES)
        assert "온보딩" not in prompt

    def test_project_name_injected(self):
        prompt = build_system_prompt("내가게", SINGLE_TABLE)
        assert "내가게" in prompt

    def test_table_info_in_prompt(self):
        """Table names and columns appear in the prompt."""
        prompt = build_system_prompt("테스트", SINGLE_TABLE)
        assert "매출" in prompt
        assert "날짜(DATE)" in prompt
        assert "100행" in prompt

    def test_intent_schema_addition(self):
        """schema intent → schema-specific instructions added."""
        prompt = build_system_prompt("테스트", SINGLE_TABLE, intent="schema")
        assert "구조" in prompt  # schema section mentions 구조 변경

    def test_intent_crud_addition(self):
        prompt = build_system_prompt("테스트", SINGLE_TABLE, intent="crud")
        assert "데이터 관리" in prompt or "describe_table" in prompt

    def test_intent_analysis_addition(self):
        prompt = build_system_prompt("테스트", SINGLE_TABLE, intent="analysis")
        assert "분석" in prompt

    def test_intent_general_no_extra(self):
        """general intent → no additional section (empty string)."""
        base = build_system_prompt("테스트", SINGLE_TABLE, intent="general")
        assert INTENT_PROMPT_ADDITIONS["general"] == ""

    def test_attachment_addition(self):
        prompt = build_system_prompt("테스트", SINGLE_TABLE, has_attachments=True)
        assert "첨부" in prompt or "CSV" in prompt

    def test_attachment_with_intent(self):
        """Attachment + intent should both be included."""
        prompt = build_system_prompt("테스트", SINGLE_TABLE, intent="crud", has_attachments=True)
        assert "첨부" in prompt
        assert "데이터 관리" in prompt or "describe_table" in prompt


# ---------------------------------------------------------------------------
# build_conversation_context
# ---------------------------------------------------------------------------

class TestBuildConversationContext:
    def test_empty_messages(self):
        assert build_conversation_context([]) == []

    def test_max_messages_limit(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        result = build_conversation_context(msgs, max_messages=5)
        assert len(result) == 5
        # Should keep the most recent 5
        assert result[0]["content"] == "msg15"

    def test_user_messages_not_truncated(self):
        long_msg = "x" * 2000
        msgs = [{"role": "user", "content": long_msg}]
        result = build_conversation_context(msgs, max_chars_per_message=800)
        assert result[0]["content"] == long_msg  # user msgs kept intact

    def test_assistant_messages_truncated(self):
        long_msg = "a" * 2000
        msgs = [{"role": "assistant", "content": long_msg}]
        result = build_conversation_context(msgs, max_chars_per_message=800)
        assert len(result[0]["content"]) < 2000
        assert "생략" in result[0]["content"]

    def test_short_assistant_not_truncated(self):
        short_msg = "짧은 응답입니다."
        msgs = [{"role": "assistant", "content": short_msg}]
        result = build_conversation_context(msgs, max_chars_per_message=800)
        assert result[0]["content"] == short_msg

    def test_preserves_message_order(self):
        msgs = [
            {"role": "user", "content": "질문1"},
            {"role": "assistant", "content": "답변1"},
            {"role": "user", "content": "질문2"},
        ]
        result = build_conversation_context(msgs)
        assert [m["role"] for m in result] == ["user", "assistant", "user"]
