"""A kill-and-wait boundary for serverless AI turns (including tool threads)."""
import asyncio
import base64
from contextlib import aclosing
import json
import os
from pathlib import Path
import subprocess
import sys

from .agent import AgentResult, AgentStep
from .config import settings

INTERRUPTED = '분석 실행 시간이 초과되었거나 중단되었습니다. 일부 변경은 이미 반영되었을 수 있으니 분석 이력과 장부를 확인한 뒤 다시 요청해주세요.'


def child_environment():
    environment = dict(os.environ)
    for name in type(settings).model_fields:
        value = getattr(settings, name)
        environment[name.upper()] = str(value).lower() if isinstance(value, bool) else str(value)
    environment.update(PYTHONIOENCODING='utf-8', DB_POOL_MIN_SIZE='0', DB_POOL_MAX_SIZE='1',
                       DB_POOL_TIMEOUT='5', DB_CONNECT_TIMEOUT='5',
                       PYTHONPATH=os.pathsep.join(str(p) for p in sys.path if p))
    return environment


async def events(mode, arguments):
    payload = dict(arguments)
    payload['attached_files'] = [{**f, 'content': base64.b64encode(f['content']).decode('ascii')}
                                 for f in arguments.get('attached_files') or []]
    process = None
    try:
        async with asyncio.timeout(settings.agent_timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'app.agent_worker', mode,
                cwd=Path(__file__).resolve().parents[1], env=child_environment(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4 * 1024 * 1024,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            process.stdin.write(json.dumps(payload, default=str).encode())
            await process.stdin.drain()
            process.stdin.close()
            completed = False
            while line := await process.stdout.readline():
                frame = json.loads(line)
                if frame.get('type') == 'complete':
                    completed = True
                    break
                yield frame
            await process.wait()
            if process.returncode or not completed:
                raise RuntimeError('Interrupted agent process')
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


async def run_bounded_agent(**arguments):
    result = None
    try:
        async with aclosing(events('sync', arguments)) as frames:
            async for frame in frames:
                if frame.get('type') == 'result':
                    data = frame['data']
                    data['steps'] = [AgentStep(**s) for s in data['steps']]
                    result = AgentResult(**data)
        if result is None:
            raise RuntimeError('Missing agent result')
        return result
    except Exception:
        return AgentResult(answer=INTERRUPTED, steps=[AgentStep(type='error', content=INTERRUPTED)])


async def stream_bounded_agent(**arguments):
    try:
        async with aclosing(events('stream', arguments)) as frames:
            async for frame in frames:
                if frame.get('type') == 'step':
                    yield AgentStep(**frame['data'])
    except Exception:
        yield AgentStep(type='error', content=INTERRUPTED)
