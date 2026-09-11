"""HTTP boundary for source imports. Parsing/commits run off the event loop."""
import asyncio
import logging
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from . import ledger_imports as service
from . import attribute_restoration as restoration
from .auth import get_current_user
from .config import settings
from .rate_limiter import rate_limiter
from .upload_sources import read_source
from .storage import StorageService
from . import import_mapping
from .payment_imports import PaymentImportMapping
from .exceptions import AppException
from pydantic import ValidationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}", tags=["imports"])
storage = StorageService()


@router.post('/import-mapping/inspect')
async def inspect_mapping_file(project_id: UUID, file: UploadFile | None = File(default=None), stored_file_id: UUID | None = Form(default=None), user=Depends(get_current_user)):
    rate_limiter.check(f'mapping:{user["id"]}', settings.upload_rate_limit_per_minute, 60)
    filename, content = await read_source(user["id"], str(project_id), file, stored_file_id, storage)
    return await asyncio.to_thread(import_mapping.inspect_file, user['id'], str(project_id), content, filename)


@router.post('/import-mapping/validate')
async def validate_mapping_file(project_id: UUID, file: UploadFile | None = File(default=None), stored_file_id: UUID | None = Form(default=None), mapping: str = Form(..., max_length=10000), user=Depends(get_current_user)):
    rate_limiter.check(f'mapping:{user["id"]}', settings.upload_rate_limit_per_minute, 60)
    try:
        parsed = PaymentImportMapping.model_validate_json(mapping)
    except ValidationError:
        raise AppException(422, 'invalid_mapping', '필수 컬럼과 금액 해석을 확인해주세요.') from None
    filename, content = await read_source(user["id"], str(project_id), file, stored_file_id, storage)
    return await asyncio.to_thread(import_mapping.validate_mapping, user['id'], str(project_id), content, filename, parsed)


@router.post('/ledger-sources/{source_id}/attribute-restorations/preview')
async def preview_attributes(project_id: UUID, source_id: UUID, payload: restoration.RestoreAttributesRequest, user=Depends(get_current_user)):
    rate_limiter.check(f"attribute-preview:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    return await asyncio.to_thread(restoration.preview_restoration, user['id'], str(project_id), str(source_id), payload, storage)


@router.post('/ledger-sources/{source_id}/attribute-restorations/{restoration_id}/apply')
async def apply_attributes(project_id: UUID, source_id: UUID, restoration_id: UUID, user=Depends(get_current_user)):
    rate_limiter.check(f"attribute-apply:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    result = await asyncio.to_thread(restoration.apply_restoration, user['id'], str(project_id), str(source_id), str(restoration_id), storage)
    return {**result, 'index_status': 'queued'}


@router.get('/ledger-sources/{source_id}/attribute-restorations')
def attribute_history(project_id: UUID, source_id: UUID, user=Depends(get_current_user)):
    return {'restorations': restoration.list_restorations(user['id'], str(project_id), str(source_id))}


@router.get('/ledger-sources/{source_id}/attribute-restorations/{restoration_id}/changes')
def attribute_changes(project_id: UUID, source_id: UUID, restoration_id: UUID, limit: int = Query(50, ge=1, le=100),
                      offset: int = Query(0, ge=0), user=Depends(get_current_user)):
    return restoration.list_changes(user['id'], str(project_id), str(source_id), str(restoration_id), limit, offset)


@router.post("/ledger-sources")
async def create_source(project_id: UUID, payload: service.CreateSourceRequest, user=Depends(get_current_user)):
    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    result = await asyncio.to_thread(service.create_source, user["id"], str(project_id), payload)
    return result


@router.get("/ledger-sources")
def list_sources(project_id: UUID, user=Depends(get_current_user)):
    return {"sources": service.list_sources(user["id"], str(project_id))}


@router.post("/ledger-sources/preview-adoption")
async def preview_adoption(project_id: UUID, payload: service.CreateSourceRequest, user=Depends(get_current_user)):
    return await asyncio.to_thread(service.preview_adoption, user["id"], str(project_id), payload)


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_idless: bool = False


@router.post("/ledger-sources/{source_id}/baseline")
async def baseline(project_id: UUID, source_id: UUID, payload: BaselineRequest, user=Depends(get_current_user)):
    return await asyncio.to_thread(service.baseline_source, user["id"], str(project_id), str(source_id), payload.accept_idless)


@router.post("/imports")
async def upload(project_id: UUID, source_id: UUID = Form(...), request_key: UUID = Form(...),
                 file: UploadFile | None = File(default=None), stored_file_id: UUID | None = Form(default=None), user=Depends(get_current_user)):
    rate_limiter.check(f"upload:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    filename, content = await read_source(user["id"], str(project_id), file, stored_file_id, storage)
    return await asyncio.to_thread(service.upload_batch, user["id"], str(project_id), str(source_id),
                                   str(request_key), content, filename, storage)


@router.get("/imports")
def history(project_id: UUID, source_id: UUID, limit: int = Query(20, ge=1, le=100),
            offset: int = Query(0, ge=0), user=Depends(get_current_user)):
    return service.list_batches(user["id"], str(project_id), str(source_id), limit, offset)


@router.get("/imports/{batch_id}")
def get_batch(project_id: UUID, batch_id: UUID, user=Depends(get_current_user)):
    return service.get_batch(user["id"], str(project_id), str(batch_id))


@router.post("/imports/{batch_id}/preview")
async def preview(project_id: UUID, batch_id: UUID, user=Depends(get_current_user)):
    rate_limiter.check(f"import-preview:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    return await asyncio.to_thread(service.preview_batch, user["id"], str(project_id), str(batch_id), storage)


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_token: UUID


class RowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_number: int = Field(ge=1)
    decision: Literal["include", "exclude"]


class DecisionsRequest(CommitRequest):
    decisions: list[RowDecision] = Field(min_length=1, max_length=1000)


@router.get("/imports/{batch_id}/rows")
def rows(project_id: UUID, batch_id: UUID, classification: Literal["new", "duplicate", "candidate", "conflict"] | None = None,
         limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(get_current_user)):
    return service.list_rows(user["id"], str(project_id), str(batch_id), classification, limit, offset)


@router.post("/imports/{batch_id}/decisions")
def decisions(project_id: UUID, batch_id: UUID, payload: DecisionsRequest, user=Depends(get_current_user)):
    return service.decide_rows(user["id"], str(project_id), str(batch_id), str(payload.preview_token), payload.decisions)


@router.post("/imports/{batch_id}/commit")
async def commit(project_id: UUID, batch_id: UUID, payload: CommitRequest, user=Depends(get_current_user)):
    result = await asyncio.to_thread(service.commit_batch, user["id"], str(project_id), str(batch_id), str(payload.preview_token), storage)
    return result


async def run_import_cleanup(stop: asyncio.Event):
    while not stop.is_set():
        try:
            await asyncio.to_thread(service.expire_pending_batches, storage)
            if settings.storage_backend == "supabase":
                from .direct_uploads import cleanup_expired_uploads
                await asyncio.to_thread(cleanup_expired_uploads)
        except Exception:
            logger.exception("Pending import cleanup failed; retrying next tick")
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            pass
