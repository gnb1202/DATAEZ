"""Vercel entrypoint. Persistent Docker deployments keep app.main:app."""
import os

os.environ["RUNTIME_MODE"] = "serverless"
os.environ["APP_ENV"] = "production"

from app.main import app  # noqa: E402,F401
