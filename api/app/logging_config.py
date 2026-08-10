"""Structured JSON logging configuration.

Call setup_logging() once at startup to configure all loggers to emit
JSON lines with standard fields: timestamp, level, message, logger,
and optional request_id / user_id from contextvars.
"""

import logging
import contextvars
from pythonjsonlogger.json import JsonFormatter

# Context vars for request-scoped fields
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")


class DataezJsonFormatter(JsonFormatter):
    """Adds request_id and user_id from contextvars to every log record."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["request_id"] = request_id_var.get("")
        log_record["user_id"] = user_id_var.get("")


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output."""
    formatter = DataezJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
