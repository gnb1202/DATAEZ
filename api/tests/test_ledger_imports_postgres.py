"""Durable B-stage behavior on real PostgreSQL, including independent clients."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app import db, ledger_imports as service, sql_executor, table_imports
from app.exceptions import AppException
from app.import_validation import ImportValidationError
from app.storage import StorageService
from .test_import_postgres import live, DSN

pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for durable batch tests")
CONTENT = b"id,money,day\n0001,100000,2026-09-01\n0002,200000,2026-09-01\n0003,-50000,2026-09-02\n"
NEXT = b"id,money,day\n0004,50000,2026-09-03\n"


@pytest.fixture
def env(live, monkeypatch, tmp_path):
    connect, _, user, store, other = live
    for module in (service, sql_executor):
        monkeypatch.setattr(module, "_connect", connect)
    from app.config import settings
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    storage = StorageService()
    return connect, storage, user, store, other


def source(env, store=None, **overrides):
    _, _, user, default_store, _ = env
    payload = {"name": "카드 장부", "provider": "카드사A", "account": "가맹점1", "feed": "결제·취소 이벤트",
               "mapping": {"amount_column": "money", "occurred_at_column": "day", "event_id_column": "id", "event_kind": "signed"}}
    payload.update(overrides)
    return service.create_source(user, store or default_store, service.CreateSourceRequest(**payload))


def upload(env, src, content=CONTENT, request_key=None, filename="payments.csv"):
    _, storage, user, store, _ = env
    return service.upload_batch(user, str(src["project_id"]), str(src["id"]), request_key or str(uuid4()), content, filename, storage)


def preview(env, batch):
    _, storage, user, store, _ = env
    return service.preview_batch(user, store, str(batch["id"]), storage)


def commit(env, batch):
    _, storage, user, store, _ = env
    return service.commit_batch(user, store, str(batch["id"]), str(batch["preview_token"]), storage)


def state(env, src):
    connect, _, user, *_ = env
    with connect() as conn:
        rows = conn.execute(sql.SQL("SELECT event_id,amount FROM {} ORDER BY _row_id").format(
            sql.Identifier(db.get_user_table_name(user, str(src["table_id"]))))).fetchall()
        meta = conn.execute("SELECT row_count FROM table_meta WHERE id=%s", (src["table_id"],)).fetchone()
        revision = conn.execute("SELECT data_revision FROM ledger_sources WHERE id=%s", (src["id"],)).fetchone()
    assert len(rows) == meta["row_count"]
    return rows, revision["data_revision"]


def test_source_retries_and_concurrent_namespace_creation_are_stable(env):
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = list(pool.map(lambda _: source(env), range(2)))
    assert sources[0]["id"] == sources[1]["id"]
    assert len(service.list_sources(env[2], env[3])) == 1
    with pytest.raises(AppException) as exc:
        source(env, name="다른 이름")
    assert exc.value.status_code == 409


def test_same_file_rename_and_lost_response_replay_original_result(env):
    src = source(env)
    key = str(uuid4())
    first = preview(env, upload(env, src, request_key=key))
    assert first["summary"]["amount"] == "250000"
    saved = commit(env, first)
    again = upload(env, src, filename="renamed.csv")
    retry = upload(env, src, request_key=key)
    assert again["id"] == retry["id"] == first["id"]
    assert saved["rows_added"] == 3
    assert again["replayed"] and again["rows_added"] == 0
    assert saved["result"] == again["result"] == retry["result"]
    assert commit(env, first)["rows_added"] == 0
    assert state(env, src)[1] == 1
    history = service.list_batches(env[2], env[3], str(src["id"]))
    assert history["total"] == 1 and history["batches"][0]["filename"] == "payments.csv"


def test_concurrent_upload_and_commit_only_write_once(env):
    src = source(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(lambda _: upload(env, src), range(2)))
    assert batches[0]["id"] == batches[1]["id"]
    ready = preview(env, batches[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: commit(env, ready), range(2)))
    assert sorted(r["rows_added"] for r in results) == [0, 3]
    assert len(state(env, src)[0]) == 3


def test_request_key_cannot_be_reused_for_different_bytes(env):
    src = source(env)
    key = str(uuid4())
    upload(env, src, request_key=key)
    with pytest.raises(AppException) as exc:
        upload(env, src, content=NEXT, request_key=key)
    assert exc.value.code == "idempotency_mismatch"


def test_same_bytes_in_other_store_remain_independent(env):
    first, second = source(env), source(env, store=env[4])
    commit(env, preview(env, upload(env, first)))
    batch = upload(env, second)
    assert batch["status"] == "uploaded" and batch["same_file_sources"] == []
    ready = service.preview_batch(env[2], env[4], str(batch["id"]), env[1])
    result = service.commit_batch(env[2], env[4], str(batch["id"]), str(ready["preview_token"]), env[1])
    assert result["rows_added"] == 3
    assert len(state(env, second)[0]) == 3


def test_same_bytes_in_different_source_show_candidate_without_auto_exclusion(env):
    first, second = source(env), source(env, account="가맹점2")
    commit(env, preview(env, upload(env, first)))
    uploaded = upload(env, second)
    assert uploaded["same_file_sources"] == [{"source_id": first["id"], "source_name": first["name"]}]
    assert commit(env, preview(env, uploaded))["rows_added"] == 3


@pytest.mark.parametrize("foreign_user", [False, True])
def test_foreign_scope_cannot_read_preview_commit_or_upload(env, foreign_user):
    src = source(env)
    batch = preview(env, upload(env, src))
    user = str(uuid4()) if foreign_user else env[2]
    store = env[3] if foreign_user else env[4]
    calls = [lambda: service.get_batch(user, store, batch["id"]),
             lambda: service.preview_batch(user, store, batch["id"], env[1]),
             lambda: service.commit_batch(user, store, batch["id"], batch["preview_token"], env[1]),
             lambda: service.list_batches(user, store, src["id"]),
             lambda: service.upload_batch(user, store, src["id"], str(uuid4()), CONTENT, "file.csv", env[1])]
    for call in calls:
        with pytest.raises(AppException) as exc:
            call()
        assert exc.value.status_code == 404
    assert state(env, src) == ([], 0)


def test_stale_preview_requires_recheck_but_successful_retry_ignores_staleness(env):
    src = source(env)
    first = preview(env, upload(env, src))
    second = preview(env, upload(env, src, content=NEXT))
    commit(env, first)
    with pytest.raises(AppException) as exc:
        commit(env, second)
    assert exc.value.code == "stale_preview"
    commit(env, preview(env, second))
    replay = service.commit_batch(env[2], env[3], first["id"], str(uuid4()), env[1])
    assert replay["rows_added"] == 0 and replay["result"]["data_revision"] == 1
    assert sum(row["amount"] for row in state(env, src)[0]) == Decimal(300000)


def test_failed_partial_insert_rolls_back_rows_counts_revision_and_batch(env):
    src = source(env)
    ready = preview(env, upload(env, src))
    name = db.get_user_table_name(env[2], str(src["table_id"]))
    with env[0]() as conn:
        conn.execute(sql.SQL("ALTER TABLE {} ADD CHECK (amount >= 0)").format(sql.Identifier(name)))
    with pytest.raises(psycopg.errors.CheckViolation):
        commit(env, ready)
    assert state(env, src) == ([], 0)
    stored = service.get_batch(env[2], env[3], ready["id"])
    assert stored["status"] == "ready" and stored["result"] is None
    assert env[1].read_staged(StorageService.staged_key(str(ready["id"]))) == CONTENT
    with env[0]() as conn:
        assert conn.execute("SELECT count(*) AS n FROM files").fetchone()["n"] == 0


def test_validation_error_retains_actionable_history_and_zero_rows(env):
    src = source(env)
    batch = upload(env, src, content=b"id,money,day\n001,100,2026-09-01\n002,NaN,2026-09-02\n")
    with pytest.raises(ImportValidationError) as exc:
        preview(env, batch)
    assert exc.value.issues[0]["row"] == 3
    stored = service.get_batch(env[2], env[3], batch["id"])
    assert stored["status"] == "failed" and stored["error"]["issues"][0]["column"] == "money"
    assert state(env, src) == ([], 0)


def test_expired_pending_file_cleanup_reupload_and_committed_retention(env):
    src = source(env)
    committed = commit(env, preview(env, upload(env, src)))
    pending = preview(env, upload(env, src, content=NEXT))
    with env[0]() as conn:
        conn.execute("UPDATE import_batches SET expires_at=now()-interval '1 hour'")
    with pytest.raises(AppException) as exc:
        commit(env, pending)
    assert exc.value.code == "batch_expired"
    assert service.expire_pending_batches(env[1]) == 1
    assert env[1].read_staged(StorageService.staged_key(str(committed["id"]))) == CONTENT
    with pytest.raises(FileNotFoundError):
        env[1].read_staged(StorageService.staged_key(str(pending["id"])))
    again = upload(env, src, content=NEXT)
    assert again["id"] == pending["id"] and again["status"] == "uploaded"
    assert commit(env, preview(env, again))["rows_added"] == 1
    assert commit(env, committed)["replayed"]


def test_crash_after_object_write_is_durably_recoverable(env, monkeypatch):
    src = source(env)
    real_write = env[1].write_staged
    def interrupted(key, content):
        real_write(key, content)
        raise RuntimeError("process lost before DB finalization")
    monkeypatch.setattr(env[1], "write_staged", interrupted)
    with pytest.raises(RuntimeError):
        upload(env, src)
    history = service.list_batches(env[2], env[3], src["id"])
    assert history["total"] == 1 and history["batches"][0]["status"] == "staging"
    monkeypatch.setattr(env[1], "write_staged", real_write)
    retried = upload(env, src)
    assert retried["id"] == history["batches"][0]["id"]
    assert commit(env, preview(env, retried))["rows_added"] == 3


def test_cleanup_after_crashed_upload_removes_unfinalized_object(env, monkeypatch):
    src = source(env)
    real_write = env[1].write_staged
    def interrupted(key, content):
        real_write(key, content)
        raise RuntimeError("interrupted")
    monkeypatch.setattr(env[1], "write_staged", interrupted)
    with pytest.raises(RuntimeError):
        upload(env, src)
    with env[0]() as conn:
        conn.execute("UPDATE import_batches SET expires_at=now()-interval '1 hour'")
    assert service.expire_pending_batches(env[1]) == 1
    assert list(env[1]._local_root.rglob("*.bin")) == []


def test_decimal_preview_and_storage_keep_more_than_28_digits(env):
    src = source(env)
    batch = preview(env, upload(env, src, content=b"id,money,day\n00012345678901234567890,123456789012345678901234567890.01,2026-09-01\n002,0.02,2026-09-01\n"))
    assert batch["summary"]["amount"] == "123456789012345678901234567890.03"
    commit(env, batch)
    assert state(env, src)[0][0] == {"event_id": "00012345678901234567890", "amount": Decimal("123456789012345678901234567890.01")}


def test_idless_equal_rows_are_preserved_after_explicit_inclusion(env):
    src = source(env, mapping={"amount_column": "money", "occurred_at_column": "day"})
    ready = preview(env, upload(env, src, content=b"money,day\n100,2026-09-01\n100,2026-09-01\n"))
    from app.ledger_routes import RowDecision
    ready = service.decide_rows(env[2], env[3], ready["id"], ready["preview_token"], [RowDecision(row_number=3, decision="include")])
    result = commit(env, ready)
    assert result["rows_added"] == 2 and result["deduplication_scope"] == "source_events_v1"


@pytest.mark.parametrize("operation", ["insert", "update", "delete", "alter", "append", "drop", "delete_meta", "schema_meta", "count_meta"])
def test_generic_mutation_paths_cannot_bypass_managed_ledger(env, operation):
    src = source(env)
    name = db.get_user_table_name(env[2], str(src["table_id"]))
    calls = {
        "insert": lambda: sql_executor.safe_insert(name, env[2], [{"amount": 1}]),
        "update": lambda: sql_executor.safe_update(name, env[2], {"amount": 1}, [{"column": "_row_id", "operator": "=", "value": "1"}]),
        "delete": lambda: sql_executor.safe_delete(name, env[2], [{"column": "_row_id", "operator": "=", "value": "1"}]),
        "alter": lambda: sql_executor.safe_alter_table(name, env[2], "drop_column", "amount"),
        "append": lambda: table_imports.append_imported_table(env[2], env[3], str(src["table_id"]), CONTENT, "test.csv"),
        "drop": lambda: db.drop_user_data_table(env[2], str(src["table_id"])),
        "delete_meta": lambda: db.delete_table_meta(str(src["table_id"]), env[2]),
        "schema_meta": lambda: db.update_table_meta(str(src["table_id"]), env[2], columns_schema=[]),
        "count_meta": lambda: db.update_table_meta(str(src["table_id"]), env[2], row_count=999),
    }
    with pytest.raises(AppException) as exc:
        calls[operation]()
    assert exc.value.code == "managed_ledger"
    assert state(env, src) == ([], 0)


def test_http_flow_and_json_money_roundtrip(env, monkeypatch):
    from app import main, ledger_routes
    from app.auth import get_current_user
    monkeypatch.setattr(ledger_routes, "storage", env[1])
    main.app.dependency_overrides[get_current_user] = lambda: {"id": env[2]}
    try:
        client = TestClient(main.app)
        base = f"/api/projects/{env[3]}"
        src = source(env)
        response = client.post(base + "/imports", data={"source_id": str(src["id"]), "request_key": str(uuid4())}, files={"file": ("pay.csv", CONTENT)})
        assert response.status_code == 200
        bid = response.json()["id"]
        ready = client.post(base + f"/imports/{bid}/preview")
        assert ready.status_code == 200 and ready.json()["summary"]["amount"] == "250000"
        result = client.post(base + f"/imports/{bid}/commit", json={"preview_token": ready.json()["preview_token"]})
        assert result.status_code == 200 and result.json()["rows_added"] == 3
        assert client.get(base + f"/imports/{bid}").json()["result"]["amount"] == "250000"
        assert client.get(base + "/imports", params={"source_id": str(src["id"])}).json()["total"] == 1
        rows = client.get(base + f"/tables/{src['table_id']}/data")
        assert rows.status_code == 200
        assert rows.json()["rows"][0]["event_id"] == "0001"
        assert rows.json()["rows"][0]["amount"] == "100000"
        denied = client.post(base + f"/tables/{src['table_id']}/append", files={"file": ("pay.csv", CONTENT)})
        assert denied.status_code == 409
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_migration_and_startup_ddl_remain_identical(env):
    from pathlib import Path
    from app.ledger_schema import DDL
    text = (Path(__file__).resolve().parents[2] / "db/migrations/004_ledger_imports.sql").read_text(encoding="utf-8")
    assert text.split("\n", 1)[1] == DDL
    db.ensure_ledger_import_tables()  # repeat startup is safe


def test_original_file_deletion_and_deleted_store_cleanup_preserve_committed_history(env):
    src = source(env)
    saved = commit(env, preview(env, upload(env, src)))
    with pytest.raises(AppException) as exc:
        db.delete_file(env[2], str(saved["file_id"]))
    assert exc.value.code == "managed_import_file"
    assert not db.delete_file(str(uuid4()), str(saved["file_id"]))
    db.delete_project(env[3], env[2])
    with env[0]() as conn:
        conn.execute("UPDATE projects SET deleted_at=now()-interval '40 days' WHERE id=%s", (env[3],))
        conn.execute("UPDATE table_meta SET deleted_at=now()-interval '40 days'")
    db.purge_soft_deleted()
    assert state(env, src)[1] == 1
    with pytest.raises(AppException) as exc:
        service.get_batch(env[2], env[3], saved["id"])
    assert exc.value.status_code == 404


def test_chat_write_returns_actionable_managed_error(env, monkeypatch):
    from app import agent_tools
    src = source(env)
    monkeypatch.setattr(agent_tools.ToolExecutor, "_auto_describe_if_needed", lambda *_: None)
    executor = agent_tools.ToolExecutor(env[2], env[3])
    result = executor.execute("insert_rows", json.dumps({"table_name": src["name"], "rows": [{"amount": 100}]}))
    assert result["error"] == "managed_ledger"
    assert "출처 업로드" in result["message"]
    assert not executor.mutations_performed


def test_committed_source_stable_table_updates_saved_metric(env):
    from app import dashboard_metrics as metrics
    src = source(env)
    commit(env, preview(env, upload(env, src)))
    saved = metrics.create_saved_metric(env[3], env[2], metrics.CreateMetricRequest(title="결제 합계",
        definition={"table_id": str(src["table_id"]), "column": "amount"}))
    assert saved["widget_data"]["value"] == "250000"
    commit(env, preview(env, upload(env, src, content=NEXT)))
    from uuid import UUID
    refreshed = metrics.refresh_metric(project_id=UUID(env[3]), metric_id=UUID(saved["id"]), user={"id": env[2]})
    assert refreshed["widget_data"]["value"] == "300000"


def test_cleanup_skips_inflight_commit_that_crosses_expiry(env, monkeypatch):
    import threading
    import time
    src = source(env)
    ready = preview(env, upload(env, src))
    entered, release = threading.Event(), threading.Event()
    real_write = service.event_review.write_events
    def delayed_write(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return real_write(*args, **kwargs)
    monkeypatch.setattr(service.event_review, "write_events", delayed_write)
    with env[0]() as conn:
        conn.execute("UPDATE import_batches SET expires_at=now()+interval '1 second' WHERE id=%s", (ready["id"],))
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(commit, env, ready)
        try:
            assert entered.wait(timeout=3)
            time.sleep(1.1)  # cleanup can now see an expired candidate, held by commit
            assert service.expire_pending_batches(env[1]) == 0
        finally:
            release.set()
        assert saving.result()["rows_added"] == 3
    assert service.expire_pending_batches(env[1]) == 0
    assert env[1].read_staged(StorageService.staged_key(str(ready["id"]))) == CONTENT
