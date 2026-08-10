"""Tests for api/app/agent.py — suggestion parsing and tool selection."""

import pytest

from app.agent import _parse_suggestions


# ---------------------------------------------------------------------------
# _parse_suggestions
# ---------------------------------------------------------------------------

class TestParseSuggestions:
    def test_standard_marker(self):
        text = "결과입니다.\n\n---SUGGESTIONS---\n제안1|제안2|제안3"
        clean, suggestions = _parse_suggestions(text)
        assert clean == "결과입니다."
        assert suggestions == ["제안1", "제안2", "제안3"]

    def test_lowercase_marker(self):
        text = "결과.\n---suggestions---\n제안A|제안B|제안C"
        clean, suggestions = _parse_suggestions(text)
        assert clean == "결과."
        assert len(suggestions) == 3

    def test_korean_marker(self):
        text = "결과.\n---제안---\n제안1|제안2|제안3"
        clean, suggestions = _parse_suggestions(text)
        assert clean == "결과."
        assert suggestions == ["제안1", "제안2", "제안3"]

    def test_marker_with_whitespace(self):
        text = "결과.\n--- SUGGESTIONS ---\n제안1|제안2|제안3"
        clean, suggestions = _parse_suggestions(text)
        assert clean == "결과."
        assert len(suggestions) == 3

    def test_max_three_suggestions(self):
        text = "결과.\n---SUGGESTIONS---\n하나|둘|셋|넷"
        clean, suggestions = _parse_suggestions(text)
        assert len(suggestions) == 3

    def test_fallback_pipe_in_last_line(self):
        """No marker but last line has pipe separators → extract."""
        text = "결과입니다.\n매출 보기|차트 생성|데이터 추가"
        clean, suggestions = _parse_suggestions(text)
        assert clean == "결과입니다."
        assert len(suggestions) == 3

    def test_no_suggestions(self):
        text = "그냥 평범한 응답입니다."
        clean, suggestions = _parse_suggestions(text)
        assert clean == text
        assert suggestions == []

    def test_empty_string(self):
        clean, suggestions = _parse_suggestions("")
        assert clean == ""
        assert suggestions == []

    def test_single_pipe_not_enough(self):
        """Single item with no pipe → no suggestions."""
        text = "결과.\n하나만있음"
        clean, suggestions = _parse_suggestions(text)
        assert suggestions == []

    def test_strips_whitespace_from_suggestions(self):
        text = "결과.\n---SUGGESTIONS---\n 제안1 | 제안2 | 제안3 "
        clean, suggestions = _parse_suggestions(text)
        assert suggestions == ["제안1", "제안2", "제안3"]

    def test_multiline_answer_preserved(self):
        text = "첫째 줄.\n둘째 줄.\n셋째 줄.\n\n---SUGGESTIONS---\nA|B|C"
        clean, suggestions = _parse_suggestions(text)
        assert "첫째 줄" in clean
        assert "둘째 줄" in clean
        assert "셋째 줄" in clean
        assert "SUGGESTIONS" not in clean
