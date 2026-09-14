"""Private quality observations. Custom JWT authorization; no Data API access."""
import hashlib
import json
import logging
from contextvars import ContextVar
from functools import lru_cache, wraps
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from . import db
from .auth import get_current_user
from .config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quality", tags=["quality"])
active_run: ContextVar[str | None] = ContextVar("quality_run", default=None)

DDL = """
CREATE TABLE IF NOT EXISTS quality_runs (
 id UUID PRIMARY KEY,
 conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 user_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
 assistant_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
 started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 duration_ms INTEGER, error_code TEXT, version JSONB NOT NULL,
 review JSONB, reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
 reviewed_at TIMESTAMPTZ, candidate JSONB
);
CREATE INDEX IF NOT EXISTS quality_runs_recent ON quality_runs(started_at DESC, id);
CREATE INDEX IF NOT EXISTS quality_runs_conversation ON quality_runs(conversation_id);
CREATE TABLE IF NOT EXISTS message_feedback (
 message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
 rating INTEGER NOT NULL CHECK(rating IN (-1,1)),
 reason TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '',
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE quality_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_feedback ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON quality_runs, message_feedback FROM PUBLIC;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
  REVOKE ALL ON quality_runs, message_feedback FROM anon;
 END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
  REVOKE ALL ON quality_runs, message_feedback FROM authenticated;
 END IF;
END $$;
"""


def ensure_quality():
    with db._connect() as conn:
        conn.execute(DDL)
        conn.commit()


@lru_cache(maxsize=1)
def code_fingerprint():
    root = Path(__file__).parent
    names = ('prompts.py', 'library_agent.py', 'router.py', 'agent.py', 'agent_tools.py')
    return hashlib.sha256(b''.join(name.encode() + (root / name).read_bytes() for name in names)).hexdigest()


def observe_sql(statement, params):
    """Observation failure never replays or turns a completed user operation into failure."""
    try:
        with db._connect() as conn:
            conn.execute(statement, params)
            conn.commit()
        return True
    except Exception:
        # Avoid leaking DB/provider exceptions and request contents to platform logs.
        logger.error('quality_observation_write_failed')
        return False


def start_run(conversation_id):
    run_id = str(uuid4())
    version = {'worker': settings.openai_model, 'router': settings.openai_orchestrator_model,
               'code_sha256': code_fingerprint(), 'release': settings.quality_release,
               'max_iterations': settings.agent_max_iterations, 'token_budget': settings.agent_max_token_budget}
    ok = observe_sql('INSERT INTO quality_runs(id,conversation_id,status,version) VALUES(%s,%s,\'running\',%s::jsonb)',
                     (run_id, conversation_id, json.dumps(version)))
    return run_id if ok else None


def link_message(message_id, role):
    run_id = active_run.get()
    if run_id and role in ('user', 'assistant'):
        column = 'user_message_id' if role == 'user' else 'assistant_message_id'
        observe_sql(f'UPDATE quality_runs SET {column}=%s WHERE id=%s', (message_id, run_id))


def finish_run(run_id, status, code=None):
    if run_id:
        observe_sql("""UPDATE quality_runs SET status=%s,error_code=%s,finished_at=clock_timestamp(),
          duration_ms=LEAST(2147483647,EXTRACT(EPOCH FROM (clock_timestamp()-started_at))*1000)::integer
          WHERE id=%s AND status='running'""", (status, code, run_id))


def result_state(result):
    outcome = (result.get('usage') or {}).get('turn_outcome', 'completed')
    known_failures = {'not_configured','budget_exhausted','llm_error','iterations_exhausted','incomplete_response'}
    if outcome in known_failures:
        return 'failed', outcome
    if any(s.get('type') == 'error' for s in result.get('steps', [])):
        return 'failed', 'agent_error'
    return 'completed', None


def observed_chat(fn):
    """Track both request execution and the lifetime of a streamed response."""
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        run_id = start_run(kwargs['conversation_id'])
        token = active_run.set(run_id)
        try:
            response = await fn(*args, **kwargs)
        except BaseException as exc:
            import asyncio
            finish_run(run_id, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed',
                       f'http_{exc.status_code}' if isinstance(exc, HTTPException) else type(exc).__name__)
            raise
        finally:
            active_run.reset(token)
        if not isinstance(response, StreamingResponse):
            finish_run(run_id, *result_state(response))
            return response
        original = response.body_iterator

        async def body():
            token = active_run.set(run_id)
            status, code, buffer = 'cancelled', 'stream_incomplete', ''
            try:
                async for chunk in original:
                    buffer += chunk.decode('utf-8') if isinstance(chunk, bytes) else chunk
                    while '\n\n' in buffer:
                        frame, buffer = buffer.split('\n\n', 1)
                        for line in frame.splitlines():
                            if line.startswith('data: '):
                                event = json.loads(line[6:])
                                if event.get('type') == 'error':
                                    status, code = 'failed', 'stream_error'
                                elif event.get('type') == 'done' and status != 'failed':
                                    status, code = result_state(event.get('data') or {})
                    yield chunk
            except Exception:
                status, code = 'failed', 'stream_exception'
                raise
            finally:
                try:
                    await original.aclose()
                finally:
                    finish_run(run_id, status, code)
                    active_run.reset(token)
        response.body_iterator = body()
        return response
    return wrapped


def is_admin(user):
    return str(user['id']) in {v.strip() for v in settings.quality_admin_user_ids.split(',') if v.strip()}


def require_admin(response: Response, user=Depends(get_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    if not is_admin(user):
        raise HTTPException(403, '품질 검토 권한이 없습니다.')
    return user


@router.get('/access')
def access(response: Response, user=Depends(get_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return {'admin': is_admin(user)}


Reason = Literal['', 'calculation', 'intent', 'chart', 'scope', 'incomplete', 'other']


class Feedback(BaseModel):
    rating: Literal[-1, 1]
    reason: Reason = ''
    comment: str = Field(default='', max_length=1000)


def owned_assistant(conn, message_id, user):
    row = conn.execute("""SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE m.id=%s AND c.user_id=%s AND m.role='assistant'""", (message_id, user['id'])).fetchone()
    if not row:
        raise HTTPException(404, '답변을 찾을 수 없습니다.')


@router.get('/messages/{message_id}/feedback')
def get_feedback(message_id: UUID, response: Response, user=Depends(get_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    with db._connect() as conn:
        owned_assistant(conn, message_id, user)
        return {'feedback': conn.execute('SELECT rating,reason,comment FROM message_feedback WHERE message_id=%s', (message_id,)).fetchone()}


@router.put('/messages/{message_id}/feedback')
def put_feedback(message_id: UUID, payload: Feedback, user=Depends(get_current_user)):
    with db._connect() as conn:
        owned_assistant(conn, message_id, user)
        conn.execute("""INSERT INTO message_feedback(message_id,rating,reason,comment) VALUES(%s,%s,%s,%s)
            ON CONFLICT(message_id) DO UPDATE SET rating=EXCLUDED.rating,reason=EXCLUDED.reason,
            comment=EXCLUDED.comment,updated_at=now()""", (message_id, payload.rating, payload.reason, payload.comment))
        conn.commit()
    return {'feedback': payload.model_dump()}


RUN_FROM = """FROM quality_runs r JOIN conversations c ON c.id=r.conversation_id
 LEFT JOIN messages q ON q.id=r.user_message_id LEFT JOIN messages a ON a.id=r.assistant_message_id
 LEFT JOIN message_feedback f ON f.message_id=r.assistant_message_id"""
STATUS = "CASE WHEN r.status='running' AND r.started_at < now()-interval '10 minutes' THEN 'unconfirmed' ELSE r.status END"


@router.get('/runs')
def runs(status: Literal['all','running','completed','failed','cancelled','unconfirmed','negative','unreviewed']='all',
         user_id: UUID | None=None, limit: int=Query(30, ge=1, le=100), offset: int=Query(0, ge=0, le=100000),
         admin=Depends(require_admin)):
    conditions, params = [], []
    if status == 'negative': conditions.append('f.rating=-1')
    elif status == 'unreviewed': conditions.append('r.review IS NULL')
    elif status != 'all': conditions.append(f'{STATUS}=%s'); params.append(status)
    if user_id: conditions.append('c.user_id=%s'); params.append(user_id)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    with db._connect() as conn:
        total = conn.execute('SELECT count(*) AS n '+RUN_FROM+where, params).fetchone()['n']
        rows = conn.execute(f"""SELECT r.id,c.user_id,c.project_id,r.conversation_id,{STATUS} AS status,
          r.started_at,r.duration_ms,r.error_code,r.version,r.review,f.rating,LEFT(q.content,200) AS question,
          a.total_tokens,a.cost_usd {RUN_FROM}{where} ORDER BY r.started_at DESC,r.id DESC LIMIT %s OFFSET %s""",
          params+[limit, offset]).fetchall()
    db.record_audit(admin['id'], 'read', 'quality_runs', None)
    return {'runs': rows, 'total': total}


def run_detail(run_id):
    with db._connect() as conn:
        row = conn.execute(f"""SELECT r.*,c.user_id,c.project_id,{STATUS} AS observed_status,
          q.content AS question,q.steps AS references,a.content AS answer,a.steps,a.charts,a.table_data,a.usage,
          f.rating,f.reason AS feedback_reason,f.comment AS feedback_comment {RUN_FROM} WHERE r.id=%s""", (run_id,)).fetchone()
    if not row: raise HTTPException(404, '실행 기록을 찾을 수 없습니다.')
    return row


@router.get('/runs/{run_id}')
def detail(run_id: UUID, admin=Depends(require_admin)):
    row = run_detail(run_id)
    db.record_audit(admin['id'], 'read', 'quality_run', str(run_id))
    return row


class Review(BaseModel):
    verdict: Literal['pass','fail','needs_review']
    category: Reason = ''
    note: str = Field(default='', max_length=2000)


@router.put('/runs/{run_id}/review')
def review(run_id: UUID, payload: Review, admin=Depends(require_admin)):
    with db._connect() as conn:
        row = conn.execute('UPDATE quality_runs SET review=%s::jsonb,reviewed_by=%s,reviewed_at=now() WHERE id=%s RETURNING id',
                           (payload.model_dump_json(), admin['id'], run_id)).fetchone()
        if not row: raise HTTPException(404, '실행 기록을 찾을 수 없습니다.')
        conn.commit()
    db.record_audit(admin['id'], 'review', 'quality_run', str(run_id))
    return {'review': payload.model_dump()}


class Candidate(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    expected_behavior: str = Field(min_length=5, max_length=3000)
    synthetic_confirmed: Literal[True]


@router.put('/runs/{run_id}/candidate')
def candidate(run_id: UUID, payload: Candidate, admin=Depends(require_admin)):
    with db._connect() as conn:
        row = conn.execute("""UPDATE quality_runs SET candidate=%s::jsonb WHERE id=%s
             AND review->>'verdict'='fail' RETURNING id""", (payload.model_dump_json(), run_id)).fetchone()
        if not row: raise HTTPException(409, '실패로 검토한 실행에서만 후보를 만들 수 있습니다.')
        conn.commit()
    db.record_audit(admin['id'], 'candidate', 'quality_run', str(run_id))
    return {'candidate': payload.model_dump()}


@router.get('/runs/{run_id}/candidate')
def export_candidate(run_id: UUID, admin=Depends(require_admin)):
    row = run_detail(run_id)
    if not row['candidate'] or (row['review'] or {}).get('verdict') != 'fail':
        raise HTTPException(409, '검토된 회귀 후보가 없습니다.')
    db.record_audit(admin['id'], 'export', 'quality_candidate', str(run_id))
    # Deliberately exclude original question, answer, UUIDs, traces and data rows.
    return {'schema_version': 1, 'kind': 'synthetic_regression_candidate', **row['candidate']}
