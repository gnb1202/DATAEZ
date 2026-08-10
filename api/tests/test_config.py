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


_BASE_ENV = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "OPENAI_API_KEY": "test-key",
    "JWT_SECRET_KEY": "a-secure-secret-for-testing-only",
}


def _settings(**overrides):
    """Build a Settings instance from _BASE_ENV plus overrides."""
    from app.config import Settings

    with pytest.MonkeyPatch.context() as mp:
        for k, v in {**_BASE_ENV, **overrides}.items():
            mp.setenv(k, v)
        return Settings()


class TestLocalFirstDefaults:
    """A fresh clone must run without any AWS configuration."""

    def test_storage_backend_defaults_to_local(self):
        s = _settings()
        assert s.storage_backend == "local"
        assert s.local_storage_path

    def test_local_backend_needs_no_s3_bucket(self):
        s = _settings(STORAGE_BACKEND="local", S3_BUCKET="")
        assert s.storage_backend == "local"

    def test_unknown_storage_backend_rejected(self):
        with pytest.raises(ValidationError):
            _settings(STORAGE_BACKEND="gcs")


class TestEnvAwareSecretValidation:
    """The dev secret shipped in .env.example must not survive production."""

    DEV_SECRET = "dev-insecure-local-jwt-secret-do-not-deploy"

    def test_dev_secret_allowed_in_development(self):
        s = _settings(APP_ENV="development", JWT_SECRET_KEY=self.DEV_SECRET)
        assert s.is_production is False

    def test_dev_secret_rejected_in_production(self):
        with pytest.raises(ValidationError):
            _settings(APP_ENV="production", JWT_SECRET_KEY=self.DEV_SECRET)

    def test_short_secret_rejected_in_production(self):
        with pytest.raises(ValidationError):
            _settings(APP_ENV="production", JWT_SECRET_KEY="short")

    def test_strong_secret_accepted_in_production(self):
        strong = "Yb3xQm7Lp2Rv9Kt4Wn8Cz6Hs1Jf5Dg0Ae"
        s = _settings(APP_ENV="production", JWT_SECRET_KEY=strong)
        assert s.is_production is True

    def test_placeholder_secret_rejected_everywhere(self):
        with pytest.raises(ValidationError):
            _settings(APP_ENV="development", JWT_SECRET_KEY="change-this-in-production")
