"""Shared fixtures for DATAEZ API tests."""

import os
import sys

# Ensure api package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out heavy dependencies before any app module import
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-unit-tests")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-unit-tests-only")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("S3_BUCKET", "test-bucket")
