"""Serverless boot must never perform DDL or start persistent background work."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from app.config import Settings


def serverless(**overrides):
    return Settings(runtime_mode="serverless", storage_backend="s3", s3_bucket="test-bucket", **overrides)


def test_serverless_defaults():
    config = serverless()
    assert (config.db_pool_min_size, config.db_pool_max_size, config.db_pool_timeout) == (0, 2, 5)
    assert config.db_prepared_statements is False
    assert not any((config.startup_migrations_enabled, config.metric_scheduler_enabled,
                    config.index_worker_enabled, config.import_cleanup_enabled))


@pytest.mark.parametrize("override", [
    {"startup_migrations_enabled": True}, {"metric_scheduler_enabled": True},
    {"index_worker_enabled": True}, {"import_cleanup_enabled": True},
    {"db_prepared_statements": True}, {"db_pool_min_size": 3, "db_pool_max_size": 2},
    {"db_pool_timeout": 0},
])
def test_incompatible_serverless_settings_rejected(override):
    with pytest.raises(ValidationError):
        serverless(**override)


def test_serverless_rejects_local_storage():
    with pytest.raises(ValidationError, match="durable"):
        Settings(runtime_mode="serverless", storage_backend="local")


def test_serverless_boot_without_database_or_workers(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "settings", serverless())
    initialize, scheduler, indexing, cleanup, close = [Mock() for _ in range(5)]
    for name, mock in [("initialize_database", initialize), ("run_metric_scheduler", scheduler),
                       ("run_index_worker", indexing), ("run_import_cleanup", cleanup), ("close_pool", close)]:
        monkeypatch.setattr(main, name, mock)

    async def boot_twice():
        for _ in range(2):
            async with main.lifespan(main.app):
                assert main.health()["status"] == "ok"
    asyncio.run(boot_twice())
    for mock in (initialize, scheduler, indexing, cleanup):
        mock.assert_not_called()
    assert close.call_count == 2


def test_concurrent_pool_initialization_and_transaction_settings(monkeypatch):
    from app import db
    monkeypatch.setattr(db, "settings", serverless())
    monkeypatch.setattr(db, "_pool", None)
    with patch.object(db, "ConnectionPool") as factory:
        with ThreadPoolExecutor(max_workers=8) as executor:
            pools = list(executor.map(lambda _: db.get_pool(), range(24)))
        assert all(pool is pools[0] for pool in pools)
        factory.assert_called_once()
        assert factory.call_args.kwargs["kwargs"]["prepare_threshold"] is None
        assert factory.call_args.kwargs["check"] is factory.check_connection
        assert factory.call_args.kwargs["min_size"] == 0
        db.close_pool()
        factory.return_value.close.assert_called_once()


def test_persistent_runtime_keeps_startup_migrations():
    config = Settings(runtime_mode="persistent")
    assert config.startup_migrations_enabled
    assert config.db_prepared_statements
    assert (config.db_pool_min_size, config.db_pool_max_size) == (2, 10)
