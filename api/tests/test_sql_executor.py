"""Tests for sql_executor module — validation and query building."""

import pytest

from app.sql_executor import validate_table_access


class TestValidateTableAccess:
    def test_valid_access(self):
        user_id = "12345678-abcd-efgh-ijkl-mnopqrstuvwx"
        # ut_{first 8 chars of user_id without dashes}_{table_id}
        uid = user_id.replace("-", "")[:8]
        table_name = f"ut_{uid}_abc12345"
        assert validate_table_access(user_id, table_name) is True

    def test_wrong_user_prefix(self):
        assert validate_table_access("user-1234", "ut_00000000_abc") is False

    def test_no_ut_prefix(self):
        assert validate_table_access("12345678", "users") is False

    def test_empty_table_name(self):
        assert validate_table_access("12345678", "") is False

    def test_matching_uid_pattern(self):
        user_id = "aabbccdd-1122-3344-5566-778899001122"
        uid = user_id.replace("-", "")[:8]
        assert validate_table_access(user_id, f"ut_{uid}_test") is True
        assert validate_table_access(user_id, f"ut_XXXXXXXX_test") is False
