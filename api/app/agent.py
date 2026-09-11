"""Core AI Agent loop with OpenAI Function Calling — project-level multi-table."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from .agent_tools import TOOL_SPECS, ToolExecutor
from .config import settings
from .llm_telemetry import ROLE_WORKER, TurnLedger, track_llm_call
from .metrics import agent_iterations, agent_turns_total
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
            if len(output_str) > 3000 and self.tool_name != "search_library_files":
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
    # Every LLM call made for this turn, including the orchestrator's routing
    # call, which the old total_tokens counter never included.
    usage: dict[str, Any] = field(default_factory=dict)

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
            "usage": self.usage,
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


def _select_tools(
    question: str,
    has_attachments: bool = False,
    ledger: TurnLedger | None = None,
    conversation_messages: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str, bool]:
    """Orchestrator LLM을 통해 질문에 필요한 툴과 intent를 반환.

    Returns (tool_specs, intent, degraded). `degraded` marks a turn whose
    routing failed and fell back to the read-only safe set.
    """
    all_tool_names = [t["function"]["name"] for t in TOOL_SPECS]
    result: OrchestratorResult = select_tools_via_orchestrator(
        question, has_attachments, all_tool_names, ledger=ledger, conversation_messages=conversation_messages
    )
    selected = result.tools or []
    if any(word in question for word in ("보관함", "저장소", "파일 찾아", "파일 불러")):
        selected = list(dict.fromkeys([*selected, "search_library_files"]))
    if set(selected) & {"list_ledger_sources", "list_import_history", "inspect_import_review"}:
        selected = list(set(selected) | {"list_ledger_sources", "list_import_history", "inspect_import_review"})
    if "restore_metric" in selected:
        selected = list(dict.fromkeys([*selected, "get_metric_history"]))
    if "draft_cash_entry" in selected:
        selected = list(dict.fromkeys([*selected, "list_cash_entries", "get_cash_entry"]))
    if set(selected) & {"preview_metric", "save_metric", "list_metrics", "set_metric_refresh", "update_metric", "get_metric_history", "restore_metric"}:
        selected = list(set(selected) | {"list_tables", "describe_table", "search_schema", "preview_metric", "list_metrics", "get_metric_history"})
    if set(selected) & {"list_stores", "list_store_tables", "inspect_store_table", "search_store_schema"}:
        selected = list(set(selected) | {"list_stores", "list_store_tables", "inspect_store_table", "search_store_schema", "preview_metric", "list_metrics", "get_metric_history"})
    specs = [t for t in TOOL_SPECS if t["function"]["name"] in selected]
    return specs, result.intent, result.degraded


def _tool_result_content(tool_name: str, output: dict[str, Any]) -> str:
    """Keep history pages valid and navigable inside the model context budget.

    Cutting the JSON at 4,000 characters hid older batches while preserving a
    misleading total. Full evidence stays in AgentStep; details remain available
    through inspect_import_review. Both sync and streaming loops use this view.
    """
    if tool_name in ('list_stores','list_store_tables','inspect_store_table','search_store_schema','search_library_files'):
        return json.dumps(output, ensure_ascii=False, default=str, separators=(',', ':'))
    if tool_name == 'list_metrics' and isinstance(output.get('metrics'), list):
        compact = [{k:v for k,v in m.items() if k != 'definition'} for m in output['metrics']]
        return json.dumps({'metrics':compact,'hint':'변경할 지표의 전체 정의는 get_metric_history로 확인하세요.'},ensure_ascii=False,default=str)
    if tool_name == "preview_metric" and "metric_definition" in output:
        # Full chart/SQL remain in AgentStep and the persisted chart. Give the
        # model valid JSON and explicit sample coverage instead of broken JSON.
        page = {k:v for k,v in output.items() if k not in ('execution', 'data')}
        page['evidence_limits'] = (
            'value/data는 저장 정의의 기간·필터를 적용한 집계값입니다. 여기에 없는 승인/취소 건수나 원인을 '
            '원본 sample_rows에서 추정하지 마세요. 장부 목록/describe_table의 row_count는 전체 장부 행 수이며 '
            '이번 집계의 포함 건수가 아닙니다. 추가 건수가 필요하면 같은 기간·필터의 count를 실제 계산하세요.')
        if isinstance(output.get('data'), list):
            page['total_groups'] = len(output['data'])
            page['data'] = output['data'][:5]
            page['data_is_sample'] = len(output['data']) > len(page['data'])
            page['hint'] = '전체 집계표·SQL은 차트 상세에 있습니다. 표본으로 전체 통계나 추세를 추정하지 마세요.'
        return json.dumps(page, ensure_ascii=False, default=str, separators=(',', ':'))
    if tool_name == "list_import_history" and isinstance(output.get("batches"), list):
        page = {k: v for k, v in output.items() if k != "batches"}
        page["batches"] = []
        page["hint"] = "next_offset이 있으면 같은 출처의 다음 이력을 계속 조회하세요. 특정 파일을 찾기 전 다른 파일로 대신 답하지 마세요. 상세 근거는 inspect_import_review로 조회하세요."

        def encoded():
            return json.dumps(page, ensure_ascii=False, default=str, separators=(",", ":"))

        for batch in output["batches"]:
            summary = batch.get("summary") or {}
            result = batch.get("result") or {}
            compact = {k: batch.get(k) for k in ("id", "filename", "status", "created_at", "committed_at", "review_url")}
            compact["summary"] = {k: summary[k] for k in ("row_count", "counts", "amount", "can_commit") if k in summary}
            compact["result"] = {k: result[k] for k in ("rows_inserted", "duplicates_skipped", "total_row_count", "amount") if k in result}
            if batch.get("error"):
                error = batch["error"]
                compact["error"] = {"code": error.get("code"), "message": str(error.get("message", ""))[:180], "issue_count": len(error.get("issues") or [])}
            page["batches"].append(compact)
            if len(encoded()) > 3600 and len(page["batches"]) > 1:
                page["batches"].pop()
                break
        offset = output.get("offset", 0)
        count = len(page["batches"])
        page["returned_count"] = count
        page["next_offset"] = offset + count if count and offset + count < output.get("total", 0) else None
        return encoded()
    collection = {'get_metric_history': 'revisions', 'list_cash_entries': 'entries'}.get(tool_name)
    if collection and isinstance(output.get(collection), list):
        page = {k:v for k,v in output.items() if k not in (collection, 'metric')}
        if 'metric' in output:
            page['metric'] = {k:output['metric'][k] for k in ('id','title','definition_revision')}
        page[collection] = []
        page['hint'] = 'next_offset이 있으면 해당 offset으로 계속 조회하세요. 이 페이지에 없다는 이유로 전체 이력에 없다고 판단하지 마세요.'
        def encoded_page():
            return json.dumps(page, ensure_ascii=False, default=str, separators=(',',':'))
        for item in output[collection]:
            page[collection].append(item)
            if len(encoded_page()) > 3600 and len(page[collection]) > 1:
                page[collection].pop()
                break
        count = len(page[collection]); offset = output.get('offset', 0)
        page['returned_count'] = count
        page['next_offset'] = offset+count if count and offset+count < output.get('total', 0) else None
        return encoded_page()
    content = json.dumps(output, ensure_ascii=False, default=str)
    return content if len(content) <= 4000 else content[:4000] + "... (truncated)"


def run_agent(
    user_id: str,
    project_id: str,
    project_name: str,
    tables_info: list[dict[str, Any]],
    conversation_messages: list[dict[str, str]],
    question: str,
    attached_files: list[dict[str, Any]] | None = None,
    library_refs: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Run the agent loop with function calling against project tables."""
    if not settings.openai_api_key:
        return AgentResult(
            answer="OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요.",
            steps=[AgentStep(type="answer", content="API key not configured")],
        )

    ledger = TurnLedger()
    has_attachments = bool(attached_files)
    active_tools, intent, degraded = _select_tools(question, has_attachments=has_attachments, ledger=ledger, conversation_messages=conversation_messages)
    logger.info("Orchestrator selected tools=%d, intent=%s: %s", len(active_tools), intent, [t["function"]["name"] for t in active_tools])

    client = get_openai_client()
    executor = ToolExecutor(user_id, project_id, attached_files=attached_files, ledger=ledger, **({"library_refs":library_refs} if library_refs else {}))
    if library_refs:
        from .library_agent import SCOPED_TOOLS
        active_tools = [tool for tool in active_tools if tool["function"]["name"] in SCOPED_TOOLS]
        selected_names = {tool["function"]["name"] for tool in active_tools}
        selected_names |= {"list_tables", "describe_table", "query_data", "cross_query", "generate_chart", "search_documents"}
        if any(ref["project_id"] != project_id for ref in library_refs):
            selected_names |= {"list_stores", "list_store_tables", "inspect_store_table", "preview_metric"}
        active_tools = [tool for tool in TOOL_SPECS if tool["function"]["name"] in selected_names]
        tables_info = executor._tables

    system_prompt = build_system_prompt(
        project_name, tables_info, intent=intent, has_attachments=has_attachments,
    )
    from .library_agent import prompt as library_prompt
    system_prompt += library_prompt(library_refs)
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

    # Skip tool forcing when nothing was selected, and when routing degraded.
    # Forcing a call on a fallback set pushes a greeting into a data tool,
    # contradicting the system prompt's own edge-case rule.
    skip_tool_forcing = not active_tools or degraded

    for iteration in range(settings.agent_max_iterations):
        # Budget guard
        if total_tokens >= settings.agent_max_token_budget:
            logger.warning("Token budget exhausted (%d tokens), stopping agent", total_tokens)
            answer = "토큰 예산이 초과되었습니다. 더 간결한 질문으로 다시 시도해주세요."
            steps.append(AgentStep(type="answer", content=answer))
            agent_turns_total.labels(mode="sync", outcome="budget_exhausted").inc()
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
        if settings.runtime_mode == "serverless":
            call_kwargs["max_completion_tokens"] = 4096
        if active_tools:
            call_kwargs["tools"] = active_tools
            call_kwargs["tool_choice"] = tc

        try:
            with track_llm_call(
                model=settings.openai_model, role=ROLE_WORKER, ledger=ledger
            ) as call:
                response = client.chat.completions.create(**call_kwargs)
                call.record_usage(response.usage)
        except Exception as exc:
            logger.error("LLM call failed", exc_info=True)
            answer = "AI 모델 호출 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            steps.append(AgentStep(type="answer", content=answer))
            agent_turns_total.labels(mode="sync", outcome="llm_error").inc()
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
                if tool_name in ("generate_chart", "preview_metric") and "chart_type" in tool_output:
                    charts.append(tool_output)
                if tool_name in ("query_data", "cross_query") and "data" in tool_output:
                    table_data = tool_output["data"]

                tool_result_str = _tool_result_content(tool_name, tool_output)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str,
                })

        elif choice.finish_reason == "stop":
            answer = choice.message.content or ""
            steps.append(AgentStep(type="answer", content=answer))
            agent_turns_total.labels(mode="sync", outcome="answered").inc()
            break
        else:
            answer = choice.message.content or "분석이 완료되었습니다."
            steps.append(AgentStep(type="answer", content=answer))
            agent_turns_total.labels(mode="sync", outcome="answered").inc()
            break

    if not answer:
        answer = "최대 반복 횟수에 도달했습니다. 더 구체적인 질문으로 다시 시도해주세요."
        steps.append(AgentStep(type="answer", content=answer))
        agent_turns_total.labels(mode="sync", outcome="iterations_exhausted").inc()

    agent_iterations.labels(mode="sync").observe(iteration + 1)
    answer, suggestions = _parse_suggestions(answer)
    usage = ledger.summary()
    logger.info(
        "Agent finished: %d tokens across %d LLM calls, est. $%.5f",
        usage["total_tokens"],
        usage["calls"],
        usage["cost_usd"],
    )
    return AgentResult(
        answer=answer,
        steps=steps,
        charts=charts,
        table_data=table_data,
        suggestions=suggestions,
        mutations_performed=executor.mutations_performed,
        schema_changed=executor.schema_changed,
        mutated_table_ids=executor.mutated_table_ids,
        # Ledger-wide, so routing and worker calls are both counted. The old
        # value silently omitted the orchestrator's call.
        total_tokens=usage["total_tokens"],
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Streaming variants (async generators for SSE)
# ---------------------------------------------------------------------------


def _streaming_meta_step(executor: ToolExecutor, ledger: TurnLedger) -> AgentStep:
    """Final meta frame carrying mutation flags and this turn's LLM usage.

    Usage is emitted unconditionally. The previous version only sent a meta
    frame when a mutation happened, so the streaming endpoint had no token or
    cost figures to persist and always recorded zero.
    """
    return AgentStep(
        type="meta",
        content=json.dumps(
            {
                "mutations_performed": executor.mutations_performed,
                "schema_changed": executor.schema_changed,
                "mutated_table_ids": list(executor.mutated_table_ids),
                "usage": ledger.summary(),
            },
            ensure_ascii=False,
        ),
    )


async def run_agent_streaming(
    user_id: str,
    project_id: str,
    project_name: str,
    tables_info: list[dict[str, Any]],
    conversation_messages: list[dict[str, str]],
    question: str,
    attached_files: list[dict[str, Any]] | None = None,
    library_refs: list[dict[str, Any]] | None = None,
):
    """Async generator that yields AgentStep objects in real-time."""
    if not settings.openai_api_key:
        yield AgentStep(
            type="answer",
            content="OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요.",
        )
        return

    ledger = TurnLedger()
    has_attachments = bool(attached_files)
    active_tools, intent, degraded = await asyncio.to_thread(_select_tools, question, has_attachments=has_attachments, ledger=ledger, conversation_messages=conversation_messages)
    logger.info("Orchestrator selected tools=%d, intent=%s (streaming): %s", len(active_tools), intent, [t["function"]["name"] for t in active_tools])

    async_client = get_async_openai_client()
    executor = ToolExecutor(user_id, project_id, attached_files=attached_files, ledger=ledger, **({"library_refs":library_refs} if library_refs else {}))
    if library_refs:
        from .library_agent import SCOPED_TOOLS
        active_tools = [tool for tool in active_tools if tool["function"]["name"] in SCOPED_TOOLS]
        selected_names = {tool["function"]["name"] for tool in active_tools}
        selected_names |= {"list_tables", "describe_table", "query_data", "cross_query", "generate_chart", "search_documents"}
        if any(ref["project_id"] != project_id for ref in library_refs):
            selected_names |= {"list_stores", "list_store_tables", "inspect_store_table", "preview_metric"}
        active_tools = [tool for tool in TOOL_SPECS if tool["function"]["name"] in selected_names]
        tables_info = executor._tables

    system_prompt = build_system_prompt(
        project_name, tables_info, intent=intent, has_attachments=has_attachments,
    )
    from .library_agent import prompt as library_prompt
    system_prompt += library_prompt(library_refs)
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

    # Skip tool forcing when nothing was selected, and when routing degraded.
    # Forcing a call on a fallback set pushes a greeting into a data tool,
    # contradicting the system prompt's own edge-case rule.
    skip_tool_forcing = not active_tools or degraded
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
        if settings.runtime_mode == "serverless":
            call_kwargs["max_completion_tokens"] = 4096
        if active_tools:
            call_kwargs["tools"] = active_tools
            call_kwargs["tool_choice"] = tc

        # Stream the completion. The previous implementation awaited the whole
        # response before yielding anything, so time-to-first-token equalled
        # full model latency and the "streaming" endpoint only streamed
        # completed tool steps.
        call_kwargs["stream"] = True
        call_kwargs["stream_options"] = {"include_usage": True}

        content_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage = None

        try:
            with track_llm_call(
                model=settings.openai_model, role=ROLE_WORKER, ledger=ledger
            ) as call:
                stream = await async_client.chat.completions.create(**call_kwargs)
                async for chunk in stream:
                    # The usage-bearing chunk carries no choices, which is why
                    # streaming previously reported zero tokens.
                    if getattr(chunk, "usage", None):
                        usage = chunk.usage
                    if not chunk.choices:
                        continue

                    chunk_choice = chunk.choices[0]
                    if chunk_choice.finish_reason:
                        finish_reason = chunk_choice.finish_reason

                    delta = chunk_choice.delta
                    if delta is None:
                        continue

                    if delta.content:
                        content_parts.append(delta.content)
                        yield AgentStep(type="token", content=delta.content)

                    for tc_delta in delta.tool_calls or []:
                        slot = tool_call_parts.setdefault(
                            tc_delta.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        if tc_delta.function:
                            # Both name and arguments arrive in fragments and
                            # must be concatenated, not overwritten.
                            if tc_delta.function.name:
                                slot["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                slot["arguments"] += tc_delta.function.arguments

                call.record_usage(usage)
        except Exception:
            logger.error("LLM streaming call failed", exc_info=True)
            agent_turns_total.labels(mode="streaming", outcome="llm_error").inc()
            yield AgentStep(
                type="error",
                content="AI 모델 호출 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            )
            return

        if usage:
            total_tokens += usage.total_tokens

        assembled_tool_calls = [
            tool_call_parts[index] for index in sorted(tool_call_parts)
        ]
        streamed_content = "".join(content_parts)

        if assembled_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": streamed_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in assembled_tool_calls
                    ],
                }
            )

            for tool_call in assembled_tool_calls:
                tool_name = tool_call["name"]
                tool_args_str = tool_call["arguments"]

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

                tool_result_str = _tool_result_content(tool_name, tool_output)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result_str,
                })

        else:
            # Any finish without tool calls ends the turn. The text has already
            # been streamed token by token; this frame carries the assembled
            # answer so the client can persist it without re-joining deltas.
            placeholder = "" if finish_reason == "stop" else "분석이 완료되었습니다."
            answer = streamed_content or placeholder
            yield AgentStep(type="answer", content=answer)
            agent_iterations.labels(mode="streaming").observe(iteration + 1)
            agent_turns_total.labels(mode="streaming", outcome="answered").inc()
            yield _streaming_meta_step(executor, ledger)
            return

    agent_iterations.labels(mode="streaming").observe(settings.agent_max_iterations)
    agent_turns_total.labels(mode="streaming", outcome="iterations_exhausted").inc()
    yield AgentStep(
        type="answer",
        content="최대 반복 횟수에 도달했습니다. 더 구체적인 질문으로 다시 시도해주세요.",
    )
    yield _streaming_meta_step(executor, ledger)
