"""Authenticated, bounded serverless entrypoint; no resident scheduler needed."""
import hmac
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from . import db
from .config import settings

router = APIRouter(prefix='/api/internal/maintenance', tags=['maintenance'])
logger = logging.getLogger(__name__)
Kind = Literal['index', 'metrics', 'cleanup']
HARD_TIMEOUT_SECONDS = 120
LEASE_SECONDS = 180


def authorize(authorization: str = Header('')):
    if not settings.maintenance_enabled:
        raise HTTPException(503, 'Scheduled maintenance is disabled')
    expected = 'Bearer ' + settings.maintenance_secret
    if not settings.maintenance_secret or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, 'Invalid maintenance credentials')


def claim(kind):
    token = uuid4()
    with db._connect() as conn:
        conn.execute("SET LOCAL statement_timeout = '5s'")
        row = conn.execute("""INSERT INTO maintenance_runs(kind,lease_token,lease_until,last_started_at,status,attempts)
            VALUES(%s,%s,clock_timestamp()+(%s * interval '1 second'),clock_timestamp(),'running',1)
            ON CONFLICT(kind) DO UPDATE SET lease_token=EXCLUDED.lease_token,lease_until=EXCLUDED.lease_until,
                last_started_at=clock_timestamp(),status='running',attempts=maintenance_runs.attempts+1
            WHERE (maintenance_runs.lease_until IS NULL OR maintenance_runs.lease_until<=clock_timestamp())
              AND (maintenance_runs.last_finished_at IS NULL OR maintenance_runs.last_finished_at<clock_timestamp()-interval '10 seconds')
            RETURNING lease_token""", (kind,token,LEASE_SECONDS)).fetchone()
    return token if row else None


def finish(kind, token, status, processed):
    with db._connect() as conn:
        conn.execute("SET LOCAL statement_timeout = '5s'")
        conn.execute("""UPDATE maintenance_runs SET status=%s,processed=%s,last_finished_at=clock_timestamp(),
            lease_token=NULL,lease_until=NULL,failures=failures+%s
            WHERE kind=%s AND lease_token=%s""", (status,processed,int(status!='succeeded'),kind,token))


def run_child(kind):
    # A thread timeout cannot stop parsing, an SDK retry, or a DB write. A child
    # process gives a real stop boundary; subprocess.run kills AND waits on timeout.
    environment = {**os.environ, 'PYTHONIOENCODING':'utf-8', 'DB_POOL_MIN_SIZE':'0',
                   'DB_POOL_MAX_SIZE':'1', 'DB_POOL_TIMEOUT':'5', 'DB_CONNECT_TIMEOUT':'5'}
    # Settings may have loaded a local dotenv file rather than the OS environment.
    for name in type(settings).model_fields:
        value = getattr(settings, name)
        environment[name.upper()] = str(value).lower() if isinstance(value, bool) else str(value)
    environment.update(DB_POOL_MIN_SIZE='0', DB_POOL_MAX_SIZE='1', DB_POOL_TIMEOUT='5', DB_CONNECT_TIMEOUT='5')
    # Vercel's bootstrap adds bundled dependencies to sys.path in-process.
    # Python subprocesses need that same search path explicitly.
    environment['PYTHONPATH'] = os.pathsep.join(str(p) for p in sys.path if p)
    result = subprocess.run([sys.executable, '-m', 'app.maintenance_worker', kind],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=HARD_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0:
        logger.warning('Maintenance child exited: kind=%s exit_code=%s', kind, result.returncode)
        raise RuntimeError('Maintenance task failed')
    payload = json.loads(result.stdout)
    if set(payload) != {'processed'} or type(payload['processed']) is not int or not 0 <= payload['processed'] <= 10:
        raise RuntimeError('Invalid maintenance result')
    return payload['processed']


@router.get('/status', dependencies=[Depends(authorize)])
def status(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    with db._connect() as conn:
        rows = conn.execute('SELECT kind,status,processed,attempts,failures,last_started_at,last_finished_at,lease_until FROM maintenance_runs ORDER BY kind').fetchall()
    return {'tasks': rows}


@router.post('/{kind}', dependencies=[Depends(authorize)])
def run(kind: Kind, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    token = claim(kind)
    if token is None:
        return {'kind':kind, 'status':'busy', 'processed':0}
    outcome, processed = 'succeeded', 0
    try:
        processed = run_child(kind)
    except subprocess.TimeoutExpired:
        outcome = 'timeout'
    except Exception as error:
        logger.warning('Maintenance runner failed: kind=%s error_type=%s', kind, type(error).__name__)
        outcome = 'failed'
    finish(kind, token, outcome, processed)
    if outcome != 'succeeded':
        response.status_code = 504 if outcome == 'timeout' else 503
    return {'kind':kind, 'status':outcome, 'processed':processed}
