"""Provision this project's backend login and ignored local Supabase settings.

Requires `supabase login` and the already applied migrations.
Never prints credentials. Reuses an existing local configuration on later runs.
"""
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import subprocess
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parents[2]
REF = "whbygnzoaehvlddltwlb"
ENV_FILE = ROOT / ".env.supabase.local"


def main():
    cli = shutil.which("supabase")
    if not cli:
        raise RuntimeError("Supabase CLI is required")

    def command(args):
        result = subprocess.run([cli, *args, "--profile", "supabase"], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        if result.returncode:
            # CLI errors can echo SQL, URIs or API keys: do not print raw output.
            raise RuntimeError("Supabase CLI command failed; check profile/project access")
        return result.stdout

    assert (ROOT / "supabase/.temp/project-ref").read_text().strip() == REF
    if subprocess.run(["git", "check-ignore", "--quiet", str(ENV_FILE)], cwd=ROOT).returncode:
        raise RuntimeError("Refusing to write credentials outside a Git-ignored path")
    pooler = urlsplit((ROOT / "supabase/.temp/pooler-url").read_text().strip())
    assert pooler.username == "postgres." + REF
    assert pooler.hostname.endswith(".pooler.supabase.com")
    values = dict(dotenv_values(ENV_FILE)) if ENV_FILE.exists() else {}
    if not values.get("DATABASE_URL"):
        password = secrets.token_hex(32)
        sql_file = ROOT / ".local-test/supabase/provision-login.sql"
        sql_file.parent.mkdir(parents=True, exist_ok=True)
        sql_file.write_text("ALTER ROLE dataez_app LOGIN PASSWORD '" + password + "';", encoding="utf-8")
        try:
            command(["db", "query", "--linked", "--file", str(sql_file), "--output", "json"])
        finally:
            sql_file.unlink(missing_ok=True)
        values["DATABASE_URL"] = (f"postgresql://dataez_app.{REF}:{quote(password, safe='')}@"
                                  f"{pooler.hostname}:6543/postgres?sslmode=require")
    if not values.get("SUPABASE_SECRET_KEY", "").isascii() or not values.get("SUPABASE_SECRET_KEY"):
        keys = json.loads(command(["projects", "api-keys", "--project-ref", REF, "--output", "json"]))
        active = [k for k in keys if not k.get("disabled")]
        # Listing modern secret keys may return masked Unicode, not a usable key.
        selected = next((k for k in active if re.fullmatch(r"sb_secret_[A-Za-z0-9_-]{20,}", k.get("api_key", ""))), None)
        if selected is None:
            selected = next((k for k in active if k.get("name") == "service_role"), None)
        if not selected:
            raise RuntimeError("No server API key returned for DATAEZ")
        values["SUPABASE_SECRET_KEY"] = selected["api_key"]
    local = dotenv_values(ROOT / ".env")
    values.setdefault("OPENAI_API_KEY", local.get("OPENAI_API_KEY", ""))
    values.setdefault("JWT_SECRET_KEY", secrets.token_hex(32))
    values.update({"APP_ENV": "production", "RUNTIME_MODE": "serverless", "STORAGE_BACKEND": "supabase",
                   "SUPABASE_URL": f"https://{REF}.supabase.co", "SUPABASE_STORAGE_BUCKET": "dataez-files",
                   "ALLOWED_ORIGINS": "https://dataez.vercel.app", "S3_PREFIX": "uploads"})
    # dotenv quoting preserves special characters; keys are not emitted to stdout.
    ENV_FILE.write_text("\n".join(f"{k}='{v.replace(chr(39), chr(92) + chr(39))}'" for k, v in values.items()) + "\n", encoding="utf-8")
    with psycopg.connect(values["DATABASE_URL"], connect_timeout=10, prepare_threshold=None) as conn:
        role, table_count = conn.execute("SELECT current_user,(SELECT count(*) FROM pg_tables WHERE schemaname='public')").fetchone()
        assert role == "dataez_app" and table_count >= 25
        # pg_stat_ssl describes pooler->Postgres, not this client's TLS session.
        assert conn.pgconn.ssl_in_use
        for _ in range(8):
            conn.execute("SELECT %s::int", (123,)).fetchone()
        assert conn.execute("SELECT count(*) FROM pg_prepared_statements").fetchone()[0] == 0
    print(json.dumps({"project_ref": REF, "backend_role": role, "transaction_pooler_connected": True,
                      "tls": True, "local_config": ENV_FILE.name,
                      "storage_key_kind": "secret" if values["SUPABASE_SECRET_KEY"].startswith("sb_secret_") else "legacy_service_role"}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Connection errors can contain a DSN. Keep failure output free of secrets.
        print("Supabase configuration failed:", type(error).__name__)
        raise SystemExit(1)
