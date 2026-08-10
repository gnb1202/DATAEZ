"""Core AI Agent loop with OpenAI Function Calling — project-level multi-table."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from .agent_tools import TOOL_SPECS, ToolExecutor
from .config import settings
from .openai_clients import get_async_openai_client, get_openai_client
from .prompts import build_conversation_context, build_system_prompt
from .router import OrchestratorResult, select_tools_via_orchestrator

@dataclass
class AgentStep:
    type: str  # "thinking" | "tool_call" | "tool_result" | "answer"
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.content:
            d["content"] = self.content
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.tool_input:
            d["tool_input"] = self.tool_input
        if self.tool_output:
            # Truncate large outputs for storage
            output_str = json.dumps(self.tool_output, ensure_ascii=False, default=str)
            if len(output_str) > 3000:
                d["tool_output"] = {"_truncated": True, "summary": output_str[:3000] + "..."}
            else:
                d["tool_output"] = self.tool_output
        return d




@dataclass
class AgentResult:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    table_data: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    mutations_performed: bool = False
    schema_changed: bool = False
    mutated_table_ids: set[str] = field(default_factory=set)
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "steps": [s.to_dict() for s in self.steps],
            "charts": self.charts,
            "table_data": self.table_data,
            "suggestions": self.suggestions,
            "mutations_performed": self.mutations_performed,
            "schema_changed": self.schema_changed,
            "total_tokens": self.total_tokens,
        }


def _parse_suggestions(text: str) -> tuple[str, list[str]]:
    """Extract suggestions from the answer text and return (clean_answer, suggestions).

    Supports multiple marker formats for robustness:
    - ---SUGGESTIONS---
    - ---suggestions---
    - ---제안---
    """
    import re

    # Pattern: ---SUGGESTIONS--- (case-insensitive, flexible whitespace)
    marker_pattern = r'---\s*(?:SUGGESTIONS?|제안)\s*---\s*\n?(.*?)$'
    match = re.search(marker_pattern, text, re.IGNORECASE | re.DOTALL)

    if match:
        clean = text[:match.start()].rstrip()
        raw = match.group(1).strip()
        suggestions = [s.strip() for s in raw.split("|") if s.strip()]
        if suggestions:
            return clean, suggestions[:3]

    # Fallback: last line contains | separators (no marker)
    lines = text.rstrip().split("\n")
    if lines and "|" in lines[-1] and lines[-1].count("|") >= 1:
        raw = lines[-1]
        suggestions = [s.strip() for s in raw.split("|") if s.strip()]
        if 2 <= len(suggestions) <= 4:
            clean = "\n".join(lines[:-1]).rstrip()
            return clean, suggestions[:3]

    return text, []


def _select_tools(question: str, has_attachments: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Orchestrator LLM을 통해 질문에 필요한 툴과 intent를 반환."""
    all_tool_names = [t["function"]["name"] for t in TOOL_SPECS]
    result: OrchestratorResult = select_tools_via_orchestrator(question, has_attachments, all_tool_names)
    if result.tools is None:
        return TOOL_SPECS, result.intent
    return [t for t in TOOL_SPECS if t["function"]["name"] in result.tools], result.intent


def run_agent(
    user_id: str,
    project_id: str,
    project_name: str,
    tables_info: list[dict[str, Any]],
    conversation_messages: list[dict[str, str]],
    question: str,
    attached_files: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Run the agent loop with function calling against project tables."""
    if not settings.openai_api_key:
        return AgentResult(
            answer="OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요.",
            steps=[AgentStep(type="answer", content="API key not configured")],
        )

    has_attachments = bool(attached_files)
    active_tools, intent = _select_tools(question, has_attachments=has_attachments)
    logger.info("Orchestrator selected tools=%d, intent=%s: %s", len(active_tools), intent, [t["function"]["name"] for t in active_tools])

    client = get_openai_client()
    executor = ToolExecutor(user_id, project_id, attached_files=attached_files)

    system_prompt = build_system_prompt(
        project_name, tables_info, intent=intent, has_attachments=has_attachments,
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # Add compressed conversation history
    for msg in build_conversation_context(conversation_messages):
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Inject file descriptions into user message
    user_content = question
    if attached_files:
        file_desc = "\n".join(
            f"[첨부파일 {i}] {f['filename']} ({len(f['content'])} bytes)"
            for i, f in enumerate(attached_files)
        )
        user_content = f"{question}\n\n---\n첨부된 파일:\n{file_desc}"

    messages.append({"role": "user", "content": user_content})

    steps: list[AgentStep] = []
    charts: list[dict[str, Any]] = []
    table_data: list[dict[str, Any]] = []
    answer = ""
    total_tokens = 0

    # Greeting/no-tools intent: skip tool forcing entirely
    skip_tool_forcing = not active_tools

    for iteration in range(settings.agent_max_iterations):
        # Budget guard
        if total_tokens >= settings.agent_max_token_budget:
            logger.warning("Token budget exhausted (%d tokens), stopping agent", total_tokens)
            answer = "토큰 예산이 초과되었습니다. 더 간결한 질문으로 다시 시도해주세요."
            steps.append(AgentStep(type="answer", content=answer))
            break

        logger.info("Agent iteration %d/%d (tokens used: %d)", iteration + 1, settings.agent_max_iterations, total_tokens)
        # Force tool call on first iteration only for data-related intents
        tc = "auto"
        if iteration == 0 and not skip_tool_forcing:
            tc = "required"

        # For greeting intent with no tools, don't pass tools at all
        call_kwargs: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": messages,
        }
        if active_tools:
            call_kwargs["tools"] = active_tools
            call_kwargs["tool_choice"] = tc

        try:
            response = client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            logger.error("LLM call failed", exc_info=True)
            answer = "AI 모델 호출 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            steps.append(AgentStep(type="answer", content=answer))
            break

        # Track token usage
        if response.usage:
            total_tokens += response.usage.total_tokens

        choice = response.choices[0]

        if choice.message.tool_calls:
            messages.append(choice.message.model_dump())

            for tool_call in choice.message.tool_calls:
                tool_name = tool_call.function.name
                tool_args_str = tool_call.function.arguments

                try:
                    tool_input = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_input = {"raw": tool_args_str}

                logger.info("  Tool call: %s(%s)", tool_name, tool_args_str[:200])
                tool_output = executor.execute(tool_name, tool_args_str)

                steps.append(AgentStep(
                    type="tool_call",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output,
                ))

                # Collect charts and table data
                if tool_name == "generate_chart" and "chart_type" in tool_output:
                    charts.append(tool_output)
                if tool_name in ("query_data", "cross_query") and "data" in tool_output:
                    table_data = tool_output["data"]

                tool_result_str = json.dumps(tool_output, ensure_ascii=False, default=str)
                if len(tool_result_str) > 4000:
                    tool_result_str = tool_result_str[:4000] + "... (truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str,
                })

        elif choice.finish_reason == "stop":
            answer = choice.message.content or ""
            steps.append(AgentStep(type="answer", content=answer))
            break
        else:
            answer = choice.message.content or "분석이 완료되었습니다."
            steps.append(AgentStep(type="answer", content=answer))
            break

    if not answer:
        answer = "최대 반복 횟수에 도달했습니다. 더 구체적인 질문으로 다시 시도해주세요."
        steps.append(AgentStep(type="answer", content=answer))

    answer, suggestions = _parse_suggestions(answer)
    logger.info("Agent finished: %d total tokens used", total_tokens)
    return AgentResult(
        answer=answer,
        steps=steps,
        charts=charts,
        table_data=table_data,
        suggestions=suggestions,
        mutations_performed=executor.mutations_performed,
        schema_changed=executor.schema_changed,
        mutated_table_ids=executor.mutated_table_ids,
        total_tokens=total_tokens,
    )


# ---------------------------------------------------------------------------
# Streaming variants (async generators for SSE)
# ---------------------------------------------------------------------------


async def run_agent_streaming(
    user_id: str,
    project_id: str,
    project_name: str,
    tables_info: list[dict[str, Any]],
    conversation_messages: list[dict[str, str]],
    question: str,
    attached_files: list[dict[str, Any]] | None = None,
):
    """Async generator that yields AgentStep objects in real-time."""
    if not settings.openai_api_key:
        yield AgentStep(
            type="answer",
            content="OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요.",
        )
        return

    has_attachments = bool(attached_files)
    active_tools, intent = _select_tools(question, has_attachments=has_attachments)
    logger.info("Orchestrator selected tools=%d, intent=%s (streaming): %s", len(active_tools), intent, [t["function"]["name"] for t in active_tools])

    async_client = get_async_openai_client()
    executor = ToolExecutor(user_id, project_id, attached_files=attached_files)

    system_prompt = build_system_prompt(
        project_name, tables_info, intent=intent, has_attachments=has_attachments,
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    for msg in build_conversation_context(conversation_messages):
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Inject file descriptions into user message
    user_content = question
    if attached_files:
        file_desc = "\n".join(
            f"[첨부파일 {i}] {f['filename']} ({len(f['content'])} bytes)"
            for i, f in enumerate(attached_files)
        )
        user_content = f"{question}\n\n---\n첨부된 파일:\n{file_desc}"

    messages.append({"role": "user", "content": user_content})

    # Greeting/no-tools intent: skip tool forcing entirely
    skip_tool_forcing = not active_tools
    total_tokens = 0

    for iteration in range(settings.agent_max_iterations):
        if total_tokens >= settings.agent_max_token_budget:
            logger.warning("Token budget exhausted (%d tokens), stopping streaming agent", total_tokens)
            yield AgentStep(type="answer", content="토큰 예산이 초과되었습니다. 더 간결한 질문으로 다시 시도해주세요.")
            return

        logger.info("Agent streaming iteration %d/%d (tokens used: %d)", iteration + 1, settings.agent_max_iterations, total_tokens)
        # Force tool call on first iteration only for data-related intents
        tc = "auto"
        if iteration == 0 and not skip_tool_forcing:
            tc = "required"

        # For greeting intent with no tools, don't pass tools at all
        call_kwargs: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": messages,
        }
        if active_tools:
            call_kwargs["tools"] = active_tools
            call_kwargs["tool_choice"] = tc

        try:
            response = await async_client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            logger.error("LLM streaming call failed", exc_info=True)
            yield AgentStep(type="answer", content="AI 모델 호출 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
            return

        if response.usage:
            total_tokens += response.usage.total_tokens

        choice = response.choices[0]

        if choice.message.tool_calls:
            messages.append(choice.message.model_dump())

            for tool_call in choice.message.tool_calls:
                tool_name = tool_call.function.name
                tool_args_str = tool_call.function.arguments

                try:
                    tool_input = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_input = {"raw": tool_args_str}

                logger.info("  Tool call: %s(%s)", tool_name, tool_args_str[:200])
                tool_output = await asyncio.to_thread(executor.execute, tool_name, tool_args_str)

                yield AgentStep(
                    type="tool_call",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output,
                )

                tool_result_str = json.dumps(tool_output, ensure_ascii=False, default=str)
                if len(tool_result_str) > 4000:
                    tool_result_str = tool_result_str[:4000] + "... (truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str,
                })

        elif choice.finish_reason == "stop":
            answer = choice.message.content or ""
            yield AgentStep(type="answer", content=answer)
            # Yield mutation/schema info as a final meta step
            if executor.mutations_performed or executor.schema_changed:
                yield AgentStep(
                    type="meta",
                    content=json.dumps({
                        "mutations_performed": executor.mutations_performed,
                        "schema_changed": executor.schema_changed,
                        "mutated_table_ids": list(executor.mutated_table_ids),
                    }),
                )
            return
        else:
            yield AgentStep(type="answer", content=choice.message.content or "분석이 완료되었습니다.")
            if executor.mutations_performed or executor.schema_changed:
                yield AgentStep(
                    type="meta",
                    content=json.dumps({
                        "mutations_performed": executor.mutations_performed,
                        "schema_changed": executor.schema_changed,
                        "mutated_table_ids": list(executor.mutated_table_ids),
                    }),
                )
            return

    yield AgentStep(
        type="answer",
        content="최대 반복 횟수에 도달했습니다. 더 구체적인 질문으로 다시 시도해주세요.",
    )
