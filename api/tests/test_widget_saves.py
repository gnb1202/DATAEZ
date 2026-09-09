"""Real transaction tests: concurrent retries must create exactly one widget."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app import db
from app.widget_saves import ensure_widget_saves
from .test_dashboard_metrics_postgres import live, DSN  # noqa: F401

pytestmark = pytest.mark.skipif(not DSN, reason="Set DATAEZ_TEST_DATABASE_URL")


def prepare(live):
    client, connect, store, other, table, _ = live
    ensure_widget_saves()
    ensure_widget_saves()  # startup is repeatable
    with connect() as conn:
        conn.execute("ALTER TABLE dashboard_widgets ADD COLUMN file_id uuid")
        user = str(conn.execute("SELECT user_id FROM projects WHERE id=%s", (store,)).fetchone()["user_id"])
    return client, connect, store, other, table, user


def test_metric_concurrent_retry_refresh_conflict_and_delete(live):
    client, connect, store, other, table, user = prepare(live)
    body = {"title": "결제액", "save_key": "analysis:message:0", "definition": {"table_id": table, "column": "amount"}}
    def save():
        response = client.post(f"/api/projects/{store}/metrics", json=body)
        assert response.status_code == 201, response.text
        return response.json()["id"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(lambda _: save(), range(5)))
    assert len(set(ids)) == 1
    assert db.list_widgets(user, store)[0]["save_key"] == body["save_key"]
    assert client.post(f"/api/projects/{store}/metrics/{ids[0]}/refresh").status_code == 200
    assert save() == ids[0]
    # Changing a previously used key's payload must never silently overwrite it.
    conflict = client.post(f"/api/projects/{store}/metrics", json={**body, "title": "다른 계산"})
    assert conflict.status_code == 409
    assert client.post(f"/api/projects/{other}/metrics", json=body).status_code == 404
    # Retries still find a saved result even after the source becomes unavailable.
    with connect() as conn:
        conn.execute("UPDATE table_meta SET deleted_at=now() WHERE id=%s", (table,))
    assert save() == ids[0]
    with connect() as conn:
        conn.execute("UPDATE table_meta SET deleted_at=NULL WHERE id=%s", (table,))
    assert db.delete_widget(ids[0], user)
    assert save() != ids[0]


def test_snapshot_retry_layout_and_owner_scope(live):
    _, _, store, other, _, user = prepare(live)
    data = {"chart_type": "bar", "data": [{"value": "9007199254740993.01"}]}
    def save(owner=user, project=store, value=data, key="analysis:snapshot:0", y=0):
        return db.create_widget(str(uuid4()), owner, "chart", "정확한 값", value, {"x": 0, "y": y, "w": 6, "h": 5}, project, save_key=key)
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda i: save(y=i), range(5)))
    assert len({str(row["id"]) for row in rows}) == 1
    assert rows[0]["widget_data"] == data
    assert save(project=other)["id"] != rows[0]["id"]
    assert save(owner=str(uuid4()))["id"] != rows[0]["id"]
    with pytest.raises(HTTPException) as error:
        save(value={"data": []})
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        save(project=None)
    assert error.value.status_code == 422
    assert save(key=None)["id"] != save(key=None)["id"]
