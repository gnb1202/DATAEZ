"""Isolated PostgreSQL + real API auth verification; no Supabase or model requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def exercise(reconnect=False):
    sys.path.insert(0, str(ROOT / "api"))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import _connect
    checks = []
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        checks.append("database_ready")
        identities = []
        for suffix in ("a", "b"):
            body = {"email": f"{suffix}@serverless.invalid", "password": "Synthetic-test-password-123"}
            if not reconnect:
                assert client.post("/api/auth/signup", json=body).status_code == 200
            response = client.post("/api/auth/login", json=body)
            assert response.status_code == 200
            token = response.json()
            identities.append({"Authorization": f"Bearer {token['access_token']}"})
            assert client.post("/api/auth/refresh", json={"refresh_token": token["refresh_token"]}).status_code == 200
        checks.append("two_accounts_login_and_refresh")
        if not reconnect:
            for headers in identities:
                assert client.post("/api/projects", headers=headers, json={"name": "Synthetic store"}).status_code == 200
        projects = [client.get("/api/projects", headers=h).json()["projects"] for h in identities]
        assert all(len(p) == 1 for p in projects)
        assert projects[0][0]["id"] != projects[1][0]["id"]
        assert client.get(f"/api/projects/{projects[0][0]['id']}", headers=identities[1]).status_code == 404
        checks.append("cross_account_project_isolation")
        def read(i):
            return client.get("/api/projects", headers=identities[i % 2]).status_code
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert all(code == 200 for code in executor.map(read, range(12)))
        checks.append("concurrent_reads_with_two_connection_pool")
        with _connect() as conn:
            assert conn.prepare_threshold is None
            for _ in range(8):
                assert conn.execute("SELECT %s::int AS value", (123,)).fetchone()["value"] == 123
            assert conn.execute("SELECT count(*) AS n FROM pg_prepared_statements").fetchone()["n"] == 0
        checks.append("no_automatic_prepared_statements")
    print(json.dumps({"fresh_process_reconnect": reconnect, "checks": checks}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".local-test/serverless/report.json")
    args = parser.parse_args()
    if args.exercise:
        exercise(args.reconnect)
        return
    password = secrets.token_hex(24)
    container = None
    def run(command, **kwargs):
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120, **kwargs)
        if result.returncode:
            raise RuntimeError(result.stderr.replace(password, "[redacted]")[-3000:])
        return result.stdout.strip()
    report = {"scope": "local PostgreSQL, real API; not remote Supabase/pooler/Storage/LLM validation"}
    try:
        container = run(["docker", "run", "-d", "--name", f"dataez-serverless-{uuid4().hex[:8]}",
                         "--label", "dataez.task=serverless-foundation", "--memory", "512m",
                         "--tmpfs", "/var/lib/postgresql/data:rw", "-p", "127.0.0.1::5432",
                         "-e", f"POSTGRES_PASSWORD={password}", "pgvector/pgvector:pg16"])
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Temporary PostgreSQL did not start")
        binding = run(["docker", "port", container, "5432/tcp"])
        port = binding.rsplit(":", 1)[1]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "RUNTIME_MODE": "serverless", "APP_ENV": "production",
               "DATABASE_URL": f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres",
               "OPENAI_API_KEY": "offline-test-not-a-real-key", "JWT_SECRET_KEY": secrets.token_hex(32),
               "STORAGE_BACKEND": "s3", "S3_BUCKET": "unused-verification-bucket",
               "DB_POOL_MIN_SIZE": "0", "DB_POOL_MAX_SIZE": "2", "DB_PREPARED_STATEMENTS": "false",
               "STARTUP_MIGRATIONS_ENABLED": "false", "METRIC_SCHEDULER_ENABLED": "false",
               "INDEX_WORKER_ENABLED": "false", "IMPORT_CLEANUP_ENABLED": "false"}
        for _ in range(2):
            run([sys.executable, "-m", "app.migrate", "--bootstrap-sql", str(ROOT / "db/init.sql")], cwd=ROOT / "api", env=env)
        report["explicit_initialization_runs"] = 2
        report["initial"] = json.loads(run([sys.executable, str(Path(__file__).resolve()), "--exercise"], env=env))
        report["new_process"] = json.loads(run([sys.executable, str(Path(__file__).resolve()), "--exercise", "--reconnect"], env=env))
    finally:
        if container:
            label = run(["docker", "inspect", container, "--format", '{{index .Config.Labels "dataez.task"}}'])
            if label != "serverless-foundation":
                raise RuntimeError("Refusing to remove an unowned container")
            run(["docker", "rm", "-f", "-v", container])
            report["temporary_database_removed"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
