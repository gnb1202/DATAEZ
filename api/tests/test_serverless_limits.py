import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing
import hashlib
import sys
from unittest.mock import patch

from fastapi import HTTPException
import pytest

from .test_file_library import live  # noqa: F401
from app import agent_process, rate_limiter as limits
from app.config import settings
from app.request_limit_schema import DDL


def test_database_admission_is_shared_and_expires(live):
    with live.connect() as conn: conn.execute(DDL)
    def attempt(_):
        try:
            limits.DatabaseRateLimiter().check('private-user',7,60)
            return True
        except HTTPException as error:
            assert error.status_code == 429
            assert error.headers['Retry-After'] == '60'
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt,range(24))) == 7
    with live.connect() as conn:
        row = conn.execute('SELECT * FROM request_limits').fetchone()
        assert row['used'] == 7 and row['key_hash'] == hashlib.sha256(b'private-user').hexdigest()
        conn.execute("UPDATE request_limits SET expires_at=now()-interval '1 second'")
    assert attempt(0)


def test_quota_backend_fails_closed(monkeypatch):
    monkeypatch.setattr('app.db._connect', lambda: (_ for _ in ()).throw(RuntimeError('secret')))
    with pytest.raises(HTTPException) as error:
        limits.DatabaseRateLimiter().check('key',1,60)
    assert error.value.status_code == 503 and 'secret' not in str(error.value.detail)


def test_per_user_and_global_ai_attempt_budget(monkeypatch):
    monkeypatch.setattr(settings,'runtime_mode','serverless')
    monkeypatch.setattr(settings,'ai_user_requests_per_day',1)
    monkeypatch.setattr(settings,'ai_total_requests_per_day',2)
    monkeypatch.setattr(limits,'rate_limiter',limits.InMemoryRateLimiter())
    limits.check_ai_budget('a')
    with pytest.raises(HTTPException): limits.check_ai_budget('a')
    limits.check_ai_budget('b')
    with pytest.raises(HTTPException): limits.check_ai_budget('c')


@pytest.mark.parametrize('stop', ['timeout','disconnect'])
def test_real_child_is_reaped_before_return(monkeypatch, stop):
    """An actual sleeping OS child is terminated, not just its awaiter."""
    children = []
    original = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        process = await original(sys.executable,'-c',
            'import sys,time; sys.stdin.buffer.read(); print(\'{"type":"step","data":{}}\',flush=True); time.sleep(60)', **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setattr(settings,'agent_timeout_seconds',0.4)
    async def run():
        if stop == 'timeout':
            with pytest.raises(TimeoutError):
                async for _ in agent_process.events('stream',{}): pass
        else:
            async with aclosing(agent_process.events('stream',{})) as stream:
                await anext(stream)
        assert children and children[0].returncode is not None
    asyncio.run(run())


def test_worker_protocol_returns_answer_without_external_calls(monkeypatch):
    environment = agent_process.child_environment()
    # Suppress provider calls inside the real worker, after valid config loads.
    original = asyncio.create_subprocess_exec
    async def spawn(*args,**kwargs):
        kwargs['env'] = environment
        return await original(sys.executable,'-c',
            'import asyncio; from app.config import settings; settings.openai_api_key=""; from app.agent_worker import main; asyncio.run(main())',
            'sync',**kwargs)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    result = asyncio.run(agent_process.run_bounded_agent(user_id='u',project_id='p',project_name='p',
        tables_info=[],conversation_messages=[],question='hello'))
    assert 'OpenAI' in result.answer and result.mutated_table_ids == []
