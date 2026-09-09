"""Tests for data_import module — schema inference and value casting."""

import pandas as pd
import pytest
from decimal import Decimal

from app.data_import import _cast_value, _sanitize_column_name, infer_columns_schema


class TestSanitizeColumnName:
    def test_simple_name(self):
        assert _sanitize_column_name("name") == "name"

    def test_strips_whitespace(self):
        assert _sanitize_column_name("  hello  ") == "hello"

    def test_replaces_special_chars(self):
        assert _sanitize_column_name("col@name!") == "col_name"

    def test_removes_leading_digits(self):
        assert _sanitize_column_name("123abc") == "abc"

    def test_collapses_underscores(self):
        assert _sanitize_column_name("a__b___c") == "a_b_c"

    def test_empty_becomes_col(self):
        assert _sanitize_column_name("@#$") == "col"

    def test_korean_chars_preserved(self):
        assert _sanitize_column_name("매출액") == "매출액"

    def test_mixed_korean_english(self):
        assert _sanitize_column_name("매출_amount") == "매출_amount"

    def test_spaces_to_underscore(self):
        assert _sanitize_column_name("first name") == "first_name"


class TestCastValue:
    def test_none_returns_none(self):
        assert _cast_value(None, "TEXT") is None

    def test_bigint(self):
        assert _cast_value("42", "BIGINT") == 42

    def test_bigint_from_float(self):
        with pytest.raises(ValueError):
            _cast_value("42.7", "BIGINT")

    def test_numeric(self):
        assert _cast_value("3.14", "NUMERIC(10,2)") == Decimal("3.14")

    def test_boolean(self):
        assert _cast_value(True, "BOOLEAN") is True

    def test_text(self):
        assert _cast_value(123, "TEXT") == "123"

    def test_date_valid(self):
        result = _cast_value("2024-01-15", "DATE")
        assert result == "2024-01-15"

    def test_date_invalid(self):
        with pytest.raises(ValueError):
            _cast_value("not-a-date", "DATE")

    def test_timestamp_valid(self):
        result = _cast_value("2024-01-15 10:30:00", "TIMESTAMP")
        assert result is not None
        assert "2024-01-15" in result

    def test_invalid_bigint_fallback(self):
        with pytest.raises(ValueError):
            _cast_value("abc", "BIGINT")


class TestInferColumnsSchema:
    def test_basic_types(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [25, 30],
            "score": [95.5, 88.0],
        })
        schema = infer_columns_schema(df)
        names = {col["name"]: col["type"] for col in schema}
        assert names["name"] == "TEXT"
        assert names["age"] == "BIGINT"
        assert names["score"].startswith("NUMERIC")

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        schema = infer_columns_schema(df)
        assert schema == []

    def test_boolean_column(self):
        df = pd.DataFrame({"flag": [True, False, True]})
        schema = infer_columns_schema(df)
        assert schema[0]["type"] == "BOOLEAN"

    def test_column_name_sanitized(self):
        df = pd.DataFrame({"First Name!": ["Alice"]})
        schema = infer_columns_schema(df)
        assert schema[0]["name"] == "first_name"
