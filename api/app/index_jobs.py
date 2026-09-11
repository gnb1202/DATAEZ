"""Persistent indexing with short claims, expiring leases and fenced writes."""
import asyncio
import hashlib
import logging
from uuid import uuid4

from . import db
from .config import settings
from .exceptions import AppException, ResourceNotFound

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 600
RETRY_SECONDS = (15, 60, 300, 900)
MAX_DOCUMENT_CHUNKS = 192


def ensure_index_jobs():
    from .index_schema import DDL
    with db._connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('dataez-index-migration'))")
        conn.execute(DDL)


def adopt_indexed_documents():
    """Only existing chunk scope is trustworthy; orphan uploads are not guessed."""
    with db._connect() as conn:
        conn.execute("""INSERT INTO search_index_jobs(user_id,project_id,file_id,status,completed_generation,last_success_at)
            SELECT f.user_id,d.project_id,f.id,'succeeded',1,max(d.created_at) AT TIME ZONE 'UTC'
            FROM files f JOIN document_chunks d ON d.file_id=f.id AND d.user_id=f.user_id
            LEFT JOIN projects p ON p.id=d.project_id AND p.user_id=f.user_id AND p.deleted_at IS NULL
            WHERE (d.project_id IS NULL OR p.id IS NOT NULL)
              AND NOT EXISTS(SELECT 1 FROM document_chunks x WHERE x.file_id=f.id
                AND (x.user_id<>f.user_id OR x.project_id IS DISTINCT FROM d.project_id))
            GROUP BY f.id,d.project_id ON CONFLICT(file_id) DO NOTHING""")


def register_document(user_id, project_id, filename, content, storage, *, source_file_id=None):
    """Original object first, then file registration + job in one transaction."""
    if source_file_id:
        from .file_library import prepare_file
        record = prepare_file(user_id, source_file_id, project_id, storage)
        binding = next(b for b in record['bindings'] if b['kind'] == 'document' and b['project_id'] == project_id)
        return {'file_id': source_file_id, 'filename': filename, 'size_bytes': len(content),
                'chunks': 0, 'index_status': binding['index_status'], 'index_job_id': binding['job_id']}
    file_id = str(uuid4())
    # Fixed server-generated staging keys avoid filename/path interpretation.
    key = storage.staged_key(file_id)
    storage.write_staged(key, content)
    with db._connect() as conn:
        project = conn.execute('SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL FOR SHARE',
                               (project_id, user_id)).fetchone()
        if not project:
            raise ResourceNotFound('가게')
        conn.execute('INSERT INTO files(id,user_id,filename,storage_key,size_bytes) VALUES(%s,%s,%s,%s,%s)',
                     (file_id, user_id, filename, key, len(content)))
        job = conn.execute('''INSERT INTO search_index_jobs(user_id,project_id,file_id,file_sha256)
            VALUES(%s,%s,%s,%s) RETURNING id''', (user_id, project_id, file_id, hashlib.sha256(content).hexdigest())).fetchone()
    return {'file_id': file_id, 'filename': filename, 'size_bytes': len(content), 'chunks': 0,
            'index_status': 'pending', 'index_job_id': str(job['id'])}


def claim_one():
    if not settings.rag_enabled:
        return None
    with db._connect() as conn:
        job = conn.execute("""SELECT * FROM search_index_jobs
            WHERE status IN ('pending','retry','processing') AND next_attempt_at<=clock_timestamp()
              AND (status<>'processing' OR lease_until<=clock_timestamp())
            ORDER BY next_attempt_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
        if not job:
            return None
        if job['attempts'] >= MAX_ATTEMPTS:
            conn.execute("""UPDATE search_index_jobs SET status='failed',lease_token=NULL,lease_until=NULL,
                last_error_code='worker_interrupted',last_error='검색 갱신 작업이 반복 중단되었습니다. 다시 시도해 주세요.',
                updated_at=clock_timestamp() WHERE id=%s""", (job['id'],))
            return {'exhausted': True}
        return dict(conn.execute("""UPDATE search_index_jobs SET status='processing',attempts=attempts+1,
            lease_token=%s,lease_until=clock_timestamp()+(%s * interval '1 second'),
            next_attempt_at=clock_timestamp()+(%s * interval '1 second'),updated_at=clock_timestamp()
            WHERE id=%s RETURNING *""", (str(uuid4()), LEASE_SECONDS, LEASE_SECONDS, job['id'])).fetchone())


def fence(cur, job):
    """Call only AFTER source metadata locks; hold through index + completion."""
    cur.execute("""SELECT id FROM search_index_jobs WHERE id=%s AND generation=%s AND lease_token=%s
        AND status='processing' AND lease_until>clock_timestamp() FOR UPDATE""",
        (job['id'], job['generation'], job['lease_token']))
    return bool(cur.fetchone())


def succeeded(cur, job):
    cur.execute("""UPDATE search_index_jobs SET status='succeeded',completed_generation=generation,
        lease_token=NULL,lease_until=NULL,last_error_code=NULL,last_error=NULL,
        last_success_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=%s""", (job['id'],))


def _finish_failure(job, code, message, *, permanent=False, cancelled=False):
    with db._connect() as conn, conn.cursor() as cur:
        if not fence(cur, job):
            return
        status = 'cancelled' if cancelled else ('failed' if permanent or job['attempts'] >= MAX_ATTEMPTS else 'retry')
        if status == 'failed' and code == 'index_unavailable':
            message = '검색 갱신을 완료하지 못했습니다. 다시 시도해 주세요.'
        delay = RETRY_SECONDS[min(job['attempts'] - 1, len(RETRY_SECONDS) - 1)]
        cur.execute("""UPDATE search_index_jobs SET status=%s,lease_token=NULL,lease_until=NULL,
            next_attempt_at=clock_timestamp()+(%s * interval '1 second'),last_error_code=%s,last_error=%s,
            updated_at=clock_timestamp() WHERE id=%s""", (status, delay, code, message, job['id']))


def _document(job, storage):
    from .document_processor import extract_text, chunk_text
    from .rag import chunk_and_embed_document
    with db._connect() as conn:
        file = conn.execute('SELECT * FROM files WHERE id=%s AND user_id=%s', (job['file_id'], job['user_id'])).fetchone()
        if not file:
            raise ResourceNotFound('문서')
        if job['project_id'] is not None and not conn.execute(
            'SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL',
            (job['project_id'], job['user_id'])).fetchone():
            raise ResourceNotFound('가게')
    if file['size_bytes'] > settings.max_upload_size_mb * 1024 * 1024:
        raise AppException(422, 'document_too_large', '문서가 검색 처리 크기 제한을 넘었습니다. 나누어 올려 주세요.')
    try:
        content = storage.read_bytes(file['storage_key'])
    except FileNotFoundError:
        raise AppException(422, 'document_missing', '저장된 원본을 찾을 수 없습니다. 원본 문서를 다시 올려 주세요.') from None
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != file['size_bytes'] or (job['file_sha256'] and digest != job['file_sha256']):
        raise AppException(422, 'document_changed', '저장된 원본이 업로드 기록과 다릅니다. 원본 문서를 다시 올려 주세요.')
    try:
        chunks = chunk_text(extract_text(content, file['filename']))
    except Exception:
        raise AppException(422, 'document_unreadable', '문서의 텍스트를 읽을 수 없습니다. 파일 형식을 확인해 다시 올려 주세요.') from None
    if not chunks:
        raise AppException(422, 'document_empty', '검색할 텍스트가 없습니다. 스캔 문서는 텍스트를 추출한 뒤 다시 올려 주세요.')
    if len(chunks) > MAX_DOCUMENT_CHUNKS:
        raise AppException(422, 'document_too_large', '문서의 텍스트가 검색 처리 한도를 넘었습니다. 나누어 올려 주세요.')
    return chunk_and_embed_document(str(job['file_id']), str(job['user_id']),
        str(job['project_id']) if job['project_id'] else None, chunks,
        [{'filename': file['filename'], 'chunk_index': i} for i in range(len(chunks))],
        job=job, file_snapshot=dict(file), file_digest=digest)


def process_one(storage=None):
    from .rag import index_schema
    from .storage import StorageService
    job = claim_one()
    if not job:
        return False
    if job.get('exhausted'):
        return True
    try:
        if job['table_meta_id']:
            result = index_schema(str(job['user_id']), str(job['project_id']), str(job['table_meta_id']), job=job)
            if result == 'missing':
                _finish_failure(job, 'not_found', '삭제되었거나 접근할 수 없는 자료입니다.', cancelled=True)
            elif result == 'stale':
                _finish_failure(job, 'source_changed', '자료가 변경되어 최신 내용으로 다시 갱신합니다.')
        else:
            _document(job, storage or StorageService())
    except AppException as exc:
        detail = '문서의 검색 준비에 실패했습니다.' if exc.code == 'rag_index_failed' else exc.detail
        _finish_failure(job, exc.code, detail, permanent=exc.status_code in (400, 404, 413, 422), cancelled=exc.code == 'not_found')
    except Exception:
        # Never persist provider errors, SQL, credentials or original text in UI.
        logger.exception('Search indexing failed: job=%s attempt=%s', job['id'], job['attempts'])
        _finish_failure(job, 'index_unavailable', '검색 갱신에 실패했습니다. 자동으로 다시 시도합니다.')
    return True


def _project(conn, user_id, project_id):
    if not conn.execute('SELECT id FROM projects WHERE id=%s AND user_id=%s AND deleted_at IS NULL',
                        (project_id, user_id)).fetchone():
        raise ResourceNotFound('가게')


def list_jobs(user_id, project_id, limit=50, offset=0):
    with db._connect() as conn:
        _project(conn, user_id, project_id)
        where = '''FROM search_index_jobs j LEFT JOIN table_meta t ON t.id=j.table_meta_id
            LEFT JOIN files f ON f.id=j.file_id WHERE j.user_id=%s AND j.project_id=%s
            AND ((t.id IS NOT NULL AND t.user_id=j.user_id AND t.project_id=j.project_id AND t.deleted_at IS NULL)
                 OR (f.id IS NOT NULL AND f.user_id=j.user_id))'''
        counts = conn.execute('SELECT j.status,count(*) AS count ' + where + ' GROUP BY j.status', (user_id, project_id)).fetchall()
        rows = conn.execute('''SELECT j.id,j.table_meta_id,j.file_id,coalesce(t.name,f.filename) AS name,
            j.status,j.attempts,j.generation,j.completed_generation,j.next_attempt_at,j.last_error_code,j.last_error,
            j.last_success_at,j.updated_at ''' + where + ''' ORDER BY
            CASE j.status WHEN 'failed' THEN 0 WHEN 'retry' THEN 1 WHEN 'processing' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
            j.updated_at DESC,j.id LIMIT %s OFFSET %s''', (user_id, project_id, limit, offset)).fetchall()
    return {'jobs': rows, 'counts': {r['status']: r['count'] for r in counts}, 'total': sum(r['count'] for r in counts),
            'limit': limit, 'offset': offset, 'search_enabled': settings.rag_enabled,
            'worker_enabled': settings.rag_enabled and (settings.index_worker_enabled or settings.maintenance_enabled), 'max_attempts': MAX_ATTEMPTS}


def retry_job(user_id, project_id, job_id):
    with db._connect() as conn:
        _project(conn, user_id, project_id)
        # Retry does not acquire source locks after this job lock.
        job = conn.execute('SELECT * FROM search_index_jobs WHERE id=%s AND user_id=%s AND project_id=%s FOR UPDATE',
                           (job_id, user_id, project_id)).fetchone()
        if not job:
            raise ResourceNotFound('검색 갱신 작업')
        if job['status'] == 'cancelled':
            raise ResourceNotFound('검색 갱신 작업')
        # Double-click/replayed request cannot steal a live lease or reset backoff.
        if job['status'] not in ('failed', 'succeeded'):
            return {'id': job['id'], 'status': job['status'], 'replayed': True}
        conn.execute("""UPDATE search_index_jobs SET generation=generation+1,status='pending',attempts=0,
            lease_token=NULL,lease_until=NULL,next_attempt_at=clock_timestamp(),last_error_code=NULL,last_error=NULL,
            updated_at=clock_timestamp() WHERE id=%s""", (job_id,))
    return {'id': job_id, 'status': 'pending', 'replayed': False}


async def run_index_worker(stop: asyncio.Event):
    while not stop.is_set():
        try:
            for _ in range(10):
                if stop.is_set() or not await asyncio.to_thread(process_one):
                    break
        except Exception:
            logger.exception('Search index worker tick failed')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
