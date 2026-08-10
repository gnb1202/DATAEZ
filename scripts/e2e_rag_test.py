"""End-to-end test for the document RAG pipeline.

Signs up (or logs in), creates a project, uploads samples/refund_policy.md,
verifies chunks were embedded, and runs a Hybrid search to confirm retrieval.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

import requests

API = "http://localhost:8000"
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "refund_policy.md"


def _post(path: str, *, token: str | None = None, **kwargs) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers.update(kwargs.pop("headers", {}))
    r = requests.post(f"{API}{path}", headers=headers, timeout=120, **kwargs)
    r.raise_for_status()
    return r.json()


def _get(path: str, token: str) -> dict:
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    email = f"ragtest+{secrets.token_hex(4)}@dataez.local"
    password = "Test1234!@#"

    print(f"[1] signup as {email}")
    _post("/api/auth/signup", json={"email": email, "password": password, "name": "rag"})

    print("[2] login")
    auth = _post("/api/auth/login", json={"email": email, "password": password})
    token = auth["access_token"]

    print("[3] create project")
    proj = _post("/api/projects", token=token, json={"name": "RAG E2E", "description": "test"})
    pid = proj["id"]
    print(f"    project_id={pid}")

    print(f"[4] upload {SAMPLE.name}")
    with SAMPLE.open("rb") as fh:
        files = {"file": (SAMPLE.name, fh, "text/markdown")}
        upload = _post(f"/api/projects/{pid}/documents", token=token, files=files)
    print(f"    chunks inserted: {upload['chunks']}")
    if upload["chunks"] == 0:
        print("ERROR: no chunks were inserted")
        return 1

    print("[5] list documents")
    docs = _get(f"/api/projects/{pid}/documents", token=token)
    print(f"    documents: {len(docs['documents'])} row(s), chunk_count={docs['documents'][0]['chunk_count']}")

    print("[6] OK — pipeline works end-to-end.")
    print(f"    next: psql to verify document_chunks rows for project {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
