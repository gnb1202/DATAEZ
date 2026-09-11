"""Resolve an upload or an owned, same-store stored original at the HTTP boundary."""
import asyncio
import hashlib

from fastapi import HTTPException, UploadFile

from . import db, file_library
from .config import settings
from .exceptions import FileTooLarge, UnsupportedFileType


def stored_source(user_id, project_id, file_id, storage, allowed):
    with db._connect() as conn:
        file_library.own_project(conn, user_id, project_id)
    row = file_library.get_record(user_id, file_id)
    scopes = {str(b['project_id']) for b in row['bindings']}
    if row['assigned_project_id']:
        scopes.add(str(row['assigned_project_id']))
    if scopes and scopes != {str(project_id)}:
        raise HTTPException(409, '현재 가게의 원본을 선택해주세요. 다른 가게 자료는 보관함의 분석 범위 선택을 이용해주세요.')
    filename = row['filename']
    if not filename.lower().endswith(allowed):
        raise UnsupportedFileType(filename)
    maximum = settings.max_upload_size_mb * 1024 * 1024
    if not row['size_bytes'] or row['size_bytes'] > maximum:
        raise FileTooLarge(settings.max_upload_size_mb)
    content = (storage._supabase.get_limited(row['storage_key'], row['size_bytes'])
               if settings.storage_backend == 'supabase' else storage.read_bytes(row['storage_key']))
    if (len(content) != row['size_bytes'] or
            (row['content_hash'] and hashlib.sha256(content).hexdigest() != row['content_hash'])):
        raise HTTPException(409, '원본 파일 검증에 실패했습니다. 다시 업로드해주세요.')
    return filename, content


async def read_source(user_id, project_id, file, stored_file_id, storage,
                      allowed=('.csv', '.xlsx', '.xls')):
    if (file is None) == (stored_file_id is None):
        raise HTTPException(422, '파일 또는 보관 파일 ID 중 하나를 전달해주세요.')
    if stored_file_id is not None:
        return await asyncio.to_thread(stored_source, user_id, project_id, str(stored_file_id), storage, allowed)
    filename = (file.filename or '').strip()
    if not filename.lower().endswith(allowed):
        raise UnsupportedFileType(filename)
    maximum = settings.max_upload_size_mb * 1024 * 1024
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        raise FileTooLarge(settings.max_upload_size_mb)
    if not content:
        raise HTTPException(422, '비어 있는 파일은 업로드할 수 없습니다.')
    return filename, content
