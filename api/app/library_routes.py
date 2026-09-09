"""Authenticated catalog API. Storage credentials/paths stay on the server."""
import asyncio
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, HTTPException, Response
from pydantic import BaseModel
from .auth import get_current_user
from .config import settings
from . import file_library as library
from .storage import StorageService
from .rate_limiter import rate_limiter

router = APIRouter(prefix='/api/library/files', tags=['file-library'])


@router.get('')
def files(project_id: UUID | None = None, search: str = Query('',max_length=160), kind: str = '',
          offset: int = Query(0,ge=0), limit: int = Query(30,ge=1,le=100), user=Depends(get_current_user)):
    return library.list_library(user['id'],project_id=str(project_id) if project_id else None,search=search,kind=kind,offset=offset,limit=limit)


@router.post('',status_code=201)
async def upload(file: UploadFile = File(...), project_id: str = Form(''), user=Depends(get_current_user)):
    rate_limiter.check(f"upload:{user['id']}",settings.upload_rate_limit_per_minute,60)
    content = await file.read(settings.max_upload_size_mb*1024*1024+1)
    return await asyncio.to_thread(library.store_file,user['id'],project_id,file.filename or '',content)


class ResolveRequest(BaseModel):
    project_id: UUID
    selections: list[dict]
    confirmed: bool = False


@router.post('/resolve')
def resolve(body: ResolveRequest,user=Depends(get_current_user)):
    with library.db._connect() as conn:
        library.own_project(conn,user['id'],str(body.project_id))
    return {'files':library.resolve_references(user['id'],str(body.project_id),body.selections,confirmed=body.confirmed)}


@router.get('/{file_id}')
def detail(file_id: UUID,user=Depends(get_current_user)):
    return library.public(library.get_record(user['id'],str(file_id)))


@router.post('/sample-workspace')
def sample_workspace(user=Depends(get_current_user)):
    from .sample_workspace import prepare_sample
    rate_limiter.check(f"sample:{user['id']}",10,60)
    return prepare_sample(user['id'])


@router.get('/{file_id}/preview')
def preview(file_id: UUID,user=Depends(get_current_user)):
    try:
        return library.preview_file(user['id'],str(file_id))
    except FileNotFoundError:
        raise HTTPException(410,'원본을 찾을 수 없습니다. 파일 상태를 확인해주세요.')


@router.get('/{file_id}/download')
def download(file_id: UUID,user=Depends(get_current_user)):
    row = library.get_record(user['id'],str(file_id))
    try:
        content = StorageService().read_bytes(row['storage_key'])
    except FileNotFoundError:
        raise HTTPException(410,'원본을 찾을 수 없습니다. 파일 상태를 확인해주세요.')
    return Response(content,media_type='application/octet-stream',headers={
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['filename'],safe=''),
        'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


class PrepareRequest(BaseModel):
    project_id: UUID


@router.post('/{file_id}/prepare')
def prepare(file_id: UUID,body: PrepareRequest,user=Depends(get_current_user)):
    try:
        return library.prepare_file(user['id'],str(file_id),str(body.project_id))
    except FileNotFoundError:
        raise HTTPException(410,'원본을 찾을 수 없습니다. 파일 상태를 확인해주세요.')


@router.delete('/{file_id}')
def remove(file_id: UUID,user=Depends(get_current_user)):
    return library.remove_file(user['id'],str(file_id))
