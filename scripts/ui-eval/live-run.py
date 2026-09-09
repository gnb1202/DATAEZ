"""Disposable, real PostgreSQL/API/browser acceptance run (no API mocks or LLM).

Requires DATAEZ_TEST_DATABASE_URL pointing at a local test PostgreSQL server,
Python API dependencies, web/node_modules and ui-eval/node_modules. The role
must be able to CREATE DATABASE. All application writes use a fresh database.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url, process):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited with {process.returncode}; inspect run logs")
        try:
            with urlopen(url, timeout=2) as res:
                if res.status == 200:
                    return
        except (OSError, TimeoutError):
            time.sleep(0.3)
    raise TimeoutError(f"Server did not become ready: {url}")


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_indexes(request, base, timeout=120):
    """I: imports commit before background indexing; acceptance waits explicitly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = request('GET', base + '/search-index')
        if state['counts'].get('failed'):
            raise AssertionError('Index failed: ' + str(state))
        if not any(state['counts'].get(s) for s in ['pending', 'processing', 'retry']):
            return state
        time.sleep(.3)
    raise TimeoutError('Search indexing did not finish: ' + str(state))


def main():
    admin = os.environ["DATAEZ_TEST_DATABASE_URL"]
    config = conninfo_to_dict(admin)
    if config.get("host") not in {"127.0.0.1", "localhost", "::1"} or config.get("hostaddr"):
        raise ValueError("Only a loopback test PostgreSQL server is accepted")
    name = "dataez_live_" + uuid4().hex
    db_url = make_conninfo(admin, dbname=name)
    artifacts = ROOT / "scripts/ui-eval/artifacts/live" / name
    artifacts.mkdir(parents=True)
    api_port, web_port = free_port(), free_port()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required")
    env = {**os.environ, "DATABASE_URL": db_url, "APP_ENV": "development",
           "JWT_SECRET_KEY": secrets.token_hex(32), "OPENAI_API_KEY": "unused-live-test-key",
           "RAG_ENABLED": "false", "STORAGE_BACKEND": "local",
           "LOCAL_STORAGE_PATH": str(artifacts / "uploads"),
           "METRIC_SCHEDULER_ENABLED": "true", "IMPORT_CLEANUP_ENABLED": "true",
           "REDIS_URL": "redis://127.0.0.1:1/0", "UPLOAD_RATE_LIMIT_PER_MINUTE": "100",
           "ALLOWED_ORIGINS": f"http://127.0.0.1:{web_port}",
           "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{api_port}",
           "LIVE_UI_URL": f"http://127.0.0.1:{web_port}", "LIVE_ARTIFACTS": str(artifacts)}
    api = web = None
    logs = []
    created = False
    report = {"database": name, "api_mocks": False, "files": "synthetic CSV",
              "llm_evaluated": False, "business_files_evaluated": False, "passed": False}
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(db_url) as conn:
            conn.execute((ROOT / "db/init.sql").read_text(encoding="utf-8"))

        def start_api(label):
            log = (artifacts / f"api-{label}.log").open("w", encoding="utf-8")
            logs.append(log)
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                     "--port", str(api_port)], cwd=ROOT / "api", env=env,
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=HIDDEN)
            return proc

        api = start_api("first")
        wait_http(env["NEXT_PUBLIC_API_URL"] + "/health", api)
        print("Real API started on an isolated database; building web", flush=True)
        with (artifacts / "build.log").open("w", encoding="utf-8") as build_log:
            subprocess.run([node, "node_modules/next/dist/bin/next", "build"], cwd=ROOT / "web", env=env,
                           stdout=build_log, stderr=subprocess.STDOUT, check=True, creationflags=HIDDEN)
        log = (artifacts / "web.log").open("w", encoding="utf-8")
        logs.append(log)
        web = subprocess.Popen([node, "node_modules/next/dist/bin/next", "start", "-p", str(web_port), "-H", "127.0.0.1"],
                               cwd=ROOT / "web", env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=HIDDEN)
        wait_http(env["LIVE_UI_URL"], web)

        def browser(phase):
            result = subprocess.run([node, "live-workflow.cjs", phase], cwd=Path(__file__).parent, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=HIDDEN)
            output = result.stdout.decode("utf-8", errors="replace")
            (artifacts / f"browser-{phase}.log").write_text(output, encoding="utf-8")
            print(output, flush=True)
            result.check_returncode()

        browser("initial")  # Process exit closes every browser/context.
        checkpoint = json.loads((artifacts / "checkpoint.json").read_text(encoding="utf-8"))
        with (artifacts / "chat-tool.log").open("w", encoding="utf-8") as tool_log:
            subprocess.run([sys.executable, str(Path(__file__).with_name("live-chat.py")), str(artifacts / "checkpoint.json")],
                           env=env, stdout=tool_log, stderr=subprocess.STDOUT, check=True, creationflags=HIDDEN)
        metric_id = checkpoint["metricId"]

        def metric():
            with psycopg.connect(db_url, row_factory=dict_row) as conn:
                return conn.execute("SELECT * FROM dashboard_widgets WHERE id=%s", (metric_id,)).fetchone()

        before = metric()
        assert str(before["widget_data"]["value"]) == "250000", before["widget_data"]
        # Advance ONLY this test widget's due time; keep the production 15s loop
        # and hourly interval unchanged. This does not simulate an elapsed hour.
        with psycopg.connect(db_url) as conn:
            conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s", (metric_id,))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            refreshed = metric()
            if str(refreshed["widget_data"]["value"]) == "300000":
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Scheduler did not refresh after all browsers closed")
        assert before["layout"] == refreshed["layout"]
        assert before["widget_data"]["metric_definition"] == refreshed["widget_data"]["metric_definition"]
        assert refreshed["refresh_interval_seconds"] == 3600 and refreshed["refresh_failures"] == 0
        report["background_refresh"] = {"before": "250000", "after": "300000", "due_time_advanced": True}
        print("Browser closed: production scheduler refreshed 250000 -> 300000", flush=True)
        stop(api)  # Abrupt worker restart also tests persisted sessions/definitions.
        api = start_api("restart")
        wait_http(env["NEXT_PUBLIC_API_URL"] + "/health", api)
        after = metric()
        for field in ("widget_data", "layout", "refresh_interval_seconds", "next_refresh_at"):
            assert after[field] == refreshed[field], field
        browser("resumed")
        report["restart_persistence"] = True
        report["chat_review_link"] = "real read tool; fixed message; no model call"
        report["passed"] = True
    finally:
        stop(web)
        stop(api)
        for log in logs:
            log.close()
        if created:
            # Name is generated here, never supplied by the user or config.
            assert name.startswith("dataez_live_") and len(name) == 44
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            report["temporary_database_removed"] = True
        (artifacts / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {artifacts / 'report.json'}", flush=True)
    print("PASS: real browser/API/PostgreSQL workflow and worker restart", flush=True)


if __name__ == "__main__":
    main()
