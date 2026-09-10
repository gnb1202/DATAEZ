"""Integration tests — exercise full API endpoints via TestClient.

These tests mock the database layer and OpenAI calls so they run
without external services. They verify request validation, auth flow,
ownership checks, and end-to-end endpoint behaviour.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_USER = {"id": str(uuid4()), "email": "test@example.com"}
_FAKE_PROJECT_ID = str(uuid4())
_FAKE_TABLE_ID = str(uuid4())
_FAKE_CONV_ID = str(uuid4())

# Patch startup tasks that need a real DB before importing app
_startup_patches = [
    # Patch where lifespan looks up the names, even when another test already
    # imported main. Patching db alone depended on test collection order.
    patch("app.main.run_startup_migrations"),
    patch("app.main.ensure_conversation_tables"),
    patch("app.main.ensure_dashboard_widgets_table"),
    patch("app.main.ensure_metric_revisions"),
    patch("app.main.ensure_project_tables"),
    patch("app.main.ensure_ledger_import_tables"),
    patch("app.main.ensure_audit_log_table"),
    patch("app.main.ensure_rag_tables"),
    patch("app.main.ensure_performance_indexes"),
    patch("app.main.ensure_library"),
    patch("app.main.ensure_widget_saves"),
    patch("app.main.cleanup_old_conversations"),
    patch("app.main.cleanup_expired_refresh_tokens"),
    patch("app.main.purge_soft_deleted"),
    patch("app.main.close_pool"),
    patch("app.main.record_audit"),
]


@pytest.fixture(autouse=True, scope="module")
def _mock_startup():
    mocks = [p.start() for p in _startup_patches]
    yield
    for p in _startup_patches:
        p.stop()


def _make_project(pid: str | None = None, **overrides):
    base = {
        "id": pid or _FAKE_PROJECT_ID,
        "user_id": _FAKE_USER["id"],
        "name": "Test Project",
        "description": "",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "table_count": 0,
    }
    base.update(overrides)
    return base


def _make_table_meta(tid: str | None = None, **overrides):
    base = {
        "id": tid or _FAKE_TABLE_ID,
        "project_id": _FAKE_PROJECT_ID,
        "user_id": _FAKE_USER["id"],
        "name": "Sales",
        "description": "",
        "columns_schema": [{"name": "item", "type": "TEXT"}, {"name": "amount", "type": "INTEGER"}],
        "row_count": 5,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    base.update(overrides)
    return base


def _make_conversation(cid: str | None = None, **overrides):
    base = {
        "id": cid or _FAKE_CONV_ID,
        "user_id": _FAKE_USER["id"],
        "file_id": None,
        "project_id": _FAKE_PROJECT_ID,
        "table_id": None,
        "title": "Test Conversation",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    base.update(overrides)
    return base


@pytest.fixture()
def auth_client():
    """TestClient with mocked auth that always returns _FAKE_USER."""
    from app.main import app
    from app.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Health / Ready
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    def test_health(self, auth_client):
        res = auth_client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_ready_with_database(self, auth_client):
        with patch("app.db._connect") as connect:
            res = auth_client.get("/ready")
        assert res.status_code == 200
        assert res.json() == {"status": "ok", "checks": {"database": "ok"}}
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.assert_called_once_with("SELECT 1")

    def test_ready_without_database(self, auth_client):
        with patch("app.db._connect", side_effect=ConnectionError("test database unavailable")):
            res = auth_client.get("/ready")
        assert res.status_code == 503
        assert res.json() == {"status": "degraded", "checks": {"database": "error"}}


# ---------------------------------------------------------------------------
# Auth validation (request shapes)
# ---------------------------------------------------------------------------


class TestAuthValidation:
    """Verify request validation without hitting the real auth layer."""

    def test_signup_missing_fields(self, auth_client):
        res = auth_client.post("/api/auth/signup", json={})
        assert res.status_code == 422

    def test_login_missing_fields(self, auth_client):
        res = auth_client.post("/api/auth/login", json={})
        assert res.status_code == 422

    def test_refresh_missing_token(self, auth_client):
        res = auth_client.post("/api/auth/refresh", json={})
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------


class TestProjectsCRUD:
    @patch("app.main.create_project")
    def test_create_project(self, mock_create, auth_client):
        mock_create.return_value = _make_project()
        res = auth_client.post(
            "/api/projects",
            json={"name": "My Shop", "description": "A small shop"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Test Project"
        mock_create.assert_called_once()

    @patch("app.main.list_projects")
    def test_list_projects(self, mock_list, auth_client):
        mock_list.return_value = [_make_project()]
        res = auth_client.get("/api/projects")
        assert res.status_code == 200
        data = res.json()
        assert len(data["projects"]) == 1

    @patch("app.main.get_project")
    def test_get_project_not_found(self, mock_get, auth_client):
        mock_get.return_value = None
        res = auth_client.get(f"/api/projects/{uuid4()}")
        assert res.status_code == 404

    @patch("app.main.get_project")
    def test_get_project_found(self, mock_get, auth_client):
        mock_get.return_value = _make_project()
        res = auth_client.get(f"/api/projects/{_FAKE_PROJECT_ID}")
        assert res.status_code == 200

    @patch("app.main.delete_project")
    def test_delete_project_not_found(self, mock_del, auth_client):
        mock_del.return_value = False
        res = auth_client.delete(f"/api/projects/{uuid4()}")
        assert res.status_code == 404

    @patch("app.main.delete_project")
    def test_delete_project_success(self, mock_del, auth_client):
        mock_del.return_value = True
        res = auth_client.delete(f"/api/projects/{_FAKE_PROJECT_ID}")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    @patch("app.main.create_project")
    def test_create_project_empty_name(self, mock_create, auth_client):
        mock_create.return_value = _make_project(name="")
        res = auth_client.post("/api/projects", json={"name": ""})
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Tables CRUD
# ---------------------------------------------------------------------------


class TestTablesCRUD:
    @patch("app.main.get_project")
    @patch("app.main.create_user_data_table")
    @patch("app.main.create_table_meta")
    def test_create_table(self, mock_meta, mock_create_pg, mock_proj, auth_client):
        mock_proj.return_value = _make_project()
        mock_meta.return_value = _make_table_meta()
        res = auth_client.post(
            f"/api/projects/{_FAKE_PROJECT_ID}/tables",
            json={
                "name": "Sales",
                "description": "Monthly sales",
                "columns": [{"name": "item", "type": "TEXT"}],
            },
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Sales"

    @patch("app.main.get_project")
    @patch("app.main.list_table_metas")
    def test_list_tables(self, mock_list, mock_proj, auth_client):
        mock_proj.return_value = _make_project()
        mock_list.return_value = [_make_table_meta()]
        res = auth_client.get(f"/api/projects/{_FAKE_PROJECT_ID}/tables")
        assert res.status_code == 200
        assert len(res.json()["tables"]) == 1

    @patch("app.main.get_project")
    def test_list_tables_project_not_found(self, mock_proj, auth_client):
        mock_proj.return_value = None
        res = auth_client.get(f"/api/projects/{uuid4()}/tables")
        assert res.status_code == 404

    @patch("app.main.get_table_meta")
    @patch("app.main.drop_user_data_table")
    @patch("app.main.delete_table_meta")
    def test_delete_table(self, mock_del_meta, mock_drop, mock_get, auth_client):
        mock_get.return_value = _make_table_meta()
        res = auth_client.delete(
            f"/api/projects/{_FAKE_PROJECT_ID}/tables/{_FAKE_TABLE_ID}"
        )
        assert res.status_code == 200
        mock_drop.assert_called_once()
        mock_del_meta.assert_called_once()

    @patch("app.main.get_table_meta")
    def test_delete_table_wrong_project(self, mock_get, auth_client):
        mock_get.return_value = _make_table_meta(project_id=str(uuid4()))
        res = auth_client.delete(
            f"/api/projects/{_FAKE_PROJECT_ID}/tables/{_FAKE_TABLE_ID}"
        )
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------


class TestConversationsCRUD:
    @patch("app.main.get_project")
    @patch("app.main.create_conversation")
    def test_create_conversation(self, mock_create, mock_proj, auth_client):
        mock_proj.return_value = _make_project()
        res = auth_client.post(
            "/api/conversations",
            json={"project_id": _FAKE_PROJECT_ID, "title": "New chat"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "conversation_id" in data
        assert data["project_id"] == _FAKE_PROJECT_ID

    @patch("app.main.get_project")
    def test_create_conversation_project_not_found(self, mock_proj, auth_client):
        mock_proj.return_value = None
        res = auth_client.post(
            "/api/conversations",
            json={"project_id": str(uuid4()), "title": "X"},
        )
        assert res.status_code == 404

    @patch("app.main.list_conversations")
    def test_list_conversations(self, mock_list, auth_client):
        mock_list.return_value = ([_make_conversation()], 1)
        res = auth_client.get(f"/api/conversations?project_id={_FAKE_PROJECT_ID}")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1

    @patch("app.main.delete_conversation")
    def test_delete_conversation_not_found(self, mock_del, auth_client):
        mock_del.return_value = False
        res = auth_client.delete(f"/api/conversations/{uuid4()}")
        assert res.status_code == 404

    @patch("app.main.delete_conversation")
    def test_delete_conversation_success(self, mock_del, auth_client):
        mock_del.return_value = True
        res = auth_client.delete(f"/api/conversations/{_FAKE_CONV_ID}")
        assert res.status_code == 200

    @patch("app.main.get_conversation")
    @patch("app.main.list_messages")
    def test_get_messages(self, mock_msgs, mock_conv, auth_client):
        mock_conv.return_value = _make_conversation()
        mock_msgs.return_value = [
            {
                "id": str(uuid4()),
                "role": "user",
                "content": "Hello",
                "steps": None,
                "charts": None,
                "table_data": None,
                "created_at": datetime.now(),
            }
        ]
        res = auth_client.get(f"/api/conversations/{_FAKE_CONV_ID}/messages")
        assert res.status_code == 200
        assert len(res.json()["messages"]) == 1


# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------


class TestFileUpload:
    def test_upload_wrong_extension(self, auth_client):
        res = auth_client.post(
            "/api/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert res.status_code == 400
        assert "test.txt" in res.json()["detail"]

    @patch("app.main.storage")
    @patch("app.main.save_file")
    def test_upload_csv_success(self, mock_save, mock_storage, auth_client):
        mock_storage.upload_bytes.return_value = "s3://bucket/test.csv"
        res = auth_client.post(
            "/api/files/upload",
            files={"file": ("test.csv", b"a,b\n1,2", "text/csv")},
        )
        assert res.status_code == 200
        assert res.json()["filename"] == "test.csv"


# ---------------------------------------------------------------------------
# Dashboard Widgets
# ---------------------------------------------------------------------------


class TestDashboardWidgets:
    @patch("app.main.list_widgets")
    def test_list_widgets(self, mock_list, auth_client):
        mock_list.return_value = []
        res = auth_client.get("/api/dashboard/widgets")
        assert res.status_code == 200
        assert res.json()["widgets"] == []

    @patch("app.main.create_widget")
    def test_create_widget(self, mock_create, auth_client):
        widget_data = {"chart_type": "bar", "x_key": "month", "y_key": "sales", "data": []}
        mock_create.return_value = {
            "id": str(uuid4()),
            "widget_type": "chart",
            "title": "Sales",
            "widget_data": widget_data,
            "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
            "created_at": datetime.now(),
        }
        res = auth_client.post(
            "/api/dashboard/widgets",
            json={
                "widget_type": "chart",
                "title": "Sales",
                "widget_data": widget_data,
                "layout": {"x": 0, "y": 0, "w": 6, "h": 4},
            },
        )
        assert res.status_code == 200
        assert res.json()["widget_type"] == "chart"

    @patch("app.main.delete_widget")
    def test_delete_widget_not_found(self, mock_del, auth_client):
        mock_del.return_value = False
        res = auth_client.delete(f"/api/dashboard/widgets/{uuid4()}")
        assert res.status_code == 404

    @patch("app.main.delete_widget")
    def test_delete_widget_success(self, mock_del, auth_client):
        mock_del.return_value = True
        res = auth_client.delete(f"/api/dashboard/widgets/{uuid4()}")
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Import CSV Pipeline
# ---------------------------------------------------------------------------


class TestImportPipeline:
    @patch("app.main.get_project")
    def test_import_wrong_extension(self, mock_proj, auth_client):
        mock_proj.return_value = _make_project()
        res = auth_client.post(
            f"/api/projects/{_FAKE_PROJECT_ID}/tables/import",
            files={"file": ("data.json", b"{}", "application/json")},
        )
        assert res.status_code == 400

    @patch("app.main.get_project")
    def test_import_project_not_found(self, mock_proj, auth_client):
        mock_proj.return_value = None
        res = auth_client.post(
            f"/api/projects/{uuid4()}/tables/import",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
        assert res.status_code == 404
