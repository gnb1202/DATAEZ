"""Opt-in real PostgreSQL tests, isolated in a disposable schema.

DATAEZ_TEST_DATABASE_URL must point to a development/test database. Each test
owns a unique schema and removes only that schema; no application tables are used.
"""

import os
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app import dashboard_metrics as metrics
from app import db
from app.auth import get_current_user

DSN = os.environ.get("DATAEZ_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL for real PostgreSQL evaluation")


@pytest.fixture
def live():
    schema = "dataez_metric_test_" + uuid4().hex
    user, store, other_store, table = (str(uuid4()) for _ in range(4))
    physical = db.get_user_table_name(user, table)
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        @contextmanager
        def connect():
            with psycopg.connect(DSN, options=f"-c search_path={schema}", row_factory=dict_row) as conn:
                yield conn

        with connect() as conn:
            conn.execute("CREATE TABLE projects (id uuid PRIMARY KEY, user_id uuid, name text, description text, created_at timestamp, updated_at timestamp, deleted_at timestamp)")
            conn.execute("CREATE TABLE table_meta (id uuid PRIMARY KEY, project_id uuid, user_id uuid, name text, description text, columns_schema jsonb, row_count integer, source_file_id uuid, created_at timestamp, updated_at timestamp, deleted_at timestamp)")
            conn.execute("CREATE TABLE dashboard_widgets (id uuid PRIMARY KEY, user_id uuid, project_id uuid, widget_type text, title text, widget_data jsonb, layout jsonb, created_at timestamptz DEFAULT now(), refresh_interval_seconds integer NOT NULL DEFAULT 0, next_refresh_at timestamptz, refresh_failures integer NOT NULL DEFAULT 0)")
            conn.execute("INSERT INTO projects (id,user_id,name) VALUES (%s,%s,'강남점'),(%s,%s,'성수점')", (store, user, other_store, user))
            conn.execute(
                """INSERT INTO table_meta (id,project_id,user_id,name,columns_schema) VALUES (%s,%s,%s,'결제',
                '[{"name":"amount","type":"NUMERIC(15,2)"},{"name":"method","type":"TEXT"},{"name":"paid_at","type":"TIMESTAMP"}]')""",
                (table, store, user),
            )
            conn.execute(sql.SQL("CREATE TABLE {} (amount numeric(15,2), method text, paid_at timestamp)").format(sql.Identifier(physical)))
            conn.execute(sql.SQL("INSERT INTO {} VALUES (100000,'현금','2026-09-01'),(200000,'카드','2026-09-01'),(-50000,'카드','2026-09-02')").format(sql.Identifier(physical)))
        app = FastAPI()
        app.include_router(metrics.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": user}
        with patch.object(metrics, "_connect", connect), patch.object(db, "_connect", connect), TestClient(app) as client:
            yield client, connect, store, other_store, table, physical
    finally:
        assert schema.startswith("dataez_metric_test_") and len(schema) == len("dataez_metric_test_") + 32
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def create(client, store, table, **extra):
    return client.post(f"/api/projects/{store}/metrics", json={
        "title": "순결제액", "definition": {"table_id": table, "column": "amount", **extra},
    })


def test_real_save_append_and_refresh(live):
    client, connect, store, _, table, physical = live
    response = create(client, store, table)
    assert response.status_code == 201, response.text
    assert response.json()["widget_data"]["value"] == "250000.00"
    metric_id = response.json()["id"]
    with connect() as conn:
        conn.execute(sql.SQL("INSERT INTO {} VALUES (80000,'현금','2026-09-03')").format(sql.Identifier(physical)))
    for _ in range(2):
        refreshed = client.post(f"/api/projects/{store}/metrics/{metric_id}/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["widget_data"]["value"] == "330000.00"


def test_real_daily_grouping(live):
    client, _, store, _, table, _ = live
    response = create(client, store, table, group_by="paid_at", date_grain="day")
    assert response.status_code == 201, response.text
    assert response.json()["widget_data"]["data"] == [
        {"dimension": "2026-09-01", "value": "300000.00"},
        {"dimension": "2026-09-02", "value": "-50000.00"},
    ]


def test_real_other_store_and_failed_refresh(live):
    client, connect, store, other_store, table, physical = live
    assert create(client, other_store, table).status_code == 404
    response = create(client, store, table)
    metric_id = response.json()["id"]
    assert client.post(f"/api/projects/{other_store}/metrics/{metric_id}/refresh").status_code == 404
    with connect() as conn:
        conn.execute(sql.SQL("ALTER TABLE {} DROP COLUMN amount").format(sql.Identifier(physical)))
    failed = client.post(f"/api/projects/{store}/metrics/{metric_id}/refresh")
    assert failed.status_code == 422
    with connect() as conn:
        result = conn.execute("SELECT widget_data FROM dashboard_widgets WHERE id=%s", (metric_id,)).fetchone()["widget_data"]
    assert result["value"] == "250000.00"
    assert result["refresh_error"]


def test_real_relative_period_and_filter(live):
    client, connect, store, _, table, physical = live
    with connect() as conn:
        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(physical)))
        conn.execute("SET TIME ZONE 'Asia/Seoul'")
        conn.execute(sql.SQL("INSERT INTO {} VALUES (100,'카드',CURRENT_DATE),(900,'현금',CURRENT_DATE),(200,'카드',date_trunc('month',CURRENT_DATE)-interval '1 day')").format(sql.Identifier(physical)))
    response = create(client, store, table, date_column="paid_at", time_range="this_month", filters=[{"column": "method", "value": "카드"}])
    assert response.status_code == 201, response.text
    assert response.json()["widget_data"]["value"] == "100.00"


def test_real_scheduler_due_time_and_stop(live):
    from app import metric_scheduler
    client, connect, store, _, table, _ = live
    response = create(client, store, table)
    wid = response.json()["id"]
    assert client.patch(f"/api/projects/{store}/metrics/{wid}/schedule", json={"refresh_interval_seconds": 3600}).status_code == 200
    with connect() as conn:
        conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 minute' WHERE id=%s", (wid,))
    with patch.object(metric_scheduler, "_connect", connect):
        assert metric_scheduler.refresh_one_due() is True
        assert metric_scheduler.refresh_one_due() is False
    assert client.patch(f"/api/projects/{store}/metrics/{wid}/schedule", json={"refresh_interval_seconds": 0}).status_code == 200
    with connect() as conn:
        row = conn.execute("SELECT * FROM dashboard_widgets WHERE id=%s", (wid,)).fetchone()
    assert row["next_refresh_at"] is None
