"""Real API + Supabase transaction pooler/Storage checks with synthetic data cleanup.

Only runs against the configured DATAEZ project; no LLM requests are made.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import secrets
import sys
from uuid import UUID, uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
REF = "whbygnzoaehvlddltwlb"


def main(deployment=None):
    values = dict(dotenv_values(ROOT / ".env.supabase.local"))
    assert values.get("SUPABASE_URL") == f"https://{REF}.supabase.co"
    assert f"dataez_app.{REF}:" in values["DATABASE_URL"]
    os.environ.update(values)
    sys.path.insert(0, str(ROOT / "api"))
    from fastapi.testclient import TestClient
    from app.main import app
    from app import db
    from app.storage import StorageService
    if deployment:
        from vercel_test_client import VercelTestClient
        factory = lambda: VercelTestClient(deployment)
    else:
        factory = lambda: TestClient(app)
    logging.disable(logging.CRITICAL)
    report = {"project_ref": REF, "scope": "real FastAPI + remote transaction pooler and Storage; no LLM or public Vercel API", "checks": []}
    if deployment:
        report.update(scope="Vercel protected API + Supabase; SQL/storage admin checks and cleanup run locally; no LLM", deployment=deployment)
    checks = report["checks"]
    users, emails, keys = [], [], []
    storage = StorageService()
    marker = uuid4().hex
    stage_key = storage.staged_key(str(uuid4()))
    try:
        with factory() as client:
            ready = client.get("/ready")
            assert ready.status_code == 200 and ready.json().get("checks", {}).get("database") == "ok"
            checks.append("database_ready")
            headers = []
            for i in range(2):
                body = {"email": f"supabase-check-{marker}-{i}@example.invalid", "password": "Aa1!" + secrets.token_urlsafe(24)}
                emails.append(body["email"])
                response = client.post("/api/auth/signup", json=body)
                assert response.status_code == 200, f"signup failed (HTTP {response.status_code})"
                token = response.json()
                users.append(UUID(token["user_id"]))
                assert client.post("/api/auth/login", json=body).status_code == 200
                assert client.post("/api/auth/refresh", json={"refresh_token": token["refresh_token"]}).status_code == 200
                headers.append({"Authorization": "Bearer " + token["access_token"]})
            checks.append("two_accounts_signup_login_refresh")
            project = client.post("/api/projects", headers=headers[0], json={"name": "Supabase 검증 가게"}).json()["id"]
            other_store = client.post("/api/projects", headers=headers[0], json={"name": "Supabase 두 번째 가게"}).json()["id"]
            assert client.get(f"/api/projects/{project}", headers=headers[1]).status_code == 404
            checks.append("cross_account_store_isolation")
            csv = "date,channel,amount\n2026-09-01,카드,12000\n2026-09-02,현금,8000\n".encode("utf-8")
            response = client.post("/api/library/files", headers=headers[0], data={"project_id": project}, files={"file": ("매출.csv", csv, "text/csv")})
            assert response.status_code == 201, "file upload failed"
            file_id = response.json()["file_id"]
            assert "storage_key" not in response.json()
            with db._connect() as conn:
                key = conn.execute("SELECT storage_key FROM files WHERE id=%s AND user_id=%s", (file_id, users[0])).fetchone()["storage_key"]
                keys.append(key)
            assert client.get(f"/api/library/files/{file_id}/download", headers=headers[0]).content == csv
            preview = client.get(f"/api/library/files/{file_id}/preview", headers=headers[0])
            assert preview.status_code == 200 and preview.json()["row_count"] == 2
            checks.append("korean_csv_upload_preview_exact_download")
            for suffix in ("", "/preview", "/download"):
                assert client.get(f"/api/library/files/{file_id}{suffix}", headers=headers[1]).status_code == 404
            assert client.post(f"/api/library/files/{file_id}/prepare", headers=headers[0], json={"project_id": other_store}).status_code == 409
            checks.append("cross_account_file_and_cross_store_binding_denied")
            response = client.post(f"/api/library/files/{file_id}/prepare", headers=headers[0], json={"project_id": project})
            assert response.status_code == 200, "file prepare failed"
            table_id = response.json()["bindings"][0]["table_id"]
            table = db.get_user_table_name(str(users[0]), table_id)
            with db._connect() as conn:
                row = conn.execute(sql.SQL('SELECT sum(amount) AS total,count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()
                assert row["total"] == 20000 and row["n"] == 2
                assert conn.execute("SELECT rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename=%s", (table,)).fetchone()["rowsecurity"]
                assert not conn.execute("SELECT has_table_privilege('anon',%s,'SELECT') AS readable", (table,)).fetchone()["readable"]
            checks.append("dynamic_import_sql_total_and_rls")
            storage.write_staged(stage_key, b"first")
            assert storage.read_bytes(stage_key) == b"first"
            storage.write_staged(stage_key, b"second")
            assert storage.read_bytes(stage_key) == b"second"
            storage.delete_staged(stage_key)
            try:
                storage.read_bytes(stage_key)
                raise AssertionError("deleted stage remained accessible")
            except FileNotFoundError:
                pass
            checks.append("staged_upload_replace_read_delete")
            public = httpx.get(f"{values['SUPABASE_URL']}/storage/v1/object/public/dataez-files/{key}", timeout=15)
            assert public.status_code in (400, 401, 403, 404) and public.content != csv
            checks.append("private_object_public_download_denied")
            with ThreadPoolExecutor(max_workers=4) as executor:
                assert all(code == 200 for code in executor.map(lambda _: client.get("/api/projects", headers=headers[0]).status_code, range(12)))
            checks.append("concurrent_reads_pool_max_two")
        # A new pool and lifespan must find the same stored files and account.
        with factory() as client:
            assert client.get(f"/api/library/files/{file_id}/download", headers=headers[0]).content == csv
            checks.append("reconnected_api_download")
        with psycopg.connect(values["DATABASE_URL"], connect_timeout=10, prepare_threshold=None) as conn:
            assert conn.pgconn.ssl_in_use
            for _ in range(8):
                conn.execute("SELECT %s::int", (123,)).fetchone()
            assert conn.execute("SELECT count(*) FROM pg_prepared_statements").fetchone()[0] == 0
            checks.append("pooler_tls_no_prepared_statements")
    finally:
        db.close_pool()
        # Clean only IDs created by this run, including a signup that failed after insert.
        with psycopg.connect(values["DATABASE_URL"], connect_timeout=10, prepare_threshold=None) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM users WHERE email=ANY(%s)", (emails,)).fetchall()]
            if ids:
                keys = [r[0] for r in conn.execute("SELECT storage_key FROM files WHERE user_id=ANY(%s)", (ids,)).fetchall()]
                for user_id, table_id in conn.execute("SELECT user_id,id FROM table_meta WHERE user_id=ANY(%s)", (ids,)).fetchall():
                    name = db.get_user_table_name(str(user_id), str(table_id))
                    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(name)))
                for table_name in ("audit_log", "query_history", "dashboard_widgets", "conversations", "search_index_jobs", "schema_embeddings", "document_chunks", "table_meta", "library_entries", "refresh_tokens", "projects", "files", "users"):
                    field = "id" if table_name == "users" else "user_id"
                    conn.execute(sql.SQL("DELETE FROM {} WHERE {}=ANY(%s)").format(sql.Identifier(table_name), sql.Identifier(field)), (ids,))
        for key in keys:
            storage._supabase.delete(key)
        storage.delete_staged(stage_key)
        with psycopg.connect(values["DATABASE_URL"], connect_timeout=10, prepare_threshold=None) as conn:
            assert conn.execute("SELECT count(*) FROM users WHERE email=ANY(%s)", (emails,)).fetchone()[0] == 0
        report["synthetic_data_removed"] = True
        output = ROOT / "docs/evaluations/vercel-api" / ("supabase-vercel-preview.json" if deployment else "supabase-api-remote.json")
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", help="Protected Vercel API deployment URL")
    args = parser.parse_args()
    try:
        main(args.deployment)
    except Exception as error:
        print("Supabase remote verification failed:", type(error).__name__, str(error) if isinstance(error, (AssertionError, RuntimeError)) else "")
        raise SystemExit(1)
