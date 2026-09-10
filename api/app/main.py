import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from .logging_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from .exceptions import ResourceNotFound, FileTooLarge, UnsupportedFileType
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from decimal import Decimal
from .import_validation import ImportValidationError
from .agent import AgentResult, _parse_suggestions, run_agent, run_agent_streaming

# Emitted while the agent is busy (typically inside a long tool call) so an
# in-progress turn stays distinguishable from a dead connection. Must stay
# comfortably below the client's stream timeout.
SSE_HEARTBEAT_SECONDS = 15
from .auth import get_current_user, login, logout_refresh_token, refresh_access_token, signup
from .config import settings
from .db import (
    cleanup_expired_refresh_tokens,
    cleanup_old_conversations,
    close_pool,
    create_conversation,
    create_project,
    delete_conversation,
    create_table_meta,
    create_user_data_table,
    create_widget,
    delete_file,
    delete_project,
    delete_table_meta,
    delete_widget,
    drop_user_data_table,
    ensure_audit_log_table,
    ensure_conversation_tables,
    ensure_dashboard_widgets_table,
    ensure_performance_indexes,
    ensure_project_tables,
    ensure_ledger_import_tables,
    ensure_rag_tables,
    get_conversation,
    get_file,
    get_project,
    get_table_meta,
    get_user_table_name,
    list_conversations,
    list_files,
    list_audit_logs,
    list_project_documents,
    list_projects,
    list_table_metas,
    list_messages,
    purge_soft_deleted,
    list_widgets,
    record_audit,
    run_startup_migrations,
    save_file,
    save_message,
    touch_conversation,
    update_conversation_title,
    update_project,
    update_table_meta,
    update_widgets_layout,
)
from .rate_limiter import rate_limiter
from .schemas import (
    AppendResponse,
    AuthTokenResponse,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateProjectRequest,
    CreateTableRequest,
    CreateWidgetRequest,
    FileListResponse,
    FileResponse,
    LoginRequest,
    LogoutRequest,
    MessageListResponse,
    MessageResponse,
    ProjectListResponse,
    ProjectResponse,
    RefreshRequest,
    SignupRequest,
    StatusResponse,
    TableDataResponse,
    TableListResponse,
    TableMetaResponse,
    UpdateLayoutRequest,
    UpdateProjectRequest,
    UpdateTableRequest,
    UserResponse,
    WidgetListResponse,
    WidgetResponse,
)
from .library_schema import ensure_library
from .widget_saves import ensure_widget_saves
from .library_routes import router as library_router
from .file_library import resolve_references, reference_step
from .storage import StorageService
from .table_imports import create_imported_table, append_imported_table
from .dashboard_metrics import router as dashboard_metrics_router
from .index_jobs import ensure_index_jobs, run_index_worker, register_document
from .index_routes import router as index_router
from .metric_revisions import ensure_metric_revisions, router as metric_revisions_router
from .cash_entries import router as cash_router
from .metric_scheduler import run_metric_scheduler
from .ledger_routes import router as ledger_router, run_import_cleanup


# ---------------------------------------------------------------------------
# Ownership dependencies (중앙집중 소유권 검증)
# ---------------------------------------------------------------------------

def _get_owned_project(
    project_id: str, user: dict[str, str] = Depends(get_current_user)
) -> dict[str, Any]:
    """FastAPI dependency — resolves and validates project ownership."""
    project = get_project(project_id, user["id"])
    if not project:
        raise ResourceNotFound("Project")
    return project


def _get_owned_table(
    project_id: str, table_id: str, user: dict[str, str] = Depends(get_current_user)
) -> dict[str, Any]:
    """FastAPI dependency — resolves and validates table ownership within a project."""
    meta = get_table_meta(table_id, user["id"])
    if not meta or str(meta["project_id"]) != project_id:
        raise ResourceNotFound("Table")
    return meta


def _get_owned_conversation(
    conversation_id: str, user: dict[str, str] = Depends(get_current_user)
) -> dict[str, Any]:
    """FastAPI dependency — resolves and validates conversation ownership."""
    conv = get_conversation(conversation_id, user["id"])
    if not conv:
        raise ResourceNotFound("Conversation")
    return conv


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown handlers (replaces deprecated @app.on_event)."""
    run_startup_migrations()
    ensure_conversation_tables()
    ensure_dashboard_widgets_table()
    ensure_metric_revisions()
    ensure_project_tables()
    ensure_ledger_import_tables()
    ensure_audit_log_table()
    if not settings.rag_enabled:
        ensure_index_jobs()
    ensure_rag_tables()
    ensure_performance_indexes()
    ensure_library()
    ensure_widget_saves()
    # Periodic cleanup on restart
    cleanup_old_conversations()
    cleanup_expired_refresh_tokens()
    purge_soft_deleted()

    stop_scheduler = asyncio.Event()
    scheduler = asyncio.create_task(run_metric_scheduler(stop_scheduler)) if settings.metric_scheduler_enabled else None
    import_cleanup = asyncio.create_task(run_import_cleanup(stop_scheduler)) if settings.import_cleanup_enabled else None
    index_worker = asyncio.create_task(run_index_worker(stop_scheduler)) if settings.rag_enabled and settings.index_worker_enabled else None
    try:
        yield
    finally:
        stop_scheduler.set()
        if index_worker:
            await index_worker
        if import_cleanup:
            await import_cleanup
        if scheduler:
            # Let the in-flight bounded SQL query commit/rollback before closing
            # its pool; cancelling to_thread would not stop the actual thread.
            await scheduler
        close_pool()


app = FastAPI(
    title="DATAEZ API",
    version="0.3.0",
    lifespan=lifespan,
    description="소상공인을 위한 AI 기반 데이터 관리 및 시각화 API",
    openapi_tags=[
        {"name": "auth", "description": "인증 및 사용자 관리"},
        {"name": "projects", "description": "프로젝트(사업장) 관리"},
        {"name": "tables", "description": "장부(테이블) 관리 및 데이터 가져오기/내보내기"},
        {"name": "conversations", "description": "AI 대화 관리"},
        {"name": "dashboard", "description": "대시보드 위젯"},
        {"name": "files", "description": "파일 업로드"},
    ],
)
storage = StorageService()


@app.exception_handler(ImportValidationError)
async def import_validation_error_handler(_request: Request, exc: ImportValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.detail, "code": exc.code, "issues": exc.issues})


_allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.include_router(dashboard_metrics_router)
app.include_router(metric_revisions_router)
app.include_router(cash_router)
app.include_router(library_router)
app.include_router(ledger_router)
app.include_router(index_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_tracking(request: Request, call_next):
    import time
    from .logging_config import request_id_var, user_id_var
    from .metrics import (
        http_request_duration_seconds,
        http_requests_total,
        route_label,
    )

    # A client-supplied X-Request-ID is echoed into logs, so cap and strip it
    # rather than trusting arbitrary header content.
    raw_req_id = request.headers.get("X-Request-ID", "")
    req_id = "".join(c for c in raw_req_id if c.isalnum() or c in "-_")[:64] or str(uuid4())[:8]
    request_id_var.set(req_id)
    user_id_var.set("")  # reset per request

    t0 = time.monotonic()
    logger.info("-> %s %s", request.method, request.url.path)
    response = await call_next(request)
    elapsed_s = time.monotonic() - t0
    logger.info(
        "<- %s %s %d %.0fms", request.method, request.url.path, response.status_code, elapsed_s * 1000
    )

    # Route template, not request.url.path: the raw path embeds project and
    # conversation UUIDs, which would mint a new time series per entity.
    route = route_label(request)
    http_requests_total.labels(
        method=request.method, route=route, status=str(response.status_code)
    ).inc()
    http_request_duration_seconds.labels(method=request.method, route=route).observe(elapsed_s)

    response.headers["X-Request-ID"] = req_id
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage_backend": settings.storage_backend}


@app.get("/ready")
def readiness() -> dict[str, Any]:
    """Readiness probe — checks the required PostgreSQL connection."""
    checks: dict[str, str] = {}
    try:
        from .db import _connect
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "degraded", "checks": checks})
    return {"status": "ok", "checks": checks}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    from fastapi.responses import Response
    from .metrics import render

    payload, content_type = render()
    return Response(content=payload, media_type=content_type)


# ---------------------------------------------------------------------------
# Auth endpoints (unchanged)
# ---------------------------------------------------------------------------

@app.post("/api/auth/signup", tags=["auth"], summary="회원가입")
def auth_signup(payload: SignupRequest, request: Request) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"signup:{client_ip}", settings.auth_rate_limit_per_minute, 60)
    return signup(payload.email.strip().lower(), payload.password, payload.name.strip())


@app.post("/api/auth/login", tags=["auth"], summary="로그인")
def auth_login(payload: LoginRequest, request: Request) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login:{client_ip}", settings.auth_rate_limit_per_minute, 60)
    return login(payload.email.strip().lower(), payload.password)


@app.post("/api/auth/refresh", tags=["auth"], summary="토큰 갱신")
def auth_refresh(payload: RefreshRequest, request: Request) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"refresh:{client_ip}", settings.auth_rate_limit_per_minute, 60)
    return refresh_access_token(payload.refresh_token.strip())


@app.post("/api/auth/logout", tags=["auth"], summary="로그아웃")
def auth_logout(payload: LogoutRequest) -> dict[str, str]:
    logout_refresh_token(payload.refresh_token.strip())
    return {"status": "ok"}


@app.get("/api/auth/me", tags=["auth"], summary="현재 사용자 정보")
def auth_me(user: dict[str, str] = Depends(get_current_user)) -> dict[str, str]:
    return {"user_id": user["id"], "email": user["email"]}


# ---------------------------------------------------------------------------
# Project endpoints (프로젝트 / 사업장)
# ---------------------------------------------------------------------------



@app.post("/api/projects", tags=["projects"], summary="프로젝트 생성")
def api_create_project(
    payload: CreateProjectRequest, user: dict[str, str] = Depends(get_current_user)
) -> dict[str, Any]:
    project_id = str(uuid4())
    project = create_project(project_id, user["id"], payload.name.strip(), payload.description.strip())
    record_audit(user["id"], "create", "project", project_id, {"name": payload.name.strip()})
    return project


@app.get("/api/projects", tags=["projects"], summary="프로젝트 목록 조회")
def api_list_projects(
    user: dict[str, str] = Depends(get_current_user),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
) -> dict[str, Any]:
    projects = list_projects(user["id"], limit=limit, offset=offset, search=q or None)
    return {"projects": projects, "limit": limit, "offset": offset}


@app.get("/api/projects/{project_id}", tags=["projects"], summary="프로젝트 상세 조회")
def api_get_project(project: dict[str, Any] = Depends(_get_owned_project)) -> dict[str, Any]:
    return project


@app.put("/api/projects/{project_id}", tags=["projects"], summary="프로젝트 수정")
def api_update_project(
    project_id: str, payload: UpdateProjectRequest, user: dict[str, str] = Depends(get_current_user), project: dict[str, Any] = Depends(_get_owned_project)
) -> dict[str, str]:
    update_project(project_id, user["id"], name=payload.name, description=payload.description)
    record_audit(user["id"], "update", "project", project_id, {"name": payload.name, "description": payload.description})
    return {"status": "ok"}


@app.delete("/api/projects/{project_id}", tags=["projects"], summary="프로젝트 삭제")
def api_delete_project(project_id: str, request: Request, user: dict[str, str] = Depends(get_current_user)) -> dict[str, str]:
    rate_limiter.check(f"delete:{user['id']}", settings.delete_rate_limit_per_minute, 60)
    if not delete_project(project_id, user["id"]):
        raise ResourceNotFound("Project")
    record_audit(user["id"], "delete", "project", project_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Table endpoints (장부)
# ---------------------------------------------------------------------------



@app.post("/api/projects/{project_id}/tables", tags=["tables"], summary="장부 생성")
def api_create_table(
    project_id: str,
    payload: CreateTableRequest,
    user: dict[str, str] = Depends(get_current_user),
    _project: dict[str, Any] = Depends(_get_owned_project),
) -> dict[str, Any]:
    table_id = str(uuid4())
    columns_schema = payload.columns if payload.columns else []

    # Create the actual PG table if columns are provided
    if columns_schema:
        create_user_data_table(user["id"], table_id, columns_schema)

    meta = create_table_meta(
        table_id=table_id,
        project_id=project_id,
        user_id=user["id"],
        name=payload.name.strip(),
        description=payload.description.strip(),
        columns_schema=columns_schema,
    )
    record_audit(user["id"], "create", "table", table_id, {"name": payload.name.strip(), "project_id": project_id})
    return meta


@app.get("/api/projects/{project_id}/tables", tags=["tables"], summary="장부 목록 조회")
def api_list_tables(
    project_id: str, user: dict[str, str] = Depends(get_current_user), _project: dict[str, Any] = Depends(_get_owned_project)
) -> dict[str, Any]:
    return {"tables": list_table_metas(project_id, user["id"])}


@app.get("/api/projects/{project_id}/tables/{table_id}")
def api_get_table(
    meta: dict[str, Any] = Depends(_get_owned_table),
) -> dict[str, Any]:
    return meta


@app.put("/api/projects/{project_id}/tables/{table_id}")
def api_update_table(
    table_id: str,
    payload: UpdateTableRequest,
    user: dict[str, str] = Depends(get_current_user),
    _meta: dict[str, Any] = Depends(_get_owned_table),
) -> dict[str, str]:
    update_table_meta(table_id, user["id"], name=payload.name, description=payload.description)
    record_audit(user["id"], "update", "table", table_id, {"name": payload.name, "description": payload.description})
    return {"status": "ok"}


@app.delete("/api/projects/{project_id}/tables/{table_id}")
def api_delete_table(
    project_id: str, table_id: str, request: Request, user: dict[str, str] = Depends(get_current_user), _meta: dict[str, Any] = Depends(_get_owned_table)
) -> dict[str, str]:
    rate_limiter.check(f"delete:{user['id']}", settings.delete_rate_limit_per_minute, 60)
    drop_user_data_table(user["id"], table_id)
    delete_table_meta(table_id, user["id"])
    record_audit(user["id"], "delete", "table", table_id, {"project_id": project_id})
    return {"status": "ok"}


@app.get("/api/projects/{project_id}/tables/{table_id}/export", tags=["tables"], summary="장부 CSV 내보내기")
async def api_export_table(
    table_id: str,
    user: dict[str, str] = Depends(get_current_user),
    meta: dict[str, Any] = Depends(_get_owned_table),
) -> StreamingResponse:
    """Export table data as CSV download."""
    from .sql_executor import export_table_csv

    pg_table_name = get_user_table_name(user["id"], table_id)
    csv_content = await asyncio.to_thread(export_table_csv, pg_table_name, user["id"])

    filename = f"{meta['name']}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/{project_id}/tables/import", tags=["tables"], summary="CSV/XLSX 가져오기")
async def api_import_table(
    project_id: str,
    file: UploadFile = File(...),
    request: Request = None,
    user: dict[str, str] = Depends(get_current_user),
    table_name: str = Form(default=""),
) -> dict[str, Any]:
    """Upload CSV/XLSX → create a new table + import data."""
    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    _get_owned_project(project_id, user)

    allowed_types = (".csv", ".xlsx", ".xls")
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(allowed_types):
        raise UnsupportedFileType(filename)

    max_upload_size = settings.max_upload_size_mb * 1024 * 1024
    content = await file.read(max_upload_size + 1)
    if len(content) > max_upload_size:
        raise FileTooLarge(settings.max_upload_size_mb)

    display_name = table_name.strip() if table_name.strip() else filename.rsplit(".", 1)[0]
    meta = await asyncio.to_thread(create_imported_table, user["id"], project_id, display_name, content, filename, storage)
    table_id = str(meta["id"])
    # A committed import must not look failed because indexing is unavailable.
    try:
        await asyncio.to_thread(record_audit, user["id"], "import", "table", table_id,
                                {"name": display_name, "project_id": project_id, "filename": filename, "row_count": meta["row_count"]})
    except Exception:
        logger.exception("Import committed but audit/index update failed for table %s", table_id)
    return meta


@app.post("/api/projects/{project_id}/documents", tags=["documents"], summary="문서 업로드 (RAG용 PDF/MD/TXT)")
async def api_upload_document(
    project_id: str,
    file: UploadFile = File(...),
    user: dict[str, str] = Depends(get_current_user),
    _project: dict[str, Any] = Depends(_get_owned_project),
) -> dict[str, Any]:
    """Upload PDF/MD/TXT → persist original + background search job.

    Used by the search_documents agent tool for unstructured Q&A.
    """

    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)

    allowed_types = (".pdf", ".md", ".txt")
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(allowed_types):
        raise UnsupportedFileType(filename)

    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    max_upload_size = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_upload_size:
        raise FileTooLarge(settings.max_upload_size_mb)

    result = await asyncio.to_thread(register_document, user['id'], project_id, filename, content, storage)
    try:
        record_audit(user['id'], 'import', 'document', result['file_id'], {'filename': filename, 'project_id': project_id})
    except Exception:
        logger.exception('Document registered but audit logging failed: %s', result['file_id'])
    return result


@app.get("/api/projects/{project_id}/documents", tags=["documents"], summary="프로젝트 문서 목록")
def api_list_documents(
    project_id: str,
    user: dict[str, str] = Depends(get_current_user),
    _project: dict[str, Any] = Depends(_get_owned_project),
) -> dict[str, Any]:
    rows = list_project_documents(user["id"], project_id)
    return {
        "documents": [
            {
                "file_id": str(r["id"]),
                "filename": r["filename"],
                "size_bytes": r["size_bytes"],
                "chunk_count": r["chunk_count"],
                "index_status": r.get("index_status"),
                "last_error": r.get("last_error"),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@app.delete("/api/projects/{project_id}/documents/{file_id}", tags=["documents"], summary="문서 삭제")
def api_delete_document(
    project_id: str,
    file_id: str,
    request: Request,
    user: dict[str, str] = Depends(get_current_user),
    _project: dict[str, Any] = Depends(_get_owned_project),
) -> dict[str, str]:
    rate_limiter.check(f"delete:{user['id']}", settings.delete_rate_limit_per_minute, 60)
    deleted = delete_file(user["id"], file_id, project_id=project_id)
    if not deleted:
        raise ResourceNotFound("Document")
    record_audit(user["id"], "delete", "document", file_id, {"project_id": project_id})
    return {"status": "ok"}


@app.post("/api/projects/{project_id}/tables/{table_id}/append")
async def api_append_table(
    table_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: dict[str, str] = Depends(get_current_user),
    meta: dict[str, Any] = Depends(_get_owned_table),
) -> dict[str, Any]:
    """Append CSV data to an existing table."""
    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    allowed_types = (".csv", ".xlsx", ".xls")
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(allowed_types):
        raise UnsupportedFileType(filename)

    max_upload_size = settings.max_upload_size_mb * 1024 * 1024
    content = await file.read(max_upload_size + 1)
    if len(content) > max_upload_size:
        raise FileTooLarge(settings.max_upload_size_mb)
    return await asyncio.to_thread(append_imported_table, user["id"], str(meta["project_id"]), table_id, content, filename)


@app.get("/api/projects/{project_id}/tables/{table_id}/data")
def api_get_table_data(
    table_id: str,
    user: dict[str, str] = Depends(get_current_user),
    meta: dict[str, Any] = Depends(_get_owned_table),
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Get paginated data from a user table."""
    from .sql_executor import safe_select

    pg_table_name = get_user_table_name(user["id"], table_id)
    result = safe_select(pg_table_name, user["id"], limit=limit, offset=offset)
    return {
        "columns": meta["columns_schema"],
        "rows": jsonable_encoder(result["rows"], custom_encoder={Decimal: str}),
        "total_count": result["total_count"],
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# File endpoints (kept for S3 upload compatibility)
# ---------------------------------------------------------------------------

@app.post("/api/files/upload", tags=["files"], summary="파일 업로드")
async def upload_file(file: UploadFile = File(...), request: Request = None, user: dict[str, str] = Depends(get_current_user)) -> dict[str, Any]:
    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    allowed_types = (".csv", ".xlsx")
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(allowed_types):
        raise UnsupportedFileType(filename)

    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    max_upload_size = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_upload_size:
        raise HTTPException(
            status_code=400,
            detail=f"File is too large. Max size is {settings.max_upload_size_mb}MB",
        )

    file_id = str(uuid4())
    try:
        storage_key = storage.upload_bytes(content, filename)
        save_file(
            user_id=user["id"],
            file_id=file_id,
            filename=filename,
            storage_key=storage_key,
            size_bytes=len(content),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    return {"file_id": file_id, "filename": filename, "size": len(content), "storage_key": storage_key}


@app.get("/api/files", tags=["files"], summary="파일 목록 조회")
def get_files(
    user: dict[str, str] = Depends(get_current_user),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows, total = list_files(user_id=user["id"], limit=limit, offset=offset)
    files = [
        {
            "file_id": str(row["id"]),
            "filename": row["filename"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        for row in rows
    ]
    return {"files": files, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Conversation endpoints (Agent-powered)
# ---------------------------------------------------------------------------

@app.post("/api/conversations", tags=["conversations"], summary="대화 생성")
def create_conversation_endpoint(
    payload: CreateConversationRequest,
    user: dict[str, str] = Depends(get_current_user),
) -> dict[str, Any]:
    project = get_project(payload.project_id, user["id"])
    if not project:
        raise ResourceNotFound("Project")

    conversation_id = str(uuid4())
    title = payload.title or f"{project['name']} 분석"
    create_conversation(
        conversation_id=conversation_id,
        user_id=user["id"],
        file_id=None,
        title=title,
        project_id=payload.project_id,
        table_id=payload.table_id,
    )
    return {
        "conversation_id": conversation_id,
        "project_id": payload.project_id,
        "title": title,
    }


@app.get("/api/conversations", tags=["conversations"], summary="대화 목록 조회")
def get_conversations(
    file_id: str = Query(default=""),
    table_id: str = Query(default=""),
    project_id: str = Query(default=""),
    q: str = Query(default=""),
    limit: int = Query(default=30, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, str] = Depends(get_current_user),
) -> dict[str, Any]:
    rows, total = list_conversations(
        user_id=user["id"],
        file_id=file_id or None,
        project_id=project_id or None,
        table_id=table_id or None,
        search=q or None,
        limit=limit,
        offset=offset,
    )

    items = [
        {
            "conversation_id": str(row["id"]),
            "file_id": str(row["file_id"]) if row.get("file_id") else None,
            "project_id": str(row["project_id"]) if row.get("project_id") else None,
            "table_id": str(row["table_id"]) if row.get("table_id") else None,
            "title": row["title"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
        for row in rows
    ]
    return {"conversations": items, "total": total, "limit": limit, "offset": offset}


@app.delete("/api/conversations/{conversation_id}", tags=["conversations"], summary="대화 삭제")
def api_delete_conversation(
    conversation_id: str, request: Request, user: dict[str, str] = Depends(get_current_user)
) -> dict[str, str]:
    rate_limiter.check(f"delete:{user['id']}", settings.delete_rate_limit_per_minute, 60)
    if not delete_conversation(conversation_id, user["id"]):
        raise ResourceNotFound("Conversation")
    record_audit(user["id"], "delete", "conversation", conversation_id)
    return {"status": "ok"}


@app.get("/api/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    _conv: dict[str, Any] = Depends(_get_owned_conversation),
) -> dict[str, list[dict[str, Any]]]:
    rows = list_messages(conversation_id)
    messages = [
        {
            "message_id": str(row["id"]),
            "role": row["role"],
            "content": row["content"],
            "steps": row.get("steps"),
            "charts": row.get("charts"),
            "table_data": row.get("table_data"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        for row in rows
    ]
    return {"messages": messages}


async def _read_attached_files(files: list[UploadFile]) -> list[dict[str, Any]]:
    """Read and validate uploaded files for the agent."""
    ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
    max_size = settings.max_upload_size_mb * 1024 * 1024
    attached: list[dict[str, Any]] = []
    for f in files:
        filename = (f.filename or "").strip()
        if not filename:
            continue
        if not filename.lower().endswith(ALLOWED_EXTENSIONS):
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {filename}")
        content = await f.read()
        if len(content) > max_size:
            raise HTTPException(status_code=400, detail=f"파일이 너무 큽니다 ({filename}). 최대 {settings.max_upload_size_mb}MB")
        attached.append({"filename": filename, "content": content})
    return attached


@app.post("/api/conversations/{conversation_id}/messages", tags=["conversations"], summary="메시지 전송 (동기)")
async def send_message(
    conversation_id: str,
    request: Request,
    message: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    library_selections: str = Form(default="[]"),
    library_scope_confirmed: bool = Form(default=False),
    user: dict[str, str] = Depends(get_current_user),
    conv: dict[str, Any] = Depends(_get_owned_conversation),
) -> dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"query:{user['id']}:{client_ip}", settings.query_rate_limit_per_minute, 60)

    try:
        selections = json.loads(library_selections)
    except (ValueError, TypeError):
        raise HTTPException(422, "파일 선택 정보를 읽을 수 없습니다.")
    library_refs = await asyncio.to_thread(resolve_references, user["id"], str(conv.get("project_id") or ""), selections, confirmed=library_scope_confirmed)
    if library_refs and files:
        raise HTTPException(422, "새 파일을 먼저 보관함에 보관한 뒤 기존 파일과 함께 선택해주세요.")
    attached_files = await _read_attached_files(files)

    # Save user message
    user_msg_id = str(uuid4())
    save_message(
        message_id=user_msg_id,
        conversation_id=conversation_id,
        role="user",
        content=message,
        steps=[reference_step(library_refs)] if library_refs else None,
    )

    # Resolve project context
    project_id = str(conv["project_id"]) if conv.get("project_id") else None
    if not project_id:
        raise HTTPException(status_code=400, detail="No project associated with this conversation")

    project = get_project(project_id, user["id"])
    if not project:
        raise ResourceNotFound("Project")

    tables_info = list_table_metas(project_id, user["id"])

    # Build conversation history from DB
    prev_messages = list_messages(conversation_id)
    conversation_history = [
        {"role": msg["role"], "content": msg["content"], "steps": msg.get("steps")}
        for msg in prev_messages
        if msg["role"] in ("user", "assistant") and str(msg["id"]) != user_msg_id
    ]

    # Run agent (offload sync call to thread to avoid blocking event loop)
    agent_result = await asyncio.to_thread(
        run_agent,
        user_id=user["id"],
        project_id=project_id,
        project_name=project["name"],
        tables_info=tables_info,
        conversation_messages=conversation_history,
        question=message,
        attached_files=attached_files or None,
        **({"library_refs": library_refs} if library_refs else {}),
    )

    # Update row_count for mutated tables
    if agent_result.mutations_performed and agent_result.mutated_table_ids:
        from .sql_executor import get_table_row_count
        for tid in agent_result.mutated_table_ids:
            try:
                pg_name = get_user_table_name(user["id"], tid)
                new_count = get_table_row_count(pg_name, user["id"])
                update_table_meta(tid, user["id"], row_count=new_count)
            except Exception:
                logger.warning("Failed to update row_count for table %s", tid, exc_info=True)

    # Save assistant message
    assistant_msg_id = str(uuid4())
    result_dict = agent_result.to_dict()
    if library_refs: result_dict["steps"].insert(0, reference_step(library_refs))
    save_message(
        message_id=assistant_msg_id,
        conversation_id=conversation_id,
        role="assistant",
        content=agent_result.answer,
        steps=result_dict["steps"],
        charts=result_dict["charts"],
        table_data=result_dict["table_data"],
        usage=result_dict["usage"],
    )

    if len(conversation_history) <= 1:
        update_conversation_title(conversation_id, message[:50])
    touch_conversation(conversation_id)

    return {
        "message_id": assistant_msg_id,
        "role": "assistant",
        "content": agent_result.answer,
        "steps": result_dict["steps"],
        "charts": result_dict["charts"],
        "table_data": result_dict["table_data"],
        "usage": result_dict["usage"],
        "suggestions": result_dict["suggestions"],
        "mutations_performed": agent_result.mutations_performed,
        "schema_changed": agent_result.schema_changed,
    }


@app.post("/api/conversations/{conversation_id}/messages/stream", tags=["conversations"], summary="메시지 전송 (스트리밍)")
async def send_message_streaming(
    conversation_id: str,
    request: Request,
    message: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    library_selections: str = Form(default="[]"),
    library_scope_confirmed: bool = Form(default=False),
    user: dict[str, str] = Depends(get_current_user),
    conv: dict[str, Any] = Depends(_get_owned_conversation),
) -> StreamingResponse:
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"query:{user['id']}:{client_ip}", settings.query_rate_limit_per_minute, 60)

    try:
        selections = json.loads(library_selections)
    except (ValueError, TypeError):
        raise HTTPException(422, "파일 선택 정보를 읽을 수 없습니다.")
    library_refs = await asyncio.to_thread(resolve_references, user["id"], str(conv.get("project_id") or ""), selections, confirmed=library_scope_confirmed)
    if library_refs and files:
        raise HTTPException(422, "새 파일을 먼저 보관함에 보관한 뒤 기존 파일과 함께 선택해주세요.")
    attached_files = await _read_attached_files(files)

    # Resolve project context
    project_id = str(conv["project_id"]) if conv.get("project_id") else None
    if not project_id:
        raise HTTPException(status_code=400, detail="No project associated with this conversation")

    project = get_project(project_id, user["id"])
    if not project:
        raise ResourceNotFound("Project")

    tables_info = list_table_metas(project_id, user["id"])

    user_msg_id = str(uuid4())
    save_message(
        message_id=user_msg_id,
        conversation_id=conversation_id,
        role="user",
        content=message,
        steps=[reference_step(library_refs)] if library_refs else None,
    )

    prev_messages = list_messages(conversation_id)
    conversation_history = [
        {"role": msg["role"], "content": msg["content"], "steps": msg.get("steps")}
        for msg in prev_messages
        if msg["role"] in ("user", "assistant") and str(msg["id"]) != user_msg_id
    ]

    async def event_generator():
        """Forward agent events, injecting heartbeats during quiet periods.

        Two problems are handled here. First, any exception raised after the
        response headers are sent must still reach the client as an error
        frame — previously it killed the stream mid-flight, the client fell
        out of its read loop with no error set, the spinner simply stopped,
        and the already-persisted user message was left without a reply.

        Second, a long-running tool produces no output, and the client aborts
        after 120s while the server allows up to 25 iterations. Heartbeats
        keep an in-progress turn distinguishable from a dead connection.
        """
        queue: asyncio.Queue = asyncio.Queue()
        finished = object()

        async def produce():
            try:
                async for event in _stream_agent_events():
                    await queue.put(event)
            except Exception:
                logger.error("Streaming turn failed", exc_info=True)
                failure = {
                    "type": "error",
                    "data": {"message": "응답 생성 중 오류가 발생했습니다. 다시 시도해주세요."},
                }
                await queue.put(f"data: {json.dumps(failure, ensure_ascii=False)}\n\n")
            finally:
                await queue.put(finished)

        producer = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                    continue
                if item is finished:
                    break
                yield item
        finally:
            producer.cancel()

    async def _stream_agent_events():
        steps = []
        charts = []
        table_data = []
        answer = ""
        mutations_performed = False
        schema_changed = False
        mutated_table_ids: list[str] = []
        usage: dict[str, Any] = {}

        async for step in run_agent_streaming(
            user_id=user["id"],
            project_id=project_id,
            project_name=project["name"],
            tables_info=tables_info,
            conversation_messages=conversation_history,
            question=message,
            attached_files=attached_files or None,
            **({"library_refs": library_refs} if library_refs else {}),
        ):
            if step.type == "meta":
                # Mutation flags plus this turn's LLM usage.
                try:
                    meta_data = json.loads(step.content)
                    if meta_data.get("mutations_performed"):
                        mutations_performed = True
                    if meta_data.get("schema_changed"):
                        schema_changed = True
                    if meta_data.get("mutated_table_ids"):
                        mutated_table_ids = meta_data["mutated_table_ids"]
                    if meta_data.get("usage"):
                        usage = meta_data["usage"]
                except Exception:
                    logger.warning("Failed to parse agent meta frame", exc_info=True)
                continue

            steps.append(step)

            if step.type == "tool_call":
                if step.tool_name in ("generate_chart", "preview_metric") and "chart_type" in step.tool_output:
                    charts.append(step.tool_output)
                if step.tool_name in ("query_data", "cross_query") and "data" in step.tool_output:
                    table_data = step.tool_output["data"]
                # Track mutations
                if step.tool_name in ("insert_rows", "update_rows", "delete_rows", "import_file"):
                    mutations_performed = True
                if step.tool_name in ("create_table", "alter_table"):
                    schema_changed = True
                event = {
                    "type": "step",
                    "data": {
                        "tool_name": step.tool_name,
                        "tool_input": step.tool_input,
                        "tool_output": step.tool_output,
                    },
                }
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            elif step.type == "token":
                # Incremental answer text. This is what makes time-to-first-
                # byte independent of total model latency.
                event = {"type": "token", "data": {"content": step.content}}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            elif step.type == "error":
                event = {"type": "error", "data": {"message": step.content}}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                return

            elif step.type == "answer":
                answer = step.content
                event = {"type": "answer", "data": {"content": answer}}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # Update row_count for mutated tables
        if mutations_performed and mutated_table_ids:
            from .sql_executor import get_table_row_count
            for tid in mutated_table_ids:
                try:
                    pg_name = get_user_table_name(user["id"], tid)
                    new_count = get_table_row_count(pg_name, user["id"])
                    update_table_meta(tid, user["id"], row_count=new_count)
                except Exception:
                    logger.warning("Failed to update row_count for table %s (streaming)", tid, exc_info=True)

        clean_answer, suggestions = _parse_suggestions(answer)
        assistant_msg_id = str(uuid4())
        result = AgentResult(
            answer=clean_answer, steps=steps, charts=charts,
            table_data=table_data, suggestions=suggestions,
            mutations_performed=mutations_performed,
            schema_changed=schema_changed,
            total_tokens=usage.get("total_tokens", 0),
            usage=usage,
        )
        result_dict = result.to_dict()
        if library_refs: result_dict["steps"].insert(0, reference_step(library_refs))
        save_message(
            message_id=assistant_msg_id,
            conversation_id=conversation_id,
            role="assistant",
            content=clean_answer,
            steps=result_dict["steps"],
            charts=result_dict["charts"],
            table_data=result_dict["table_data"],
            usage=usage,
        )

        if len(conversation_history) <= 1:
            update_conversation_title(conversation_id, message[:50])
        touch_conversation(conversation_id)

        done_event = {
            "type": "done",
            "data": {
                "message_id": assistant_msg_id,
                "content": clean_answer,
                "steps": result_dict["steps"],
                "charts": result_dict["charts"],
                "table_data": result_dict["table_data"],
                "suggestions": suggestions,
                "mutations_performed": mutations_performed,
                "schema_changed": schema_changed,
                "usage": usage,
            },
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Dashboard Widgets
# ---------------------------------------------------------------------------


@app.get("/api/dashboard/widgets", tags=["dashboard"], summary="위젯 목록 조회")
def api_list_widgets(
    project_id: str | None = Query(None),
    file_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if project_id and not get_project(project_id, user["id"]):
        raise ResourceNotFound("Project")
    widgets = list_widgets(user_id=user["id"], project_id=project_id, file_id=file_id)
    return {
        "widgets": [
            {
                "id": str(w["id"]),
                "widget_type": w["widget_type"],
                "title": w["title"],
                "widget_data": w["widget_data"],
                "refresh_interval_seconds": w.get("refresh_interval_seconds", 0),
                "next_refresh_at": str(w["next_refresh_at"]) if w.get("next_refresh_at") else None,
                "refresh_failures": w.get("refresh_failures", 0),
                "save_key": w.get("save_key"),
                "layout": w["layout"],
                "created_at": str(w["created_at"]) if w.get("created_at") else None,
            }
            for w in widgets
        ]
    }


@app.post("/api/dashboard/widgets", tags=["dashboard"], summary="위젯 생성")
def api_create_widget(
    req: CreateWidgetRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if req.project_id and not get_project(req.project_id, user["id"]):
        raise ResourceNotFound("Project")
    widget_id = str(uuid4())
    row = create_widget(
        widget_id=widget_id,
        user_id=user["id"],
        widget_type=req.widget_type,
        title=req.title,
        widget_data=req.widget_data,
        layout=req.layout,
        project_id=req.project_id,
        file_id=req.file_id,
        **({"save_key": req.save_key} if req.save_key else {}),
    )
    record_audit(user["id"], "create", "widget", str(row["id"]), {"widget_type": req.widget_type, "title": req.title})
    return {
        "id": str(row["id"]),
        "widget_type": row["widget_type"],
        "title": row["title"],
        "widget_data": row["widget_data"],
        "layout": row["layout"],
    }


@app.put("/api/dashboard/widgets/layout")
def api_update_layout(
    req: UpdateLayoutRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    update_widgets_layout(user_id=user["id"], layouts=req.layouts)
    return {"status": "ok"}


@app.delete("/api/dashboard/widgets/{widget_id}")
def api_delete_widget(
    widget_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    rate_limiter.check(f"delete:{user['id']}", settings.delete_rate_limit_per_minute, 60)
    deleted = delete_widget(widget_id=widget_id, user_id=user["id"])
    if not deleted:
        raise ResourceNotFound("Widget")
    record_audit(user["id"], "delete", "widget", widget_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

@app.get("/api/audit-logs", tags=["auth"], summary="감사 로그 조회")
def api_audit_logs(
    resource_type: str = Query(default=""),
    resource_id: str = Query(default=""),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    logs = list_audit_logs(
        user_id=user["id"],
        resource_type=resource_type or None,
        resource_id=resource_id or None,
        limit=limit,
        offset=offset,
    )
    return {
        "logs": [
            {
                "id": row["id"],
                "action": row["action"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "detail": row.get("detail"),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            }
            for row in logs
        ],
        "limit": limit,
        "offset": offset,
    }
