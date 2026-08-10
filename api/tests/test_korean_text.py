"""Tests for Korean tokenization and token counting.

The behaviour under test is the bug this replaced: under to_tsvector('simple'),
매출이 / 매출을 / 매출 are three unrelated tokens, so a query for 매출 matched
none of them and the sparse half of the hybrid search never fired.
"""

import pytest

from app.korean_text import to_tsquery_input, to_tsvector_input, tokenize_korean
from app.tokens import count_tokens, estimate_tokens, truncate_to_tokens


class TestKoreanTokenization:
    def test_particles_are_stripped_so_inflections_match(self):
        """The core fix: the same noun under different particles shares a token."""
        with_subject = set(tokenize_korean("매출이 얼마야"))
        with_object = set(tokenize_korean("매출을 보여줘"))
        bare = set(tokenize_korean("매출"))

        assert "매출" in with_subject
        assert "매출" in with_object
        assert "매출" in bare

    def test_query_and_index_analysis_agree(self):
        """A query analysed differently from the index cannot match it."""
        indexed = set(to_tsvector_input("작년 매출이 크게 늘었습니다").split())
        queried = set(to_tsquery_input("매출").split())
        assert queried & indexed

    def test_whitespace_split_would_have_missed_this(self):
        """Documents the old behaviour, so a regression is visible."""
        naive = set("매출이 얼마야".split())
        assert "매출" not in naive  # the old index had no such token
        assert "매출" in set(tokenize_korean("매출이 얼마야"))

    def test_ascii_identifiers_survive_intact(self):
        tokens = tokenize_korean("order_id 컬럼과 CSV 파일")
        assert "order_id" in tokens
        assert "csv" in tokens

    def test_empty_input(self):
        assert tokenize_korean("") == []
        assert tokenize_korean("   ") == []
        assert to_tsvector_input("") == ""

    def test_punctuation_is_not_indexed(self):
        assert all(t not in {".", ",", "?", "!"} for t in tokenize_korean("매출은?"))

    def test_tokens_are_deduplicated(self):
        tokens = tokenize_korean("매출 매출 매출")
        assert tokens.count("매출") == 1

    def test_mixed_korean_english_query(self):
        tokens = set(tokenize_korean("2025년 CSV 매출 데이터"))
        assert "매출" in tokens
        assert "csv" in tokens


class TestTokenCounting:
    def test_korean_costs_more_than_one_token_per_char(self):
        """Why the character-based budget underestimated so badly."""
        text = "안녕하세요 반갑습니다"
        assert count_tokens(text) > 0
        # A character count would be an underestimate for Korean.
        assert count_tokens(text * 10) > count_tokens(text)

    def test_empty_text_is_zero(self):
        assert count_tokens("") == 0

    def test_estimate_is_positive_for_korean(self):
        assert estimate_tokens("매출 분석") > 0

    def test_truncation_respects_the_limit(self):
        text = "매출 분석 결과입니다. " * 50
        truncated = truncate_to_tokens(text, 20)
        assert count_tokens(truncated) <= 20
        assert len(truncated) < len(text)

    def test_short_text_is_not_truncated(self):
        text = "짧은 문장"
        assert truncate_to_tokens(text, 1000) == text

    def test_zero_limit_yields_empty(self):
        assert truncate_to_tokens("아무거나", 0) == ""
