"""Verify Supabase SQL against the live app schema in disposable PostgreSQL.

Storage/auth roles are minimal local shims; this does not test remote Storage.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import quote
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def schema(conn):
    queries = {
        "columns": "SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,is_generated,generation_expression FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,2",
        "constraints": "SELECT c.relname,pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2",
        "indexes": "SELECT tablename,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2",
    }
    return {k: conn.execute(q).fetchall() for k, q in queries.items()}


def main():
    password = secrets.token_hex(24)
    container = None
    report = {"scope": "local PostgreSQL with Supabase role/storage shims"}

    def run(command, **kwargs):
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120, **kwargs)
        if result.returncode:
            raise RuntimeError((result.stderr + result.stdout).replace(password, "[redacted]")[-4000:])
        return result.stdout.strip()

    try:
        container = run(["docker", "run", "-d", "--name", f"dataez-supabase-{uuid4().hex[:8]}",
                         "--label", "dataez.task=supabase-verification", "--memory", "512m",
                         "--tmpfs", "/var/lib/postgresql/data:rw", "-p", "127.0.0.1::5432",
                         "-e", f"POSTGRES_PASSWORD={password}", "pgvector/pgvector:pg16"])
        for _ in range(60):
            if subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres"], capture_output=True).returncode == 0:
                break
            time.sleep(.5)
        port = run(["docker", "port", container, "5432/tcp"]).rsplit(":", 1)[1]
        base = f"postgresql://postgres:{password}@127.0.0.1:{port}/"
        with psycopg.connect(base + "postgres", autocommit=True) as conn:
            conn.execute("CREATE ROLE anon; CREATE ROLE authenticated", prepare=False)
            conn.execute("CREATE DATABASE app_expected")
        with psycopg.connect(base + "postgres", autocommit=True) as conn:
            conn.execute("CREATE DATABASE supabase_candidate")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "RUNTIME_MODE": "serverless", "APP_ENV": "production",
               "OPENAI_API_KEY": "offline-test-not-a-real-key", "JWT_SECRET_KEY": secrets.token_hex(32),
               "STORAGE_BACKEND": "s3", "S3_BUCKET": "unused-verification-bucket",
               "DB_POOL_MIN_SIZE": "0", "DB_POOL_MAX_SIZE": "2", "DB_PREPARED_STATEMENTS": "false",
               "STARTUP_MIGRATIONS_ENABLED": "false", "METRIC_SCHEDULER_ENABLED": "false",
               "INDEX_WORKER_ENABLED": "false", "IMPORT_CLEANUP_ENABLED": "false"}
        for database in ("app_expected", "supabase_candidate"):
            with psycopg.connect(base + database) as conn:
                conn.execute("CREATE SCHEMA extensions; CREATE EXTENSION vector WITH SCHEMA extensions; ALTER DATABASE " + database + " SET search_path=public,extensions", prepare=False)
        run([sys.executable, "-m", "app.migrate", "--bootstrap-sql", str(ROOT / "db/init.sql")],
            cwd=ROOT / "api", env={**env, "DATABASE_URL": base + "app_expected"})
        migrations = sorted((ROOT / "supabase/migrations").glob("*.sql"))
        with psycopg.connect(base + "supabase_candidate") as candidate:
            candidate.execute("CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint)", prepare=False)
            candidate.execute(migrations[0].read_text(encoding="utf-8-sig"), prepare=False)
            for migration in migrations[1:]:
                candidate.execute(migration.read_text(encoding="utf-8-sig"), prepare=False)
        with psycopg.connect(base + "app_expected") as expected, psycopg.connect(base + "supabase_candidate") as candidate:
            a, b = schema(expected), schema(candidate)
            differences = {k: {"missing": [r for r in a[k] if r not in b[k]], "extra": [r for r in b[k] if r not in a[k]]} for k in a if a[k] != b[k]}
            if differences:
                print(json.dumps(differences, ensure_ascii=False))
                raise RuntimeError("Migration differs from runtime schema")
            report["runtime_schema_parity"] = True
        with psycopg.connect(base + "supabase_candidate") as conn:
            conn.execute("SET ROLE dataez_app")
            conn.execute("CREATE TABLE public.test_dynamic_private(id bigint GENERATED ALWAYS AS IDENTITY, value text)")
            conn.execute("INSERT INTO public.test_dynamic_private(value) VALUES ('synthetic')")
            conn.execute("CREATE TABLE public.test_dynamic_copy AS SELECT * FROM public.test_dynamic_private")
            assert conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND (has_table_privilege('anon',format('%I.%I',schemaname,tablename),'SELECT') OR has_table_privilege('authenticated',format('%I.%I',schemaname,tablename),'SELECT'))").fetchone()[0] == 0
            conn.rollback()
            report["dynamic_table_rls_and_denied_client_grants"] = True
        role_options = quote("-c role=dataez_app -c search_path=public,extensions")
        report['upload_transaction_tests'] = run([sys.executable, '-m', 'pytest', 'tests/test_direct_uploads.py', 'tests/test_file_library.py', 'tests/test_maintenance.py', '-q'],
            cwd=ROOT / 'api', env={**os.environ, 'PYTHONIOENCODING':'utf-8', 'DATAEZ_TEST_DATABASE_URL':base+'postgres'})[-600:]
        for reconnect in (False, True):
            command = [sys.executable, str(ROOT / "scripts/serverless/verify.py"), "--exercise"]
            if reconnect:
                command.append("--reconnect")
            result = run(command, env={**env, "DATABASE_URL": base + "supabase_candidate?options=" + role_options})
            report["reconnect" if reconnect else "api_with_backend_role"] = json.loads(result)
    finally:
        if container:
            assert run(["docker", "inspect", container, "--format", '{{index .Config.Labels "dataez.task"}}']) == "supabase-verification"
            run(["docker", "rm", "-f", "-v", container])
            report["temporary_database_removed"] = True
    output = ROOT / "docs/evaluations/vercel-api/supabase-schema-local.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
