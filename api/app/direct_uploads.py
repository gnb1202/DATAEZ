"""Signed URLs grant one object write; only verified completion creates a file."""
import hashlib
from pathlib import PurePath
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from . import db, file_library as library
from .auth import get_current_user
from .config import settings
from .storage import StorageService

router = APIRouter(prefix="/api/uploads", tags=["file-library"])


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    project_id: UUID | None = None
    filename: str = Field(min_length=1, max_length=220)
    size_bytes: int = Field(gt=0, le=20 * 1024 * 1024, strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def require_storage():
    if settings.storage_backend != "supabase":
        raise HTTPException(409, "이 환경에서는 일반 파일 업로드를 사용해주세요.")
    return StorageService()._supabase


@router.get("/capabilities")
def capabilities(user=Depends(get_current_user)):
    return {"direct_upload": settings.storage_backend == "supabase",
            "max_size_bytes": min(settings.max_upload_size_mb, 20) * 1024 * 1024}


@router.post("", status_code=201)
def start(body: UploadRequest, response: Response, user=Depends(get_current_user)):
    storage = require_storage()
    response.headers["Cache-Control"] = "private, no-store"
    filename = PurePath(body.filename.replace("\\", "/")).name
    if not filename.lower().endswith(library.TABULAR + library.DOCUMENTS) or any(ord(c) < 32 for c in filename):
        raise HTTPException(422, "CSV·XLSX·XLS·PDF·MD·TXT 파일을 선택해주세요.")
    if body.size_bytes > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(422, "업로드 가능한 파일 크기를 초과했습니다.")
    project_id = str(body.project_id) if body.project_id else None
    with db._connect() as conn:
        # Shared across instances. Limits outstanding reservations, including
        # expired objects awaiting cleanup, so abandoned uploads cannot pile up.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"uploads:{user['id']}",))
        if project_id:
            library.own_project(conn, user['id'], project_id)
        row = conn.execute("SELECT * FROM upload_sessions WHERE user_id=%s AND request_id=%s", (user['id'], body.request_id)).fetchone()
        if row:
            if (str(row['project_id']) if row['project_id'] else None, row['filename'], row['size_bytes'], row['content_hash']) != (project_id, filename, body.size_bytes, body.content_hash):
                raise HTTPException(409, "같은 업로드 요청 ID의 파일 정보를 변경할 수 없습니다.")
            # Do not reissue a token: that would extend its expiry past cleanup.
            return {"session_id": str(row['id']), "expires_at": row['expires_at'], "upload_url": None,
                    "file_id": str(row['file_id']) if row['file_id'] else None}
        pending = conn.execute("SELECT count(*) AS n FROM upload_sessions WHERE user_id=%s AND file_id IS NULL", (user['id'],)).fetchone()['n']
        if pending >= 10:
            raise HTTPException(429, "완료되지 않은 업로드가 많습니다. 기존 업로드를 완료하거나 만료 정리를 기다려주세요.")
        session_id = uuid4()
        key = f"{settings.s3_prefix}/direct/{session_id.hex}{PurePath(filename).suffix.lower()}"
        url = storage.create_upload_url(key)
        # Expiry starts after signing; cleanup waits an additional 10 minutes.
        row = conn.execute("""INSERT INTO upload_sessions(id,user_id,project_id,request_id,filename,storage_key,size_bytes,content_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING expires_at""",
            (session_id, user['id'], project_id, body.request_id, filename, key, body.size_bytes, body.content_hash)).fetchone()
    return {"session_id": str(session_id), "expires_at": row['expires_at'], "upload_url": url, "method": "PUT"}


@router.post("/{session_id}/complete")
def complete(session_id: UUID, user=Depends(get_current_user)):
    storage = require_storage()
    with db._connect() as conn:
        conn.execute("SET LOCAL lock_timeout = '10s'")
        row = conn.execute("SELECT * FROM upload_sessions WHERE id=%s AND user_id=%s FOR UPDATE", (session_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, "업로드 요청을 찾을 수 없습니다.")
        if row['project_id']:
            library.own_project(conn, user['id'], str(row['project_id']))
        replayed = bool(row['file_id'])
        if replayed:
            file_id = str(row['file_id'])
        else:
            if conn.execute("SELECT clock_timestamp() >= %s AS expired", (row['expires_at'],)).fetchone()['expired']:
                raise HTTPException(410, "업로드 요청이 만료되었습니다. 파일을 다시 선택해주세요.")
            try:
                content = storage.get_limited(row['storage_key'], row['size_bytes'])
            except FileNotFoundError:
                raise HTTPException(409, "파일 전송이 완료되지 않았습니다. 전송 후 다시 확인해주세요.")
            except ValueError:
                raise HTTPException(422, "전송된 파일의 크기가 일치하지 않습니다.")
            if len(content) != row['size_bytes'] or hashlib.sha256(content).hexdigest() != row['content_hash']:
                raise HTTPException(422, "전송된 파일의 크기 또는 해시가 일치하지 않습니다.")
            project_id = str(row['project_id']) if row['project_id'] else None
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f"library:{user['id']}:{project_id}:{row['content_hash']}",))
            found = conn.execute('SELECT file_id FROM library_entries WHERE user_id=%s AND project_id IS NOT DISTINCT FROM %s::uuid AND content_hash=%s AND deleted_at IS NULL', (user['id'], project_id, row['content_hash'])).fetchone()
            replayed = bool(found)
            file_id = str(found['file_id']) if found else str(uuid4())
            if not found:
                conn.execute('INSERT INTO files(id,user_id,filename,storage_key,size_bytes) VALUES(%s,%s,%s,%s,%s)', (file_id,user['id'],row['filename'],row['storage_key'],row['size_bytes']))
                conn.execute('INSERT INTO library_entries(file_id,user_id,project_id,content_hash) VALUES(%s,%s,%s,%s)', (file_id,user['id'],project_id,row['content_hash']))
            conn.execute('UPDATE upload_sessions SET file_id=%s WHERE id=%s', (file_id, session_id))
    # Release the transaction before a second pool connection (pool max is two).
    return {**library.public(library.get_record(user['id'], file_id)), 'replayed': replayed}


def cleanup_expired_uploads(limit=2):
    """Bounded janitor; never delete a referenced original or a live signed target."""
    storage = require_storage()
    with db._connect() as conn:
        rows = conn.execute("""SELECT id,storage_key FROM upload_sessions
            WHERE expires_at < clock_timestamp() - interval '10 minutes'
            ORDER BY expires_at LIMIT %s FOR UPDATE SKIP LOCKED""", (min(max(limit, 1), 2),)).fetchall()
        for row in rows:
            if not conn.execute('SELECT id FROM files WHERE storage_key=%s', (row['storage_key'],)).fetchone():
                storage.delete(row['storage_key'])
            conn.execute('DELETE FROM upload_sessions WHERE id=%s', (row['id'],))
    return len(rows)
