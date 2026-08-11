"""L1: deterministic scoring of orchestrator routing decisions.

Scores two things the orchestrator is actually responsible for:

  intent accuracy      — exact match against the labelled intent.
  tool-selection F1    — precision and recall over the expected tool set.

Both are deterministic given the model's output, so a change in score is a
change in behaviour, not a change in a judge's opinion. This is the layer that
can gate CI; the LLM-judge layer cannot, because its variance would produce
flapping builds.

Precision matters as much as recall here. The orchestrator exists to *narrow*
the tool space, so selecting all 14 tools would score perfect recall while
defeating the entire design — precision is what catches that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .golden import GoldenCase


@dataclass
class CaseScore:
    case_id: str
    question: str
    expected_intent: str
    actual_intent: str
    expected_tools: list[str]
    actual_tools: list[str]
    tools_mode: str
    optional_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    fell_back: bool = False
    error: str = ""

    @property
    def intent_correct(self) -> bool:
        return self.actual_intent == self.expected_intent

    @property
    def _scored_tools(self) -> list[str]:
        """Selections that count toward precision.

        Optional tools are excluded: they are defensible for this question, so
        choosing one is neither credit nor error. Leaving them in would score
        the agent's documented behaviour as a false positive.
        """
        optional = set(self.optional_tools)
        return [t for t in self.actual_tools if t not in optional]

    @property
    def true_positives(self) -> int:
        return len(set(self.expected_tools) & set(self.actual_tools))

    @property
    def precision(self) -> float:
        scored = self._scored_tools
        if not scored:
            # Selecting nothing is perfect precision only when nothing was
            # expected; otherwise it is a total miss.
            return 1.0 if not self.expected_tools else 0.0
        return self.true_positives / len(scored)

    @property
    def recall(self) -> float:
        if not self.expected_tools:
            return 1.0 if not self.actual_tools else 0.0
        return self.true_positives / len(self.expected_tools)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)

    @property
    def tools_pass(self) -> bool:
        if self.tools_mode == "exact":
            return set(self._scored_tools) == set(self.expected_tools)
        return set(self.expected_tools).issubset(set(self.actual_tools))

    @property
    def passed(self) -> bool:
        return self.intent_correct and self.tools_pass and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "expected_intent": self.expected_intent,
            "actual_intent": self.actual_intent,
            "intent_correct": self.intent_correct,
            "expected_tools": self.expected_tools,
            "actual_tools": self.actual_tools,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "tools_pass": self.tools_pass,
            "passed": self.passed,
            "fell_back": self.fell_back,
            "tags": self.tags,
            "error": self.error,
        }


@dataclass
class RoutingReport:
    scores: list[CaseScore] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.scores)

    @property
    def intent_accuracy(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.intent_correct for s in self.scores) / self.total

    @property
    def macro_f1(self) -> float:
        """Mean per-case F1. Macro, so rare intents are not drowned out."""
        if not self.scores:
            return 0.0
        return sum(s.f1 for s in self.scores) / self.total

    @property
    def pass_rate(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.passed for s in self.scores) / self.total

    @property
    def fallback_rate(self) -> float:
        """Share of cases where routing degraded to the full toolset.

        A silent fallback defeats the orchestrator's purpose, so it is tracked
        as a headline number rather than buried in the per-case detail.
        """
        if not self.scores:
            return 0.0
        return sum(s.fell_back for s in self.scores) / self.total

    def by_tag(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for score in self.scores:
            for tag in score.tags:
                bucket = out.setdefault(tag, {"total": 0, "passed": 0})
                bucket["total"] += 1
                bucket["passed"] += int(score.passed)
        for bucket in out.values():
            bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4)
        return out

    def by_intent(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for score in self.scores:
            bucket = out.setdefault(
                score.expected_intent, {"total": 0, "correct": 0}
            )
            bucket["total"] += 1
            bucket["correct"] += int(score.intent_correct)
        for bucket in out.values():
            bucket["accuracy"] = round(bucket["correct"] / bucket["total"], 4)
        return out

    def failures(self) -> list[CaseScore]:
        return [s for s in self.scores if not s.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "intent_accuracy": round(self.intent_accuracy, 4),
            "tool_macro_f1": round(self.macro_f1, 4),
            "pass_rate": round(self.pass_rate, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "by_intent": self.by_intent(),
            "by_tag": self.by_tag(),
            "cases": [s.to_dict() for s in self.scores],
        }


# A router call takes a question and returns (tools_or_None, intent). None for
# tools means the router fell back to the full toolset.
RouterFn = Callable[[str], tuple[list[str] | None, str]]


def score_case(case: GoldenCase, router: RouterFn) -> CaseScore:
    """Run one golden case through `router` and score the result."""
    try:
        tools, intent = router(case.question)
    except Exception as exc:  # noqa: BLE001 — one bad case must not end the run
        return CaseScore(
            case_id=case.id,
            question=case.question,
            expected_intent=case.expected_intent,
            actual_intent="",
            expected_tools=case.expected_tools,
            actual_tools=[],
            tools_mode=case.tools_mode,
            optional_tools=case.optional_tools,
            tags=case.tags,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )

    return CaseScore(
        case_id=case.id,
        question=case.question,
        expected_intent=case.expected_intent,
        actual_intent=intent,
        expected_tools=case.expected_tools,
        # A fallback selects everything; recording it as such is what makes
        # its precision cost visible instead of hidden behind a None.
        actual_tools=list(tools) if tools is not None else [],
        tools_mode=case.tools_mode,
        optional_tools=case.optional_tools,
        tags=case.tags,
        fell_back=tools is None,
    )


def run_routing_eval(cases: list[GoldenCase], router: RouterFn) -> RoutingReport:
    return RoutingReport(scores=[score_case(c, router) for c in cases])
