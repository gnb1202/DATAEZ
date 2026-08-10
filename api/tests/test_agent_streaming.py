"""Tests for the streaming agent loop.

The loop had no tests at all — test_agent.py covered only _parse_suggestions.
These cover what the streaming rewrite changed: token frames arriving before
the turn ends, tool-call fragments reassembled across chunks, usage captured
from the choices-less final chunk, and failures surfacing as an error frame
rather than a truncated stream.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import run_agent_streaming


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    """Build one streamed chat-completion chunk."""
    if usage is not None and content is None and tool_calls is None:
        # The usage-bearing chunk carries no choices at all.
        return SimpleNamespace(choices=[], usage=usage)
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _tool_delta(index, call_id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()


def _client_yielding(chunks):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_FakeStream(chunks))
    return client


async def _collect(**overrides):
    kwargs = dict(
        user_id="u1",
        project_id="p1",
        project_name="proj",
        tables_info=[],
        conversation_messages=[],
        question="매출 알려줘",
    )
    kwargs.update(overrides)
    return [step async for step in run_agent_streaming(**kwargs)]


def _stub_executor():
    executor = MagicMock()
    executor.execute.return_value = {"ok": True}
    executor.mutations_performed = False
    executor.schema_changed = False
    executor.mutated_table_ids = set()
    return executor


@pytest.fixture(autouse=True)
def _isolated_agent():
    """Skip the orchestrator call and the real ToolExecutor.

    Routing is covered by the eval suite, and constructing a real executor
    would open a database connection.
    """
    with patch("app.agent._select_tools", return_value=([], "general", False)), \
         patch("app.agent.ToolExecutor", return_value=_stub_executor()):
        yield


@pytest.mark.asyncio
class TestTokenStreaming:
    async def test_tokens_are_emitted_before_the_turn_ends(self):
        """The point of the rewrite: text arrives incrementally."""
        chunks = [
            _chunk(content="월 매출은 "),
            _chunk(content="120만원"),
            _chunk(content="입니다.", finish_reason="stop"),
            _chunk(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)),
        ]
        with patch("app.agent.get_async_openai_client", return_value=_client_yielding(chunks)):
            steps = await _collect()

        tokens = [s for s in steps if s.type == "token"]
        assert [t.content for t in tokens] == ["월 매출은 ", "120만원", "입니다."]

        answer = next(s for s in steps if s.type == "answer")
        assert answer.content == "월 매출은 120만원입니다."
        # The answer frame must come after the tokens it assembles.
        assert steps.index(answer) > steps.index(tokens[-1])

    async def test_usage_from_the_choiceless_chunk_is_recorded(self):
        """Streaming previously reported zero tokens for every turn."""
        chunks = [
            _chunk(content="네", finish_reason="stop"),
            _chunk(usage=SimpleNamespace(prompt_tokens=80, completion_tokens=5, total_tokens=85)),
        ]
        with patch("app.agent.get_async_openai_client", return_value=_client_yielding(chunks)):
            steps = await _collect()

        meta = next(s for s in steps if s.type == "meta")
        import json

        usage = json.loads(meta.content)["usage"]
        assert usage["total_tokens"] == 85
        assert usage["prompt_tokens"] == 80

    async def test_meta_frame_is_emitted_even_without_mutations(self):
        """It used to be sent only when a mutation happened, so the endpoint
        had no usage figures to persist on a read-only turn."""
        chunks = [_chunk(content="안녕하세요", finish_reason="stop")]
        with patch("app.agent.get_async_openai_client", return_value=_client_yielding(chunks)):
            steps = await _collect()
        assert any(s.type == "meta" for s in steps)


@pytest.mark.asyncio
class TestToolCallAssembly:
    async def test_fragmented_tool_call_is_reassembled(self):
        """Name and arguments arrive split across chunks and must be
        concatenated, not overwritten."""
        first_round = [
            _chunk(tool_calls=[_tool_delta(0, call_id="call_1", name="list_", arguments="")]),
            _chunk(tool_calls=[_tool_delta(0, name="tables", arguments='{"dum')]),
            _chunk(tool_calls=[_tool_delta(0, arguments='my": 1}')], finish_reason="tool_calls"),
        ]
        second_round = [_chunk(content="완료", finish_reason="stop")]

        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[_FakeStream(first_round), _FakeStream(second_round)]
        )
        executor = MagicMock()
        executor.execute.return_value = {"tables": []}
        executor.mutations_performed = False
        executor.schema_changed = False
        executor.mutated_table_ids = set()

        with patch("app.agent.get_async_openai_client", return_value=client), \
             patch("app.agent.ToolExecutor", return_value=executor), \
             patch("app.agent._select_tools", return_value=([{"function": {"name": "list_tables"}}], "schema", False)):
            steps = await _collect()

        tool_steps = [s for s in steps if s.type == "tool_call"]
        assert len(tool_steps) == 1
        assert tool_steps[0].tool_name == "list_tables"
        assert tool_steps[0].tool_input == {"dummy": 1}
        executor.execute.assert_called_once_with("list_tables", '{"dummy": 1}')

    async def test_parallel_tool_calls_are_kept_separate_by_index(self):
        first_round = [
            _chunk(tool_calls=[
                _tool_delta(0, call_id="c0", name="list_tables", arguments="{}"),
                _tool_delta(1, call_id="c1", name="describe_table", arguments='{"a":1}'),
            ], finish_reason="tool_calls"),
        ]
        second_round = [_chunk(content="끝", finish_reason="stop")]

        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[_FakeStream(first_round), _FakeStream(second_round)]
        )
        executor = MagicMock()
        executor.execute.return_value = {"ok": True}
        executor.mutations_performed = False
        executor.schema_changed = False
        executor.mutated_table_ids = set()

        with patch("app.agent.get_async_openai_client", return_value=client), \
             patch("app.agent.ToolExecutor", return_value=executor), \
             patch("app.agent._select_tools", return_value=([{"function": {"name": "list_tables"}}], "schema", False)):
            steps = await _collect()

        names = [s.tool_name for s in steps if s.type == "tool_call"]
        assert names == ["list_tables", "describe_table"]


@pytest.mark.asyncio
class TestFailureSurfacing:
    async def test_llm_failure_yields_an_error_frame(self):
        """A mid-stream failure must be reported, not silently truncate."""
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("upstream down"))

        with patch("app.agent.get_async_openai_client", return_value=client):
            steps = await _collect()

        assert [s.type for s in steps] == ["error"]
        assert "오류" in steps[0].content

    async def test_missing_api_key_short_circuits(self):
        with patch("app.agent.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            steps = await _collect()
        assert steps[0].type == "answer"
