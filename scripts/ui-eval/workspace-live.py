"""Real browser → API → configured LLM → PostgreSQL acceptance, in a disposable DB.

The ordinary frontend must be stopped while this runner builds the same checkout.
Its default build is restored in finally. Credentials stay in ignored artifacts.
"""
import argparse
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("acceptance_runtime", Path(__file__).with_name("live-run.py"))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-llm", action="store_true")
    if not parser.parse_args().live_llm:
        parser.error("--live-llm enables paid calls to the configured model")
    admin = os.environ["DATAEZ_TEST_DATABASE_URL"]
    config = conninfo_to_dict(admin)
    if config.get("host") not in {"127.0.0.1", "localhost", "::1"} or config.get("hostaddr"):
        raise ValueError("Use a loopback test PostgreSQL server")
    original = os.environ.copy()
    env = original.copy()
    local = dotenv_values(ROOT / ".env")
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_ORCHESTRATOR_MODEL"):
        if not env.get(key) and local.get(key):
            env[key] = local[key]
    if not env.get("OPENAI_API_KEY"):
        raise ValueError("A configured model key is required")
    name = "dataez_workspace_live_" + uuid4().hex
    out = ROOT / "scripts/ui-eval/artifacts/workspace-live" / name
    out.mkdir(parents=True)
    dsn = make_conninfo(admin, dbname=name)
    api_port, web_port = runtime.free_port(), runtime.free_port()
    env.update(DATABASE_URL=dsn, JWT_SECRET_KEY=secrets.token_hex(32), APP_ENV="development",
               RAG_ENABLED="false", INDEX_WORKER_ENABLED="false", STORAGE_BACKEND="local",
               LOCAL_STORAGE_PATH=str(out / "uploads"), METRIC_SCHEDULER_ENABLED="true", DB_POOL_MIN_SIZE="1", DB_POOL_MAX_SIZE="4",
               IMPORT_CLEANUP_ENABLED="false", REDIS_URL="redis://127.0.0.1:1/0",
               UPLOAD_RATE_LIMIT_PER_MINUTE="100", QUERY_RATE_LIMIT_PER_MINUTE="100",
               ALLOWED_ORIGINS=f"http://127.0.0.1:{web_port}",
               NEXT_PUBLIC_API_URL=f"http://127.0.0.1:{api_port}",
               LIVE_UI_URL=f"http://127.0.0.1:{web_port}", LIVE_ARTIFACTS=str(out), PYTHONIOENCODING="utf-8")
    report = {"run_id": name, "passed": False, "synthetic_data": True, "real_browser": True,
              "real_api": True, "real_postgres": True, "real_llm": True, "api_mocks": False,
              "embeddings_evaluated": False, "checks": [], "browser_phases": []}
    processes, logs = [], []
    created = built = False
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required")

    def check(label, actual, expected):
        ok = actual == expected
        report["checks"].append({"check": label, "actual": actual, "expected": expected, "passed": ok})
        assert ok, f"{label}: {actual!r} != {expected!r}"
        print("PASS: " + label, flush=True)

    def start(args, cwd, label):
        log = (out / f"{label}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN)
        processes.append(process)
        return process

    def start_api(label):
        process = start([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)], ROOT / "api", label)
        runtime.wait_http(env["NEXT_PUBLIC_API_URL"] + "/health", process)
        return process

    def browser(phase):
        process = start([node, "workspace-live.cjs", phase], ROOT / "scripts/ui-eval", "browser-" + phase)
        code = process.wait(timeout=900)
        result_path = out / f"browser-{phase}.json"
        if result_path.exists():
            report["browser_phases"].append(json.loads(result_path.read_text(encoding="utf-8")))
        if code:
            raise RuntimeError(f"Browser {phase} failed; inspect {result_path}")
        print("PASS: real browser " + phase, flush=True)

    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
        created = True
        with psycopg.connect(dsn) as conn:
            conn.execute((ROOT / "db/init.sql").read_text(encoding="utf-8"))
        api = start_api("api-first")
        with httpx.Client(base_url=env["NEXT_PUBLIC_API_URL"], timeout=180) as client:
            def request(method, path, **kwargs):
                res = client.request(method, path, **kwargs)
                if not res.is_success:
                    raise AssertionError(f"{method} {path}: {res.status_code}: {res.text[:400]}")
                return res.json()

            email, password = name + "@example.test", secrets.token_urlsafe(24) + "Aa1!"
            account = request("POST", "/api/auth/signup", json={"name": "통합 검증", "email": email, "password": password})
            client.headers["Authorization"] = "Bearer " + account["access_token"]
            other = request("POST", "/api/projects", json={"name": "연남점"})["id"]
            external = request("POST", "/api/library/files", data={"project_id": other}, files={"file": ("연남점_매출.csv", b"paid_at,amount\n2026-09-01,54321.09\n")})
            external = request("POST", f"/api/library/files/{external['file_id']}/prepare", json={"project_id": other})
            store = request("POST", "/api/projects", json={"name": "성수점"})["id"]
            outside = request("POST", f"/api/projects/{store}/tables/import", data={"table_name": "선택하지 않은 매출"}, files={"file": ("outside.csv", b"paid_at,amount\n2026-09-01,999999.99\n")})
            csv = "paid_at,amount,method\n2026-09-01,100000.01,카드\n2026-09-02,200000.02,카드\n2026-09-02,-50000.00,카드\n2026-09-03,80000.03,현금\n"
            (out / "성수점_9월_매출.csv").write_text(csv, encoding="utf-8", newline="")
            dump(out / "browser-input.json", {"email": email, "password": password, "project_id": store,
                "other_project_id": other, "other_file_id": external["file_id"], "filename": "성수점_9월_매출.csv"})
            print(f"Run: {out}\nBuilding isolated-API frontend; configured model will be used", flush=True)
            built = True
            build = start([node, "node_modules/next/dist/bin/next", "build"], ROOT / "web", "build")
            if build.wait(timeout=240):
                raise RuntimeError("Web build failed")
            web = start([node, "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(web_port)], ROOT / "web", "web")
            runtime.wait_http(env["LIVE_UI_URL"], web)
            browser("initial")
            checkpoint = json.loads((out / "checkpoint.json").read_text(encoding="utf-8"))
            wid, tid = checkpoint["widget_id"], checkpoint["table_id"]
            base = f"/api/projects/{store}"

            def metric():
                return next(widget for widget in request("GET",f"/api/dashboard/widgets?project_id={store}")["widgets"] if widget["id"] == wid)

            def total(widget):
                data = widget["widget_data"]
                return str(sum(Decimal(str(row[data["y_key"]])) for row in data["data"]))

            before = metric()
            check("Manual refresh includes the appended transaction", total(before), "355000.10")
            check("Saved widget uses the selected source", str(before["widget_data"]["metric_definition"]["table_id"]), tid)
            check("Source count is unchanged by file selection", len(request("GET", base + "/tables")["tables"]), 2)
            check("Hourly refresh persists", before["refresh_interval_seconds"], 3600)
            # Real public append endpoint; only the due timestamp is advanced below.
            request("POST", base + f"/tables/{tid}/append", files={"file": ("next.csv", "paid_at,amount,method\n2026-09-03,5000.05,현금\n".encode())})
            with psycopg.connect(dsn) as conn:
                conn.execute("UPDATE dashboard_widgets SET next_refresh_at=now()-interval '1 second' WHERE id=%s", (wid,))
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                refreshed = metric()
                if total(refreshed) == "360000.15":
                    break
                time.sleep(1)
            else:
                raise AssertionError("Production scheduler did not refresh with browser closed")
            check("Background refresh works with every test browser closed", total(refreshed), "360000.15")
            check("Background refresh preserves layout", refreshed["layout"], before["layout"])
            check("Background refresh preserves definition", refreshed["widget_data"]["metric_definition"], before["widget_data"]["metric_definition"])
            report["due_time_advanced"] = True
            report["scheduler_poll_seconds"] = 15

            runtime.stop(api)
            api = start_api("api-restarted")
            after = metric()
            for field in ("widget_data", "layout", "save_key", "refresh_interval_seconds", "next_refresh_at"):
                check("API restart preserves " + field, after[field], refreshed[field])
            browser("resumed")
            check("Ledger and original scopes create exactly two requested widgets", len(request("GET", f"/api/dashboard/widgets?project_id={store}")["widgets"]), 2)
            check("Original download still has four original rows", client.get(f"/api/library/files/{checkpoint['file_id']}/download").content.decode(), csv)
            tables = request("GET", base + "/tables")["tables"]
            check("Connected ledger includes both later appends", next(t["row_count"] for t in tables if t["id"] == tid), 6)
            check("Unselected ledger was not changed", next(t["row_count"] for t in tables if t["id"] == outside["id"]), 1)

            # Use a second real account to test authorization with the exact known IDs.
            stranger = request("POST", "/api/auth/signup", json={"name": "별도 계정", "email": "other-" + email, "password": secrets.token_urlsafe(24) + "Aa1!"})
            stranger_headers = {"Authorization": "Bearer " + stranger["access_token"]}
            check("Other account cannot download the selected file", client.get(f"/api/library/files/{checkpoint['file_id']}/download", headers=stranger_headers).status_code, 404)
            check("Other account cannot list the store widgets", client.get(f"/api/dashboard/widgets?project_id={store}", headers=stranger_headers).status_code, 404)
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                messages = conn.execute("SELECT m.content,m.steps,m.usage FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=%s AND m.role='assistant' ORDER BY m.created_at", (account["user_id"],)).fetchall()
            report["model_messages"] = messages
            check("Six real model responses were persisted", len(messages), 6)
            report["passed"] = True
    except Exception as exc:
        report["failure"] = str(exc)
        raise
    finally:
        for process in reversed(processes):
            runtime.stop(process)
        if created:
            assert name.startswith("dataez_workspace_live_") and len(name) == len("dataez_workspace_live_") + 32
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            report["temporary_database_removed"] = True
        if built:
            with (out / "restore-build.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([node, "node_modules/next/dist/bin/next", "build"], cwd=ROOT / "web", env=original,
                    stdout=log, stderr=subprocess.STDOUT, creationflags=runtime.HIDDEN, timeout=240)
            report["ordinary_web_build_restored"] = result.returncode == 0
            report["passed"] &= result.returncode == 0
        for log in logs:
            log.close()
        dump(out / "report.json", report)
        print("Report: " + str(out / "report.json"), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
