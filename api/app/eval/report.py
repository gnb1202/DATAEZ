"""Scorecard rendering for evaluation runs.

Markdown so the output can be pasted into a PR body or a README, JSON so runs
can be diffed across commits.
"""

from __future__ import annotations

import json
from typing import Any

from .routing import RoutingReport


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def routing_markdown(report: RoutingReport, thresholds: dict[str, float] | None = None) -> str:
    """Render a routing report as a Markdown scorecard."""
    thresholds = thresholds or {}
    lines: list[str] = []

    lines.append("## L1 Routing Scorecard\n")
    lines.append(f"- cases: **{report.total}**")
    lines.append(f"- intent accuracy: **{_pct(report.intent_accuracy)}**")
    lines.append(f"- tool macro-F1: **{report.macro_f1:.3f}**")
    lines.append(f"- full pass rate: **{_pct(report.pass_rate)}**")
    lines.append(f"- routing fallback rate: **{_pct(report.fallback_rate)}**")
    if report.total_tokens:
        # A routing score without its price cannot settle a model choice —
        # the orchestrator exists to spend less than the loop it feeds.
        lines.append(f"- routing tokens: **{report.total_tokens:,}**")
        lines.append(
            f"- routing cost: **${report.total_cost_usd:.5f}** "
            f"(${report.cost_per_case_usd:.7f}/case)"
        )
    lines.append("")

    if thresholds:
        lines.append("### Gates\n")
        lines.append("| gate | threshold | actual | result |")
        lines.append("|---|---|---|---|")
        for name, actual, key in (
            ("intent accuracy", report.intent_accuracy, "intent_accuracy"),
            ("tool macro-F1", report.macro_f1, "tool_macro_f1"),
            ("fallback rate (max)", report.fallback_rate, "max_fallback_rate"),
        ):
            if key not in thresholds:
                continue
            limit = thresholds[key]
            ok = actual <= limit if key.startswith("max_") else actual >= limit
            lines.append(
                f"| {name} | {limit:.3f} | {actual:.3f} | {'PASS' if ok else 'FAIL'} |"
            )
        lines.append("")

    lines.append("### By intent\n")
    lines.append("| intent | cases | accuracy |")
    lines.append("|---|---|---|")
    for intent, stats in sorted(report.by_intent().items()):
        lines.append(f"| {intent} | {stats['total']} | {_pct(stats['accuracy'])} |")
    lines.append("")

    lines.append("### By tag\n")
    lines.append("| tag | cases | pass rate |")
    lines.append("|---|---|---|")
    for tag, stats in sorted(report.by_tag().items()):
        lines.append(f"| {tag} | {stats['total']} | {_pct(stats['pass_rate'])} |")
    lines.append("")

    failures = report.failures()
    if failures:
        lines.append(f"### Failures ({len(failures)})\n")
        lines.append("| case | question | expected | actual |")
        lines.append("|---|---|---|---|")
        for score in failures:
            expected = f"{score.expected_intent} / {score.expected_tools or '[]'}"
            actual = f"{score.actual_intent or '—'} / {score.actual_tools or '[]'}"
            if score.fell_back:
                actual += " (fallback)"
            if score.error:
                actual = f"ERROR {score.error}"
            question = score.question.replace("|", "\\|")
            lines.append(f"| {score.case_id} | {question} | {expected} | {actual} |")
        lines.append("")

    return "\n".join(lines)


def check_gates(
    report: RoutingReport, thresholds: dict[str, float]
) -> tuple[bool, list[str]]:
    """Evaluate CI gates. Returns (passed, failure messages)."""
    failures: list[str] = []

    minimum = thresholds.get("intent_accuracy")
    if minimum is not None and report.intent_accuracy < minimum:
        failures.append(
            f"intent accuracy {report.intent_accuracy:.3f} < required {minimum:.3f}"
        )

    minimum = thresholds.get("tool_macro_f1")
    if minimum is not None and report.macro_f1 < minimum:
        failures.append(
            f"tool macro-F1 {report.macro_f1:.3f} < required {minimum:.3f}"
        )

    maximum = thresholds.get("max_fallback_rate")
    if maximum is not None and report.fallback_rate > maximum:
        failures.append(
            f"routing fallback rate {report.fallback_rate:.3f} > allowed {maximum:.3f}"
        )

    return (not failures), failures


def routing_json(report: RoutingReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def summary_line(report: RoutingReport) -> dict[str, Any]:
    """Compact record for tracking scores across commits."""
    return {
        "total": report.total,
        "intent_accuracy": round(report.intent_accuracy, 4),
        "tool_macro_f1": round(report.macro_f1, 4),
        "pass_rate": round(report.pass_rate, 4),
        "fallback_rate": round(report.fallback_rate, 4),
    }
