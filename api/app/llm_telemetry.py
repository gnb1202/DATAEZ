"""Per-call and per-turn accounting for LLM usage.

Token counts were previously computed inside the agent loop and then
discarded: the streaming path never surfaced them, nothing was persisted,
and the orchestrator's own call was never counted at all — so the reported
total understated real spend on every turn.

`TurnLedger` accumulates every call made while answering one user message,
including the routing call and any embeddings, so cost can be attributed
per conversation rather than guessed.
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .llm_cost import estimate_cost_usd, is_priced
from .metrics import (
    llm_call_duration_seconds,
    llm_calls_total,
    llm_cost_usd_total,
    llm_tokens_total,
)

logger = logging.getLogger(__name__)

# Call sites, not model names: the same model can serve several roles and
# the interesting question is which stage of the pipeline spends the money.
ROLE_ORCHESTRATOR = "orchestrator"
ROLE_WORKER = "worker"
ROLE_JUDGE = "judge"
ROLE_EMBEDDING = "embedding"


@dataclass
class LlmCallRecord:
    model: str
    role: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    outcome: str = "ok"

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TurnLedger:
    """Accumulates every LLM call made while answering one user message."""

    calls: list[LlmCallRecord] = field(default_factory=list)

    def add(self, record: LlmCallRecord) -> None:
        self.calls.append(record)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def by_role(self) -> dict[str, dict[str, Any]]:
        """Token and cost split per pipeline stage."""
        out: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            bucket = out.setdefault(c.role, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            bucket["calls"] += 1
            bucket["tokens"] += c.total_tokens
            bucket["cost_usd"] += c.cost_usd
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "calls": len(self.calls),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "by_role": {
                role: {**v, "cost_usd": round(v["cost_usd"], 6)}
                for role, v in self.by_role().items()
            },
        }


def _as_token_count(value: Any) -> int:
    """Coerce a usage field to a non-negative int.

    Token counts feed metric arithmetic, so anything the SDK hands back that
    is not an integer is treated as "unknown" (0) rather than propagated into
    a counter, where it would raise at observation time.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


class _CallTracker:
    """Handle yielded by `track_llm_call` for reporting usage back."""

    def __init__(self, model: str, role: str) -> None:
        self.record = LlmCallRecord(model=model, role=role)

    def record_usage(self, usage: Any) -> None:
        """Accept an OpenAI `usage` object (or None for a streamed call)."""
        if usage is None:
            return
        self.record.prompt_tokens = _as_token_count(getattr(usage, "prompt_tokens", 0))
        self.record.completion_tokens = _as_token_count(
            getattr(usage, "completion_tokens", 0)
        )

    def record_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.record.prompt_tokens = _as_token_count(prompt_tokens)
        self.record.completion_tokens = _as_token_count(completion_tokens)


@contextmanager
def track_llm_call(
    model: str,
    role: str,
    ledger: TurnLedger | None = None,
) -> Iterator[_CallTracker]:
    """Time one LLM call, emit metrics, and append it to `ledger`.

    Exceptions are recorded as an `error` outcome and re-raised — callers
    keep their own error handling, this only makes failures countable.
    """
    tracker = _CallTracker(model, role)
    started = time.monotonic()
    try:
        yield tracker
    except Exception:
        tracker.record.outcome = "error"
        raise
    finally:
        rec = tracker.record
        rec.duration_s = time.monotonic() - started
        rec.cost_usd = estimate_cost_usd(model, rec.prompt_tokens, rec.completion_tokens)

        labels = {"model": model, "role": role}
        llm_calls_total.labels(**labels, outcome=rec.outcome).inc()
        llm_call_duration_seconds.labels(**labels).observe(rec.duration_s)
        if rec.prompt_tokens:
            llm_tokens_total.labels(**labels, kind="prompt").inc(rec.prompt_tokens)
        if rec.completion_tokens:
            llm_tokens_total.labels(**labels, kind="completion").inc(rec.completion_tokens)
        if rec.cost_usd:
            llm_cost_usd_total.labels(**labels).inc(rec.cost_usd)
        elif rec.total_tokens and not is_priced(model):
            # Spend exists but no pricing row covers it; surface the gap
            # rather than silently reporting a $0 turn.
            logger.warning(
                "No pricing configured for model %r — %d tokens counted at $0",
                model,
                rec.total_tokens,
            )

        if ledger is not None:
            ledger.add(rec)
