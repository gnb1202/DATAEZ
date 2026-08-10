"""Tests for auth module — password hashing, token creation, and validation."""

import pytest
from unittest.mock import patch, MagicMock

from app.auth import (
    _hash_password,
    _verify_password,
    _validate_password_policy,
    create_access_token,
    _decode_token,
    _hash_token,
)
from fastapi import HTTPException


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "MySecurePass1!"
        hashed = _hash_password(password)
        assert _verify_password(password, hashed) is True

    def test_wrong_password_fails(self):
        hashed = _hash_password("CorrectPass1!")
        assert _verify_password("WrongPass1!", hashed) is False

    def test_hash_format(self):
        hashed = _hash_password("TestPass123!")
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1] == "200000"

    def test_malformed_hash_returns_false(self):
        assert _verify_password("any", "not-a-valid-hash") is False

    def test_wrong_algo_returns_false(self):
        assert _verify_password("any", "bcrypt$100$abc$def") is False

    def test_empty_password_verifies_correctly(self):
        hashed = _hash_password("")
        assert _verify_password("", hashed) is True
        assert _verify_password("notempty", hashed) is False


class TestPasswordPolicy:
    def test_valid_password(self):
        # Should not raise
        _validate_password_policy("MySecure1!pass")

    def test_too_short(self):
        with pytest.raises(HTTPException) as exc:
            _validate_password_policy("Short1!")
        assert exc.value.status_code == 400

    def test_no_lowercase(self):
        with pytest.raises(HTTPException):
            _validate_password_policy("ALLUPPER123!")

    def test_no_uppercase(self):
        with pytest.raises(HTTPException):
            _validate_password_policy("alllower123!")

    def test_no_digit(self):
        with pytest.raises(HTTPException):
            _validate_password_policy("NoDigitsHere!")

    def test_no_special_char(self):
        with pytest.raises(HTTPException):
            _validate_password_policy("NoSpecial123")


class TestTokens:
    def test_access_token_roundtrip(self):
        token = create_access_token(user_id="user-123", email="test@example.com")
        payload = _decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["token_type"] == "access"

    def test_invalid_token_raises(self):
        with pytest.raises(HTTPException) as exc:
            _decode_token("invalid.jwt.token")
        assert exc.value.status_code == 401

    def test_hash_token_deterministic(self):
        token = "some-token-value"
        assert _hash_token(token) == _hash_token(token)

    def test_hash_token_different_inputs(self):
        assert _hash_token("token-a") != _hash_token("token-b")
