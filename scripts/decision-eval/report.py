"""Recompute development scorecards from frozen observations; no provider calls."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from app.eval.golden import load_cases


def probability_metrics(records, cases):
    """Use native probabilities and explicit labels only, excluding optional tools.

    Unlisted tools are not implicitly negative gold. The tool Brier denominator
    consists only of required positives and forbidden negatives. Report its
    support separately; it is not a complete 32-label calibration estimate.
    """
    intent_errors, tool_errors = [], []
    covered_cases = 0
    for record in records:
        if record["status"] != "ok" or record["score"]["fell_back"]:
            continue
        answers = record.get("evidence", {}).get("answers")
        if not answers:
            continue
        case = cases[record["case_id"]]
        probs = answers["intent"].get("probabilities")
        if not probs:
            continue
        covered_cases += 1
        intent_errors.append(sum((value - int(key == case.expected_intent))**2 for key, value in probs.items()))
        for tool in case.expected_tools:
            tool_errors.append((answers[f"tool__{tool}"]["noul"]-1)**2)
        for tool in case.forbidden_tools:
            tool_errors.append(answers[f"tool__{tool}"]["noul"]**2)
    return {
        "native_probability_cases": covered_cases,
        "intent_brier_multiclass": statistics.mean(intent_errors) if intent_errors else None,
        "explicit_tool_brier": statistics.mean(tool_errors) if tool_errors else None,
        "explicit_tool_label_count": len(tool_errors),
        "note": "Uncalibrated development observations; optional and unlisted tool labels excluded; shortcuts have no native probabilities.",
    }


def summarize(run: Path):
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    cases = {c.id: c for c in load_cases(run / "dataset.yaml")}
    records = [json.loads(line) for line in (run / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = defaultdict(list)
    for record in records:
        groups[record["arm"]].append(record)
    arms = {}
    for arm in manifest["arms"]:
        rows = groups[arm]
        scores = [r["score"] for r in rows if r["score"] is not None]
        planned = len(cases)*manifest["repetitions"]
        full = len(scores) == planned
        latency = sorted(s["duration_s"] for s in scores)
        model_latency = sorted(r["score"]["duration_s"] for r in rows
                               if r["score"] and r["status"] == "ok" and not r.get("evidence", {}).get("shortcut")
                               and not r["score"]["fell_back"])
        total_cost = sum(s["cost_usd"] for s in scores) if full and all(s["cost_usd"] is not None for s in scores) else None
        paired_keys = {(r["case_id"], r["repetition"]) for r in rows}
        if len(paired_keys) != len(rows):
            raise ValueError("duplicate case/repetition in saved observations")
        arms[arm] = {
            "planned": planned, "observed": len(scores), "complete": full,
            "errors": sum(bool(s["error"]) for s in scores),
            "degraded": sum(s["fell_back"] for s in scores),
            "passed": sum(s["passed"] for s in scores),
            "primary_passed": sum(s["passed"] and not s["fell_back"] for s in scores),
            "intent_accuracy": statistics.mean(s["intent_correct"] for s in scores) if full else None,
            "mean_case_tool_f1": statistics.mean(s["f1"] for s in scores) if full else None,
            "primary_pass_rate": sum(s["passed"] and not s["fell_back"] for s in scores)/planned if full else None,
            "forbidden_selection_cases": sum(bool(s["violated_tools"]) for s in scores),
            "p50_s": statistics.median(latency) if full else None,
            "p95_s": latency[max(0, math.ceil(.95*len(latency))-1)] if full else None,
            "model_call_p50_s": statistics.median(model_latency) if model_latency else None,
            "total_cost_usd": total_cost,
            "probabilities": probability_metrics(rows, cases),
        }
    return {
        "run_status": manifest["status"], "scope": manifest["scope"],
        "dataset_sha256": manifest["dataset_sha256"], "arms": arms,
        "caution": "Development pilot only. No human-confirmed holdout, worker execution, matched API latency comparison or production adoption decision.",
    }


def markdown(summary):
    lines = ["# DATAEZ decision router development pilot", "", summary["scope"], "",
             "| arm | observed / planned | primary pass | intent accuracy | mean tool F1 | forbidden selection cases | p50 seconds |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    def number(value):
        return f"{value:.3f}" if value is not None else "N/A"
    for arm, s in summary["arms"].items():
        lines.append(f"| {arm} | {s['observed']} / {s['planned']} | {s['primary_passed']} | {number(s['intent_accuracy'])} | {number(s['mean_case_tool_f1'])} | {s['forbidden_selection_cases']} | {number(s['p50_s'])} |")
    lines.extend(["", "Selection is not execution. The worker was not run. Missing costs remain null.", "", summary["caution"], ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = summarize(args.run)
    (args.run / "scorecard.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    md = markdown(summary)
    (args.run / "scorecard.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
