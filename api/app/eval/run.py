"""CLI entry point for the evaluation suite.

    python -m app.eval.run --validate-only          # no API calls, CI-safe
    python -m app.eval.run                          # live run, needs a key
    python -m app.eval.run --out eval-report.md

`--validate-only` checks that every golden case is well-formed without calling
a model, which is what CI runs by default. The live run costs one orchestrator
call per case and is gated on thresholds so it can fail a build deliberately.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .golden import GOLDEN_DIR, load_cases, validate_cases
from .report import check_gates, routing_json, routing_markdown, summary_line
from .routing import run_routing_eval

# Deliberately conservative starting gates. They exist to catch regressions,
# not to certify quality — tighten them as the routing layer improves.
DEFAULT_THRESHOLDS = {
    "intent_accuracy": 0.90,
    "tool_macro_f1": 0.85,
    "max_fallback_rate": 0.05,
}


def _known_tool_names() -> set[str]:
    from ..agent_tools import TOOL_SPECS

    return {spec["function"]["name"] for spec in TOOL_SPECS}


def _live_router(question: str) -> tuple[list[str] | None, str]:
    """Call the real orchestrator for one question."""
    from ..agent_tools import TOOL_SPECS
    from ..router import select_tools_via_orchestrator

    all_names = [spec["function"]["name"] for spec in TOOL_SPECS]
    result = select_tools_via_orchestrator(question, False, all_names)
    return result.tools, result.intent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DATAEZ evaluation suite")
    parser.add_argument(
        "--golden", type=Path, default=GOLDEN_DIR, help="golden file or directory"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the dataset without calling any model",
    )
    parser.add_argument("--out", type=Path, help="write the Markdown scorecard here")
    parser.add_argument("--json-out", type=Path, help="write the full JSON report here")
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="report scores but always exit 0",
    )
    args = parser.parse_args(argv)

    known_tools = _known_tool_names()
    cases = load_cases(args.golden)
    if not cases:
        print(f"No golden cases found in {args.golden}", file=sys.stderr)
        return 1

    problems = validate_cases(cases, known_tools)
    if problems:
        print(f"Golden dataset has {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"Golden dataset OK: {len(cases)} cases, {len(known_tools)} known tools")
    if args.validate_only:
        return 0

    report = run_routing_eval(cases, _live_router)
    markdown = routing_markdown(report, DEFAULT_THRESHOLDS)
    print(markdown)

    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
    if args.json_out:
        args.json_out.write_text(routing_json(report), encoding="utf-8")

    print(json.dumps(summary_line(report), ensure_ascii=False))

    passed, failures = check_gates(report, DEFAULT_THRESHOLDS)
    if not passed:
        for failure in failures:
            print(f"GATE FAILED: {failure}", file=sys.stderr)
        return 0 if args.no_gate else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
