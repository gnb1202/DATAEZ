"""Execution lifecycle tests: real wrapper, simulated agent/transport outcomes."""
import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from app import quality
from app.llm_telemetry import TurnLedger, LlmCallRecord


@pytest.mark.parametrize('mode,expected', [('ok','completed'),('error','failed'),('exception','failed'),('incomplete','cancelled'),('budget','failed')])
def test_stream_terminal_state(mode, expected):
    async def flow():
        async def chunks():
            assert quality.active_run.get() == 'run'
            yield 'data: {"type":"token","data":{"content":"hello"}}\n\n'
            if mode == 'exception': raise RuntimeError('private provider detail')
            if mode == 'budget':
                yield 'data: {"type":"done","data":{"usage":{"turn_outcome":"budget_exhausted"}}}\n\n'
                return
            if mode != 'incomplete':
                # Terminal frames may span chunks.
                yield 'data: {"type":'
                yield '"done"}\n\n' if mode == 'ok' else '"error"}\n\n'
        @quality.observed_chat
        async def endpoint(**kwargs):
            assert quality.active_run.get() == 'run'
            return StreamingResponse(chunks())
        response = await endpoint(conversation_id='conv')
        assert quality.active_run.get() is None
        try:
            async for _ in response.body_iterator: pass
        except RuntimeError:
            assert mode == 'exception'
        assert quality.active_run.get() is None
    with patch.object(quality,'start_run',return_value='run'), patch.object(quality,'finish_run') as finish:
        asyncio.run(flow())
        assert finish.call_count == 1
        assert finish.call_args.args[1] == expected


def test_cancel_closes_generator_and_context():
    closed = []
    async def flow():
        async def chunks():
            try:
                yield 'data: {"type":"token"}\n\n'
                await asyncio.sleep(100)
            finally: closed.append(True)
        @quality.observed_chat
        async def endpoint(**kwargs): return StreamingResponse(chunks())
        response = await endpoint(conversation_id='conv')
        await anext(response.body_iterator)
        await response.body_iterator.aclose()
        assert quality.active_run.get() is None
    with patch.object(quality,'start_run',return_value='run'), patch.object(quality,'finish_run') as finish:
        asyncio.run(flow())
        assert finish.call_args.args[1] == 'cancelled'
        assert closed == [True]


@pytest.mark.parametrize('mode', ['success','agent_error','http_error'])
def test_sync_result_or_rejection(mode):
    @quality.observed_chat
    async def endpoint(**kwargs):
        if mode == 'http_error': raise HTTPException(429,'quota')
        return {'steps': [{'type':'error'}] if mode == 'agent_error' else []}
    with patch.object(quality,'start_run',return_value='run'), patch.object(quality,'finish_run') as finish:
        try: asyncio.run(endpoint(conversation_id='conv'))
        except HTTPException as exc: assert exc.status_code == 429
        assert finish.call_args.args[1] == ('completed' if mode == 'success' else 'failed')
        assert quality.active_run.get() is None


def test_observation_failure_not_replayed_or_leaked(caplog):
    with patch.object(quality.db, '_connect', side_effect=RuntimeError('SECRET')):
        assert quality.observe_sql('test', ()) is False
    assert 'quality_observation_write_failed' in caplog.text and 'SECRET' not in caplog.text


def test_call_details_include_model_latency_failure_not_prompt():
    summary = TurnLedger([LlmCallRecord('model-a','worker',10,2,duration_s=1.25,outcome='error')]).summary()
    call = summary['call_details'][0]
    assert call['model'] == 'model-a' and call['duration_s'] == 1.25 and call['outcome'] == 'error'
    assert 'prompt' not in call and summary['total_tokens'] == 12


@pytest.mark.parametrize('outcome', ['not_configured','budget_exhausted','llm_error','iterations_exhausted','incomplete_response'])
def test_non_success_answer_is_not_completed(outcome):
    assert quality.result_state({'steps':[{'type':'answer'}], 'usage':{'turn_outcome':outcome}}) == ('failed',outcome)


@pytest.mark.parametrize('mode', ['budget','llm_error'])
def test_sync_agent_emits_actual_failure_outcome(mode):
    from unittest.mock import MagicMock
    from app import agent
    executor=MagicMock(mutations_performed=False,schema_changed=False,mutated_table_ids=set())
    client=MagicMock()
    client.chat.completions.create.side_effect=RuntimeError('synthetic provider failure')
    with patch.object(agent,'_select_tools',return_value=([],'general',False)), patch.object(agent,'ToolExecutor',return_value=executor), patch.object(agent,'get_openai_client',return_value=client), patch.object(agent.settings,'agent_max_token_budget',0 if mode=='budget' else 1000):
        result=agent.run_agent('user','store','합성 가게',[],[],'합성 질문')
    expected='budget_exhausted' if mode=='budget' else 'llm_error'
    assert result.usage['turn_outcome']==expected
    assert quality.result_state(result.to_dict())==('failed',expected)
