"""Real psycopg transactions: byte import -> metadata -> saved metric refresh."""
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import uuid4, UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app import db, dashboard_metrics as metrics, table_imports as imports
from app.data_import import write_import
from app.payment_imports import PaymentImportMapping, prepare_payment_import

DSN = os.environ.get("DATAEZ_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for real import transactions")


@pytest.fixture
def live(monkeypatch):
    namespace = "dataez_import_test_" + uuid4().hex
    user, store, other = (str(uuid4()) for _ in range(3))
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))

    @contextmanager
    def connect():
        with psycopg.connect(DSN, options=f"-c search_path={namespace}", row_factory=dict_row) as conn:
            yield conn

    try:
        with connect() as conn:
            conn.execute("CREATE TABLE projects (id uuid PRIMARY KEY,user_id uuid,name text,description text,created_at timestamp DEFAULT now(),updated_at timestamp DEFAULT now(),deleted_at timestamp)")
            conn.execute("CREATE TABLE files (id uuid PRIMARY KEY,user_id uuid,filename text,storage_key text,size_bytes bigint,created_at timestamp DEFAULT now())")
            conn.execute("""CREATE TABLE table_meta (id uuid PRIMARY KEY,project_id uuid REFERENCES projects(id),user_id uuid,name text,
                description text DEFAULT '',columns_schema jsonb,row_count bigint,source_file_id uuid REFERENCES files(id),
                created_at timestamp DEFAULT now(),updated_at timestamp DEFAULT now(),deleted_at timestamp)""")
            conn.execute("""CREATE TABLE dashboard_widgets (id uuid PRIMARY KEY,user_id uuid,project_id uuid,widget_type text,title text,widget_data jsonb,layout jsonb,
                created_at timestamptz DEFAULT now(),refresh_interval_seconds integer DEFAULT 0,next_refresh_at timestamptz,refresh_failures integer DEFAULT 0)""")
            conn.execute("INSERT INTO projects(id,user_id,name) VALUES (%s,%s,'강남점'),(%s,%s,'홍대점')", (store, user, other, user))
        for module in (db, imports, metrics):
            monkeypatch.setattr(module, "_connect", connect)
        db.ensure_ledger_import_tables()
        storage = MagicMock()
        storage.upload_bytes.return_value = "isolated-test-object"
        yield connect, storage, user, store, other
    finally:
        assert namespace.startswith("dataez_import_test_") and len(namespace) == len("dataez_import_test_") + 32
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(namespace)))


def create(live, text, name="결제"):
    _, storage, user, store, _ = live
    return imports.create_imported_table(user, store, name, text.encode("utf-8"), "ledger.csv", storage)


def read_rows(live, meta):
    connect, _, user, *_ = live
    with connect() as conn:
        return conn.execute(sql.SQL("SELECT * FROM {} ORDER BY _row_id").format(sql.Identifier(db.get_user_table_name(user, str(meta["id"]))))).fetchall()


def test_exact_file_values_and_metadata_saved_together(live):
    from decimal import Decimal
    meta = create(live, "event_id,amount,paid_at\n000012345678901234567890,9007199254740993.01,2026-09-01\n")
    row = read_rows(live, meta)[0]
    assert row["event_id"] == "000012345678901234567890"
    assert row["amount"] == Decimal("9007199254740993.01")
    assert meta["row_count"] == 1 and meta["source_file_id"]


def test_failed_metadata_rolls_back_file_row_and_created_table(live):
    connect, storage, *_ = live
    with connect() as conn:
        conn.execute("ALTER TABLE table_meta ADD CHECK (name <> 'reject')")
    with pytest.raises(psycopg.errors.CheckViolation):
        create(live, "amount\n100\n", name="reject")
    storage.upload_bytes.assert_called_once()
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM files").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM table_meta").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'ut_%'").fetchone()["n"] == 0


def test_partial_executemany_failure_rolls_back_all_rows_and_count(live):
    connect, _, user, store, _ = live
    meta = create(live, "event_id,amount\n001,100\n")
    table = db.get_user_table_name(user, str(meta["id"]))
    with connect() as conn:
        conn.execute(sql.SQL("ALTER TABLE {} ADD UNIQUE(event_id)").format(sql.Identifier(table)))
    with pytest.raises(psycopg.errors.UniqueViolation):
        imports.append_imported_table(user, store, str(meta["id"]), b"event_id,amount\n002,200\n001,100\n", "ledger.csv")
    assert len(read_rows(live, meta)) == 1
    assert db.get_table_meta(str(meta["id"]), user)["row_count"] == 1


def test_concurrent_append_increments_count_without_lost_update(live):
    _, _, user, store, _ = live
    meta = create(live, "event_id,amount\n001,100\n")
    def append(index):
        return imports.append_imported_table(user, store, str(meta["id"]), f"event_id,amount\n00{index},{index * 100}\n".encode(), "ledger.csv")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, [2, 3]))
    assert sorted(r["total_row_count"] for r in results) == [2, 3]
    assert len(read_rows(live, meta)) == 3
    assert db.get_table_meta(str(meta["id"]), user)["row_count"] == 3


def test_import_multi_metric_append_and_refresh(live):
    connect, _, user, store, _ = live
    metas = [create(live, f"event_id,amount,paid_at\n00{i},{amount},2026-09-01\n", name=name)
             for i, (name, amount) in enumerate([("현금", 100000), ("카드", 200000), ("취소", 50000)])]
    definition = metrics.MultiMetricDefinition(sources=[{"table_id": str(m["id"]), "label": m["name"], "column": "amount",
        "date_column": "paid_at", "amount_mode": "refund" if m["name"] == "취소" else "signed"} for m in metas])
    saved = metrics.create_saved_metric(store, user, metrics.CreateMetricRequest(title="순결제액", definition=definition))
    assert saved["widget_data"]["value"] == "250000"
    imports.append_imported_table(user, store, str(metas[0]["id"]), b"event_id,amount,paid_at\n0010,50000,2026-09-02\n", "next.csv")
    refreshed = metrics.refresh_metric(project_id=UUID(store), metric_id=UUID(saved["id"]), user={"id": user})
    assert refreshed["widget_data"]["value"] == "300000"
    assert refreshed["widget_data"]["sources"][0]["included_rows"] == 2


def test_other_store_cannot_append(live):
    _, _, user, _, other = live
    meta = create(live, "amount\n100\n")
    with pytest.raises(Exception) as error:
        imports.append_imported_table(user, other, str(meta["id"]), b"amount\n200\n", "ledger.csv")
    assert error.value.status_code == 404
    assert len(read_rows(live, meta)) == 1


def test_payment_mapping_keeps_partial_refunds_and_month_boundary(live):
    connect, *_ = live
    mapping = PaymentImportMapping(amount_column="취소금액", occurred_at_column="취소일", event_id_column="취소번호", original_event_id_column="원거래번호", event_kind="refund")
    prepared = prepare_payment_import("취소번호,원거래번호,취소금액,취소일\nR01,001,20000,2026-08-31T23:59:59\nR02,001,-30000,2026-09-01T00:00:00\n".encode(), "cancel.csv", mapping)
    with connect() as conn, conn.cursor() as cur:
        write_import(cur, "payment_events", prepared, create=True)
        cur.execute("SET TIME ZONE 'Asia/Seoul'")
        cur.execute("SELECT event_id, original_event_id, amount::text, occurred_at::date::text AS day FROM payment_events ORDER BY event_id")
        assert cur.fetchall() == [
            {"event_id": "R01", "original_event_id": "001", "amount": "-20000", "day": "2026-08-31"},
            {"event_id": "R02", "original_event_id": "001", "amount": "-30000", "day": "2026-09-01"},
        ]


def test_real_http_import_validation_is_actionable_and_all_or_nothing(live, monkeypatch):
    from app.main import app
    from app.auth import get_current_user
    from app import main
    _, storage, user, store, _ = live
    monkeypatch.setattr(main, "storage", storage)
    monkeypatch.setattr(main, "record_audit", MagicMock())
    app.dependency_overrides[get_current_user] = lambda: {"id": user}
    try:
        client = TestClient(app)  # no production startup migrations in the fixture schema
        response = client.post(f"/api/projects/{store}/tables/import", files={"file": ("bad.csv", b"amount,date\n1,2026-02-30\n")})
        assert response.status_code == 422
        assert response.json()["issues"][0]["row"] == 2
        storage.upload_bytes.assert_not_called()
        response = client.post(f"/api/projects/{store}/tables/import", files={"file": ("ok.csv", b"event_id,amount\n001,100\n")})
        assert response.status_code == 200
        table_id = response.json()["id"]
        bad = client.post(f"/api/projects/{store}/tables/{table_id}/append", files={"file": ("bad.csv", b"event_id,wrong\n002,200\n")})
        assert bad.status_code == 422
        assert db.get_table_meta(table_id, user)["row_count"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
