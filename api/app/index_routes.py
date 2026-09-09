"""Owner/store-scoped search health and bounded manual retry."""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from .auth import get_current_user
from . import index_jobs
from .rate_limiter import rate_limiter
from .config import settings

router = APIRouter(prefix='/api/projects/{project_id}/search-index', tags=['search'])


@router.get('')
def status(project_id: UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(get_current_user)):
    return index_jobs.list_jobs(user['id'], str(project_id), limit, offset)


@router.post('/{job_id}/retry')
def retry(project_id: UUID, job_id: UUID, user=Depends(get_current_user)):
    rate_limiter.check(f"index-retry:{user['id']}", settings.upload_rate_limit_per_minute, 60)
    return index_jobs.retry_job(user['id'], str(project_id), str(job_id))
