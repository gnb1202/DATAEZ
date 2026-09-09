"""C-stage acceptance scenarios: real transactions, baseline and event review."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql
from fastapi.testclient import TestClient

from app import db, ledger_imports as service, event_review, table_imports, sql_executor
from app.exceptions import AppException
from app.ledger_routes import RowDecision
from .test_ledger_imports_postgres import env, source, upload, preview, commit, state, CONTENT, NEXT
from .test_import_postgres import live, DSN

pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for C-stage verification")


def decisions(env, batch, choices):
    return service.decide_rows(env[2], env[3], batch["id"], str(batch["preview_token"]),
        [RowDecision(row_number=row, decision=choice) for row, choice in choices])


def rows(env, batch, classification=None):
    return service.list_rows(env[2], env[3], batch["id"], classification=classification)["rows"]


def test_overlapping_file_only_adds_new_50000_with_provenance(env):
    src = source(env)
    first = commit(env, preview(env, upload(env, src)))
    overlap = b"id,money,day\n0002,200000.0,2026-09-01T00:00:00+09:00\n0003,-50000,2026-09-01T15:00:00Z\n0004,50000,2026-09-03\n"
    ready = preview(env, upload(env, src, content=overlap))
    assert ready["summary"]["counts"] == {"new": 1, "duplicate": 2, "candidate": 0, "conflict": 0, "included": 1, "excluded": 0, "unresolved": 0}
    assert ready["summary"]["amount"] == "50000"
    assert ready["summary"]["amounts"]["total"] == "200000"
    duplicates = rows(env, ready, "duplicate")
    assert duplicates[0]["matched"]["batch_id"] == str(first["id"])
    assert duplicates[0]["matched"]["row_number"] == 3
    result = commit(env, ready)
    assert result["rows_added"] == 1 and result["result"]["duplicates_skipped"] == 2
    assert sum(r["amount"] for r in state(env, src)[0]) == Decimal(300000)
    assert all(r["target_row_id"] for r in rows(env, result))


def test_first_file_duplicate_key_is_recorded_but_inserted_once(env):
    src = source(env)
    ready = preview(env, upload(env, src, content=b"id,money,day\n0001,100,2026-09-01\n0001,100.00,2026-09-01\n"))
    assert ready["summary"]["counts"]["duplicate"] == 1
    result = commit(env, ready)
    records = rows(env, result)
    assert result["rows_added"] == 1 and records[0]["target_row_id"] == records[1]["target_row_id"]
    assert records[1]["matched"]["row_number"] == 2


@pytest.mark.parametrize("existing", [False, True])
def test_same_key_different_contents_blocks_entire_batch(env, existing):
    src = source(env)
    if existing:
        commit(env, preview(env, upload(env, src, content=b"id,money,day\n001,100,2026-09-01\n")))
    content = b"id,money,day\n001,200,2026-09-01\nNEW,50,2026-09-01\n"
    if not existing:
        content += b"001,300,2026-09-01\n"
    ready = preview(env, upload(env, src, content=content))
    assert ready["status"] == "failed" and not ready["summary"]["can_commit"]
    assert ready["summary"]["counts"]["conflict"] == (1 if existing else 2)
    with pytest.raises(AppException):
        commit(env, ready)
    assert len(state(env, src)[0]) == int(existing)
    assert rows(env, ready, "conflict")[0]["reason"]


def test_partial_refund_ids_and_payment_kind_are_independent(env):
    src = source(env)
    body = b"id,money,day\n001,100000,2026-08-31\n001,-20000,2026-09-01\nR02,-30000,2026-09-01\n"
    result = commit(env, preview(env, upload(env, src, content=body)))
    assert result["rows_added"] == 3 and result["result"]["amount"] == "50000"
    ready = preview(env, upload(env, src, content=b"id,money,day\nR02,-30000.00,2026-09-01\n001,-20000,2026-09-01\n"))
    assert ready["summary"]["counts"]["duplicate"] == 2
    assert commit(env, ready)["rows_added"] == 0


def test_same_amount_day_with_different_ids_remains_distinct(env):
    src = source(env)
    result = commit(env, preview(env, upload(env, src, content=b"id,money,day\nA,100,2026-09-01\na,100,2026-09-01\n")))
    assert result["rows_added"] == 2


@pytest.mark.parametrize("choice,expected", [("include", 2), ("exclude", 1)])
def test_idless_candidates_never_silently_excluded(env, choice, expected):
    src = source(env, mapping={"amount_column": "money", "occurred_at_column": "day"})
    commit(env, preview(env, upload(env, src, content=b"money,day\n100,2026-09-01T10:00:00\n")))
    ready = preview(env, upload(env, src, content=b"money,day\n100,2026-09-01T20:00:00\n"))
    assert ready["summary"]["counts"]["candidate"] == 1
    with pytest.raises(AppException) as exc:
        commit(env, ready)
    assert exc.value.code == "review_unresolved"
    old_token = ready["preview_token"]
    selected = decisions(env, ready, [(2, choice)])
    assert selected["preview_token"] != old_token
    with pytest.raises(AppException):
        commit(env, ready)
    result = commit(env, selected)
    assert len(state(env, src)[0]) == expected
    assert rows(env, result)[0]["decision"] == choice
    assert result["result"]["amount"] == ("100" if choice == "include" else "0")


def test_decision_scope_and_new_preview_reset_previous_choices(env):
    src = source(env, mapping={"amount_column": "money", "occurred_at_column": "day"})
    ready = preview(env, upload(env, src, content=b"money,day\n100,2026-09-01\n100,2026-09-01\n"))
    for choices in [[(2, "exclude")], [(999, "include")], [(3, "include"), (3, "exclude")]]:
        with pytest.raises(AppException):
            decisions(env, ready, choices)
    selected = decisions(env, ready, [(3, "include")])
    repeated = preview(env, selected)
    assert repeated["summary"]["counts"]["unresolved"] == 1
    assert rows(env, repeated, "candidate")[0]["decision"] is None


def test_concurrent_overlapping_commits_require_recheck_then_dedup(env):
    src = source(env)
    first = preview(env, upload(env, src, content=b"id,money,day\n001,100,2026-09-01\n"))
    second = preview(env, upload(env, src, content=b"id,money,day\n001,100,2026-09-01\n002,50,2026-09-02\n"))
    def attempt(batch):
        try:
            return commit(env, batch)
        except AppException as exc:
            assert exc.code == "stale_preview"
            return commit(env, preview(env, batch))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, second]))
    assert sum(r["rows_added"] for r in results) == 2
    assert sum(r["amount"] for r in state(env, src)[0]) == Decimal(150)


def test_event_registry_failure_rolls_back_physical_rows_and_file(env):
    src = source(env)
    ready = preview(env, upload(env, src))
    with env[0]() as conn:
        conn.execute("ALTER TABLE source_events ADD CHECK (event_id<>'0003')")
    with pytest.raises(psycopg.errors.CheckViolation):
        commit(env, ready)
    assert state(env, src) == ([], 0)
    with env[0]() as conn:
        assert conn.execute("SELECT count(*) AS n FROM files").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM source_events").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM import_rows WHERE target_row_id IS NOT NULL").fetchone()["n"] == 0


def legacy(env, content=CONTENT):
    return table_imports.create_imported_table(env[2], env[3], "기존 매출", content, "legacy.csv", env[1])


def adoption_request(meta, **extra):
    return service.CreateSourceRequest(name="기존 출처", provider="카드사", account="계정", feed="결제",
        existing_table_id=meta["id"], mapping={"amount_column": "money", "occurred_at_column": "day", "event_id_column": "id", "event_kind": "signed"}, **extra)


def adopt(env, meta, request=None):
    request = request or adoption_request(meta)
    checked = service.preview_adoption(env[2], env[3], request)
    return service.create_source(env[2], env[3], request.model_copy(update={"adoption_token": checked["adoption_token"]}))


def test_adoption_keeps_existing_ids_schema_rows_and_accepts_overlap(env):
    meta = legacy(env)
    src = adopt(env, meta)
    assert src["table_id"] == meta["id"] and src["storage_mode"] == "original"
    first_schema = db.get_table_meta(str(meta["id"]), env[2])["columns_schema"]
    result = commit(env, preview(env, upload(env, src, content=b"id,money,day\n0001,100000,2026-09-01\n0004,50000,2026-09-03\n")))
    assert result["rows_added"] == 1 and result["result"]["total_row_count"] == 4
    assert db.get_table_meta(str(meta["id"]), env[2])["columns_schema"] == first_schema
    matched = rows(env, result, "duplicate")[0]["matched"]
    assert matched["filename"] == "기존 장부 기준점" and matched["target_row_id"] == 1
    with env[0]() as conn:
        data = conn.execute(sql.SQL("SELECT * FROM {} ORDER BY _row_id").format(sql.Identifier(db.get_user_table_name(env[2], str(meta["id"]))))).fetchall()
    assert [r["_row_id"] for r in data] == [1, 2, 3, 4]
    assert sum(r["money"] for r in data) == Decimal(300000)
    with pytest.raises(AppException):
        table_imports.append_imported_table(env[2], env[3], str(meta["id"]), NEXT, "next.csv")


def test_adoption_rejects_stale_whole_ledger_snapshot(env):
    meta = legacy(env)
    request = adoption_request(meta)
    checked = service.preview_adoption(env[2], env[3], request)
    table_imports.append_imported_table(env[2], env[3], str(meta["id"]), NEXT, "next.csv")
    with pytest.raises(AppException) as exc:
        service.create_source(env[2], env[3], request.model_copy(update={"adoption_token": checked["adoption_token"]}))
    assert exc.value.code == "stale_baseline"
    assert service.list_sources(env[2], env[3]) == []


@pytest.mark.parametrize("amount", [100, 200])
def test_adoption_blocks_preexisting_duplicates_and_conflicts_without_changing_rows(env, amount):
    meta = legacy(env, f"id,money,day\n001,100,2026-09-01\n001,{amount},2026-09-01\n".encode())
    request = adoption_request(meta)
    checked = service.preview_adoption(env[2], env[3], request)
    assert not checked["can_adopt"] and checked["counts"]["duplicate" if amount == 100 else "conflict"] == 1
    with pytest.raises(AppException):
        service.create_source(env[2], env[3], request.model_copy(update={"adoption_token": checked["adoption_token"]}))
    assert db.get_table_meta(str(meta["id"]), env[2])["row_count"] == 2
    assert service.list_sources(env[2], env[3]) == []


def test_existing_b_source_requires_explicit_full_baseline(env):
    src = source(env)
    saved = commit(env, preview(env, upload(env, src)))
    # Model an actual B database: physical rows exist, no event registry.
    with env[0]() as conn:
        conn.execute("DELETE FROM source_events WHERE source_id=%s", (src["id"],))
        conn.execute("UPDATE ledger_sources SET event_index_version=0 WHERE id=%s", (src["id"],))
    assert commit(env, saved)["replayed"]  # successful B retries still replay
    pending = upload(env, src, content=CONTENT + b"0004,50000,2026-09-03\n")
    with pytest.raises(AppException) as exc:
        preview(env, pending)
    assert exc.value.code == "baseline_required"
    report = service.baseline_source(env[2], env[3], src["id"])
    assert report["can_adopt"] and report["row_count"] == 3
    assert commit(env, preview(env, pending))["rows_added"] == 1


def test_idless_baseline_requires_explicit_preservation(env):
    meta = legacy(env, b"money,day\n100,2026-09-01\n100,2026-09-01\n")
    request = service.CreateSourceRequest(name="현금", provider="수기", account="현금", feed="결제", existing_table_id=meta["id"],
                                         mapping={"amount_column": "money", "occurred_at_column": "day"})
    assert not service.preview_adoption(env[2], env[3], request)["can_adopt"]
    src = adopt(env, meta, request.model_copy(update={"accept_idless": True}))
    with env[0]() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_events WHERE source_id=%s", (src["id"],)).fetchone()["n"] == 2


def test_other_scope_cannot_review_decide_or_adopt(env):
    src = source(env)
    batch = preview(env, upload(env, src))
    meta = legacy(env)
    for user, store in [(env[2], env[4]), (str(uuid4()), env[3])]:
        for call in [lambda: service.list_rows(user, store, batch["id"]),
                     lambda: service.decide_rows(user, store, batch["id"], batch["preview_token"], [RowDecision(row_number=2, decision="exclude")]),
                     lambda: service.preview_adoption(user, store, adoption_request(meta)),
                     lambda: service.baseline_source(user, store, src["id"])]:
            with pytest.raises(AppException) as exc:
                call()
            assert exc.value.status_code == 404


def test_http_candidate_decision_and_rows_pagination(env, monkeypatch):
    from app import main, ledger_routes
    from app.auth import get_current_user
    monkeypatch.setattr(ledger_routes, "storage", env[1])
    main.app.dependency_overrides[get_current_user] = lambda: {"id": env[2]}
    try:
        client = TestClient(main.app)
        src = source(env, mapping={"amount_column": "money", "occurred_at_column": "day"})
        batch = preview(env, upload(env, src, content=b"money,day\n100,2026-09-01\n100,2026-09-01\n"))
        base = f"/api/projects/{env[3]}/imports/{batch['id']}"
        result = client.get(base + "/rows", params={"classification": "candidate", "limit": 1})
        assert result.status_code == 200 and result.json()["rows"][0]["row_number"] == 3
        assert client.get(base + "/rows", params={"classification": "anything"}).status_code == 422
        decision = client.post(base + "/decisions", json={"preview_token": str(batch["preview_token"]), "decisions": [{"row_number": 3, "decision": "exclude"}]})
        assert decision.status_code == 200 and decision.json()["summary"]["can_commit"]
        result = client.post(base + "/commit", json={"preview_token": decision.json()["preview_token"]})
        assert result.status_code == 200 and result.json()["rows_added"] == 1
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def test_migration_matches_runtime(env):
    from pathlib import Path
    from app.event_schema import DDL
    assert (Path(__file__).resolve().parents[2] / "db/migrations/005_event_review.sql").read_text(encoding="utf-8").split("\n", 1)[1] == DDL
    db.ensure_ledger_import_tables()


def test_adoption_and_generic_writer_are_serialized(env, monkeypatch):
    import threading
    meta = legacy(env)
    request = adoption_request(meta)
    checked = service.preview_adoption(env[2], env[3], request)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    original_scan = service.ledger_baseline.scan
    def paused_scan(*args, **kwargs):
        result = original_scan(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return result
    monkeypatch.setattr(service.ledger_baseline, "scan", paused_scan)
    def mutate():
        attempted.set()
        return sql_executor.safe_insert(db.get_user_table_name(env[2], str(meta["id"])), env[2], [{"id": "late", "money": 999, "day": "2026-09-01"}])
    with ThreadPoolExecutor(max_workers=2) as pool:
        adopting = pool.submit(service.create_source, env[2], env[3], request.model_copy(update={"adoption_token": checked["adoption_token"]}))
        try:
            assert entered.wait(timeout=3)
            writing = pool.submit(mutate)
            assert attempted.wait(timeout=3)
        finally:
            release.set()
        adopting.result()
        with pytest.raises(AppException) as exc:
            writing.result()
        assert exc.value.code == "managed_ledger"
    assert db.get_table_meta(str(meta["id"]), env[2])["row_count"] == 3


def test_large_event_ids_use_bounded_unique_keys(env):
    src = source(env)
    event_id = "000" + "x" * 5000
    content = f"id,money,day\n{event_id},100,2026-09-01\n".encode()
    commit(env, preview(env, upload(env, src, content=content)))
    changed_file = content + b"new,50,2026-09-02\n"
    result = commit(env, preview(env, upload(env, src, content=changed_file)))
    assert result["rows_added"] == 1 and state(env, src)[0][0]["event_id"] == event_id


def test_original_payment_id_does_not_collapse_partial_refunds(env):
    src = source(env, mapping={"amount_column": "money", "occurred_at_column": "day", "event_id_column": "id",
                               "original_event_id_column": "original", "event_kind": "signed"})
    content = b"id,original,money,day\nP01,,100000,2026-08-31\nR01,P01,-20000,2026-09-01\nR02,P01,-20000,2026-09-01\n"
    result = commit(env, preview(env, upload(env, src, content=content)))
    assert result["rows_added"] == 3 and result["result"]["amount"] == "60000"
    changed = content + b"R03,P01,-10000,2026-09-02\n"
    result = commit(env, preview(env, upload(env, src, content=changed)))
    assert result["rows_added"] == 1 and result["result"]["duplicates_skipped"] == 3


def test_adoption_rejects_schema_that_future_file_import_cannot_write(env):
    meta = legacy(env)
    schema = [{**c, "type": "REAL" if c["name"] == "money" else c["type"]} for c in meta["columns_schema"]]
    db.update_table_meta(str(meta["id"]), env[2], columns_schema=schema)
    with pytest.raises(AppException) as exc:
        service.preview_adoption(env[2], env[3], adoption_request(meta))
    assert exc.value.status_code == 422
    assert service.list_sources(env[2], env[3]) == []
