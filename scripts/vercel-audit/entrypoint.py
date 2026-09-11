"""Temporary Vercel probe. Never mounts DATA:EZ routes or runs its lifespan."""
import asyncio
import importlib.metadata as metadata
import os
import platform
import resource
import secrets
import time

os.environ.update(
    APP_ENV="production", JWT_SECRET_KEY=secrets.token_hex(32),
    OPENAI_API_KEY="offline-probe-not-a-real-key",
    DATABASE_URL="postgresql://unused:unused@127.0.0.1:1/unused",
    STORAGE_BACKEND="local", LOCAL_STORAGE_PATH="/tmp/dataez-probe",
    METRIC_SCHEDULER_ENABLED="false", IMPORT_CLEANUP_ENABLED="false",
    INDEX_WORKER_ENABLED="false",
)
started = time.perf_counter()
from app.main import app as source_app
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

import_seconds = round(time.perf_counter() - started, 3)
app = FastAPI(title="Temporary DATAEZ dependency probe", docs_url=None, redoc_url=None)


@app.get("/")
def status():
    return {"scope": "dependency probe only", "python": platform.python_version(),
            "source_routes_imported": len(source_app.routes), "source_routes_mounted": False,
            "source_lifespan_executed": False, "import_seconds": import_seconds,
            "database_connected": False, "llm_calls": 0,
            "versions": {n: metadata.version(n) for n in
                         ("fastapi", "pandas", "numpy", "kiwipiepy", "psycopg", "openai")}}


@app.get("/probe")
def probe():
    from app.data_import import prepare_import
    from app.korean_text import tokenize_korean
    started = time.perf_counter()
    words = tokenize_korean("강남점 카드 매출과 현금 매출 비교")
    prepared = prepare_import(("amount,store\n" + "12000,강남점\n" * 1000).encode(), "probe.csv")
    assert words and len(prepared.rows) == 1000
    assert sum(row[0] for row in prepared.rows) == 12_000_000
    return {"passed": True, "rows": len(prepared.rows), "amount_sum": 12_000_000,
            "korean_tokens": words, "seconds": round(time.perf_counter() - started, 3),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


@app.get("/stream")
def stream():
    async def events():
        for i in range(3):
            yield f"data: {i}\n\n"
            await asyncio.sleep(0.01)
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/payload")
async def payload(request: Request):
    return {"received_bytes": len(await request.body())}
