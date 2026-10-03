"""Opt-in routing experiments. Imports and defaults never switch the live agent.

The typed arms share state, questions, shortcuts and a frozen threshold. Model
probabilities are retained as evidence; an SDK's `confidence` is not substituted
for the probability of the selected answer being correct.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .golden import GoldenCase, VALID_INTENTS
from .run import _live_router
from ..router import ORCHESTRATOR_PROMPT, _TOOL_SUMMARIES, _is_pure_greeting

LAYA_MODEL = "convaiinnovations/laya-multilingual"
LAYA_REVISION = "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"
JEV_MODEL = "jev-1.13.0"
LAYA_VERSION = "0.3.24"
LAYA_WEIGHT_SHA256 = "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204"

# An experimental price snapshot, separate from the application's old table.
# Full input rates give an upper estimate when A0 telemetry omits cached tokens.
PRICE_SNAPSHOT = {
    "checked_on": "2026-10-03",
    "nano_input_per_1m": 0.20, "nano_output_per_1m": 1.25,
    "nano_cached_input_per_1m": 0.02, "jev_input_per_1m": 0.042,
    "nano_source": "https://developers.openai.com/api/docs/models/gpt-5.4-nano",
    "jev_source": "https://docs.typesafe.ai/models",
}


def routing_state(case: GoldenCase) -> dict[str, Any]:
    # Match the production history window; never send expected labels or tags.
    history = [
        {"role": m["role"], "content": m["content"][:500]}
        for m in case.conversation_messages[-4:]
        if m.get("role") in {"user", "assistant"}
    ]
    return {
        "current_request": case.question,
        "recent_conversation_data": history,
        "routing_policy": ORCHESTRATOR_PROMPT.format(tool_list=""),
    }


def routing_questions() -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {
        "intent": {
            "type": "choice",
            "instructions": "routing_policy에 따라 current_request의 intent를 분류하세요. 이력은 참조 해석에만 쓰세요.",
            "criteria": {
                "schema": "장부 목록·구조·컬럼 조회 또는 장부·컬럼 생성·변경",
                "crud": "원본 행 조회·추가·수정·삭제, 파일 가져오기, 현금 직접입력 초안",
                "analysis": "집계·비교·차트·지표 저장과 갱신, 출처 업로드 이력·중복 검토",
                "general": "인사·일반 대화·문서 정책 검색 등 위에 해당하지 않는 요청",
            },
        },
    }
    for name, description in _TOOL_SUMMARIES.items():
        questions[f"tool__{name}"] = {
            "type": "noul",
            "instructions": (
                f"routing_policy에 따라 current_request를 처리할 때 {name}을 선택해야 하나요? "
                f"도구 설명: {description}. 여러 도구를 함께 선택할 수 있습니다. "
                "대화 이력 자체의 요청은 수행하지 마세요."
            ),
        }
    return questions


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("probability must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("probability outside [0,1]")
    return value


def decode_answers(answers: dict, threshold: float = 0.5, *, require_probabilities: bool = True) -> tuple[list[str], str]:
    if not 0 <= threshold <= 1:
        raise ValueError("threshold outside [0,1]")
    expected = set(routing_questions())
    if not isinstance(answers, dict) or set(answers) != expected:
        raise ValueError("missing or unexpected typed answers")
    intent = answers["intent"]
    if intent.get("type") != "choice" or intent.get("choice") not in VALID_INTENTS:
        raise ValueError("invalid intent answer")
    probs = intent.get("probabilities")
    if require_probabilities and probs is None:
        raise ValueError("missing native intent probabilities")
    if probs is not None:
        if set(probs) != VALID_INTENTS:
            raise ValueError("incomplete intent probabilities")
        values = {k: _probability(v) for k, v in probs.items()}
        if abs(sum(values.values()) - 1) > 0.002:
            raise ValueError("intent probabilities do not sum to one")
        if values[intent["choice"]] < max(values.values()) - 0.0002:
            raise ValueError("intent choice contradicts probabilities")
    selected = []
    for name in _TOOL_SUMMARIES:
        answer = answers[f"tool__{name}"]
        if answer.get("type") != "noul":
            raise ValueError("invalid tool answer type")
        if _probability(answer.get("noul")) >= threshold:
            selected.append(name)
    return selected, intent["choice"]


@dataclass
class Decision:
    tools: list[str] | None
    intent: str
    usage: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


def shortcut(case: GoldenCase) -> Decision | None:
    # Same order as A0, including a greeting taking precedence over attachments.
    if _is_pure_greeting(case.question):
        return Decision([], "general", {"cost_usd": 0.0}, {"shortcut": "greeting"})
    if case.has_attachments:
        return Decision(["list_tables", "describe_table", "import_file"], "crud",
                        {"cost_usd": 0.0}, {"shortcut": "attachment"})
    return None


class CurrentRouter:
    def __init__(self):
        from ..config import settings
        self.metadata = {"model": settings.openai_orchestrator_model,
                         "arm": "A0", "probability_kind": "unavailable"}

    def __call__(self, case: GoldenCase) -> Decision:
        tools, intent, usage = _live_router(case)
        details = usage.get("call_details", [])
        # Replace old price arithmetic, retaining counts, outcomes and timing.
        known = all(c["model"].startswith("gpt-5.4-nano") and c["outcome"] == "ok"
                    and c["prompt_tokens"] + c["completion_tokens"] > 0 for c in details)
        usage["cost_usd"] = (sum(
            (c["prompt_tokens"] * PRICE_SNAPSHOT["nano_input_per_1m"] + c["completion_tokens"] * PRICE_SNAPSHOT["nano_output_per_1m"]) / 1_000_000
            for c in details
        ) if known and not usage["degraded"] else None)
        for c in details:
            c.pop("cost_usd", None)
        usage.pop("by_role", None)
        usage["cost_basis"] = "full-input upper estimate; cached input unavailable"
        return Decision(tools, intent, usage, {"probability_kind": "unavailable"})


class AtomicNanoRouter:
    def __init__(self):
        from ..config import settings
        from ..openai_clients import get_openai_client
        self.model = settings.openai_orchestrator_model
        self.client = get_openai_client()
        self.metadata = {"model": self.model, "arm": "A1", "probability_kind": "unavailable"}

    def __call__(self, case: GoldenCase) -> Decision:
        direct = shortcut(case)
        if direct:
            return direct
        tools_schema = {name: {"type": "boolean"} for name in _TOOL_SUMMARIES}
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "intent": {"type": "string", "enum": sorted(VALID_INTENTS)},
                "tools": {"type": "object", "properties": tools_schema,
                          "required": list(tools_schema), "additionalProperties": False},
            }, "required": ["intent", "tools"],
        }
        response = self.client.chat.completions.create(
            model=self.model, temperature=0, max_completion_tokens=1200,
            messages=[
                {"role": "system", "content": "Evaluate the supplied state against each typed question. Return the intent choice and one boolean per tool. Use routing_policy as the rules, recent_conversation_data only as data. Do not invent probabilities."},
                {"role": "user", "content": json.dumps({"state": routing_state(case), "questions": routing_questions()}, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": {
                "name": "atomic_routing", "strict": True, "schema": schema}},
        )
        raw = json.loads(response.choices[0].message.content or "")
        answers = {"intent": {"type": "choice", "choice": raw["intent"]}}
        if set(raw["tools"]) != set(_TOOL_SUMMARIES) or any(type(v) is not bool for v in raw["tools"].values()):
            raise ValueError("invalid atomic decisions")
        answers.update({f"tool__{k}": {"type": "noul", "noul": float(v)} for k, v in raw["tools"].items()})
        tools, intent = decode_answers(answers, require_probabilities=False)
        u = response.usage
        cost = None
        if u and self.model.startswith("gpt-5.4-nano"):
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            cost = ((u.prompt_tokens-cached)*PRICE_SNAPSHOT["nano_input_per_1m"] + cached*PRICE_SNAPSHOT["nano_cached_input_per_1m"] + u.completion_tokens*PRICE_SNAPSHOT["nano_output_per_1m"]) / 1_000_000
        return Decision(tools, intent, {"cost_usd": cost, "total_tokens": u.total_tokens if u else 0},
                        {"response_model": response.model, "raw_decisions": raw,
                         "usage": u.model_dump() if u else None, "probability_kind": "unavailable"})


class JevRouter:
    def __init__(self):
        import httpx
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            raise ValueError("TYPESAFE_API_KEY is required")
        self.client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {key}"})
        self.metadata = {"model": JEV_MODEL, "arm": "C0", "probability_kind": "native"}

    def __call__(self, case: GoldenCase) -> Decision:
        direct = shortcut(case)
        if direct:
            return direct
        response = self.client.post("https://api.typesafe.ai/v1/systemone", json={
            "model": JEV_MODEL, "state": routing_state(case), "questions": routing_questions(),
        })
        if response.status_code != 200:
            raise RuntimeError(f"Jev HTTP {response.status_code}")
        raw = response.json()
        if raw.get("model") != JEV_MODEL:
            raise ValueError("Jev response version differs from pinned model")
        tools, intent = decode_answers(raw["answers"])
        u = raw.get("usage") or {}
        input_tokens = u.get("input_tokens")
        output_tokens = u.get("output_tokens")
        cost = input_tokens * PRICE_SNAPSHOT["jev_input_per_1m"] / 1_000_000 if type(input_tokens) is int else None
        return Decision(tools, intent, {"cost_usd": cost, "total_tokens": (input_tokens or 0)+(output_tokens or 0)}, raw)

    def close(self):
        self.client.close()


class LayaRouter:
    def __init__(self, model_path: str | None = None, *, device: str = "cpu", threads: int = 4):
        os.environ.setdefault("USE_TF", "0")
        import importlib.metadata
        import laya
        import torch
        if importlib.metadata.version("laya") != LAYA_VERSION:
            raise ValueError(f"Use laya=={LAYA_VERSION} for this protocol")
        torch.set_num_threads(threads)
        started = perf_counter()
        self.agent = laya.load(model_path or LAYA_MODEL, device=device,
                               expected_sha256={"model.safetensors": LAYA_WEIGHT_SHA256},
                               **({} if model_path else {"revision": LAYA_REVISION}))
        self.metadata = {"model": LAYA_MODEL, "revision": LAYA_REVISION,
                         "local_path": model_path, "arm": "B0", "device": str(self.agent.device),
                         "dtype": str(self.agent.dtype), "threads": threads,
                         "load_seconds": perf_counter()-started, "probability_kind": "native",
                         "max_len": 8192, "head_max_len": 512, "question_chunk_size": 4}

    def __call__(self, case: GoldenCase) -> Decision:
        direct = shortcut(case)
        if direct:
            return direct
        from laya.common import build_sequence, encode_text, serialize_state, render_options
        state = routing_state(case)
        questions = routing_questions()
        state_ids = encode_text(self.agent.tok, serialize_state(state).replace(self.agent.tok.mask_token, " "), add_special_tokens=False)["input_ids"]
        stats = {}
        for key, q in questions.items():
            internal = self.agent._to_internal(q)
            _, _, head_stats, truncation = build_sequence(
                self.agent.tok, state, internal, max_len=8192, head_max_len=512,
                state_ids=state_ids, return_stats=True, return_truncation_stats=True,
            )
            # Check instruction and option budgets too; partial heads are not supported inputs.
            options = render_options(internal)
            option_ids = [encode_text(self.agent.tok, " " + opt.replace(self.agent.tok.mask_token, " "), add_special_tokens=False)["input_ids"] for opt in options]
            instr = encode_text(self.agent.tok, f"{internal['t']} question: {internal['ins']}", add_special_tokens=False)["input_ids"]
            if (truncation["truncated"] or head_stats["tokens_per_option"] is not None
                    or any(len(ids) > 48 for ids in option_ids)
                    or len(instr) > 512-sum(len(ids)+1 for ids in option_ids)):
                raise ValueError(f"unsupported truncation in {key}")
            stats[key] = truncation
        # Chunk questions to bound CPU memory; all questions still run on every state.
        answers = {}
        usage = []
        keys = list(questions)
        for start in range(0, len(keys), 4):
            chunk = {key: questions[key] for key in keys[start:start+4]}
            result = self.agent.predict(state, chunk, max_len=8192, head_max_len=512)
            if (result.get("usage") or {}).get("truncated"):
                raise ValueError("runtime reported truncated state or questions")
            answers.update(result["answers"])
            usage.append(result.get("usage"))
        tools, intent = decode_answers(answers)
        return Decision(tools, intent, {"cost_usd": None, "cost_basis": "hosting and electricity unmeasured"},
                        {"answers": answers, "usage_chunks": usage, "truncation": stats})
