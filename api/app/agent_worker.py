"""Private JSON-lines IPC. No credentials or provider logs go to stdout."""
import asyncio
import base64
from dataclasses import asdict
import json
import logging
import sys


def emit(kind, data=None):
    print(json.dumps({'type': kind, 'data': data}, ensure_ascii=False, default=str), flush=True)


async def main():
    logging.disable(logging.CRITICAL)
    from .agent import run_agent, run_agent_streaming
    from .db import close_pool
    arguments = json.loads(sys.stdin.buffer.read())
    for file in arguments.get('attached_files') or []:
        file['content'] = base64.b64decode(file['content'], validate=True)
    try:
        if sys.argv[1] == 'sync':
            result = asdict(run_agent(**arguments))
            result['mutated_table_ids'] = list(result['mutated_table_ids'])
            emit('result', result)
        else:
            async for step in run_agent_streaming(**arguments):
                emit('step', asdict(step))
        emit('complete')
    finally:
        close_pool()


if __name__ == '__main__':
    asyncio.run(main())
