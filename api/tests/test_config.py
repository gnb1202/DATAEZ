"""Tests for config module — settings validation."""

import os
import pytest

from pydantic import ValidationError


class TestSettings:
    def test_jwt_secret_must_be_set(self):
        """Empty JWT_SECRET_KEY should fail validation."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "OPENAI_API_KEY": "test-key",
            "JWT_SECRET_KEY": "",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            # Need to reimport to trigger validation
            from app.config import Settings
            with pytest.raises(ValidationError):
                Settings()

    def test_jwt_secret_change_this_rejected(self):
        """Default placeholder value should fail validation."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "OPENAI_API_KEY": "test-key",
            "JWT_SECRET_KEY": "change-this-in-production",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            from app.config import Settings
            with pytest.raises(ValidationError):
                Settings()

    def test_valid_config(self):
        """Valid settings should not raise."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "OPENAI_API_KEY": "test-key",
            "JWT_SECRET_KEY": "a-secure-secret-for-testing-only",
            "STORAGE_BACKEND": "local",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            from app.config import Settings
            s = Settings()
            assert s.agent_max_iterations == 25
            assert s.agent_max_token_budget == 100_000
            assert s.max_select_rows == 10_000
            assert s.query_timeout_ms == 30_000
            assert s.conversation_ttl_days == 90

    def test_s3_bucket_required_when_s3_backend(self):
        """S3_BUCKET must be set when STORAGE_BACKEND=s3."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "OPENAI_API_KEY": "test-key",
            "JWT_SECRET_KEY": "a-secure-secret-for-testing-only",
            "STORAGE_BACKEND": "s3",
            "S3_BUCKET": "",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            from app.config import Settings
            with pytest.raises(ValidationError):
                Settings()

    def test_openai_key_required(self):
        """OPENAI_API_KEY must be set."""
        env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "OPENAI_API_KEY": "",
            "JWT_SECRET_KEY": "a-secure-secret-for-testing-only",
            "STORAGE_BACKEND": "local",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)
            from app.config import Settings
            with pytest.raises(ValidationError):
                Settings()
