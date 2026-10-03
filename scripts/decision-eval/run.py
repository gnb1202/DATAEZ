"""Freeze inputs, interleave opt-in routers, and checkpoint every observation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "samples/decision-routing-v1/pilot.yaml")
    parser.add_argument("--arms", nargs="+", choices=["current", "atomic", "laya", "jev"], default=["current", "atomic", "laya"])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--laya-path", type=str)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path, help="new run directory; must not already exist")
    args = parser.parse_args(argv)
    if args.repetitions < 1 or args.threads < 1 or len(set(args.arms)) != len(args.arms):
        parser.error("positive repetitions/threads and unique arms required")
    from dotenv import load_dotenv
    # Process env wins; local settings override the root file without printing keys.
    load_dotenv(ROOT / ".env.local", override=False)
    load_dotenv(ROOT / ".env", override=False)
    if args.validate_only or not set(args.arms) & {"current", "atomic"}:
        os.environ.setdefault("OPENAI_API_KEY", "offline-validation-only")
        os.environ.setdefault("JWT_SECRET_KEY", "offline-validation-secret")
    from app.agent_tools import TOOL_SPECS
    from app.eval.golden import load_cases, validate_cases
    from app.eval.routing import RoutingReport, score_case
    from app.eval.decision_models import (
        AtomicNanoRouter, CurrentRouter, JevRouter, LayaRouter,
        LAYA_REVISION, PRICE_SNAPSHOT, routing_questions,
    )
    from app.router import expand_tool_selection
    cases = load_cases(args.dataset)
    problems = validate_cases(cases, {t["function"]["name"] for t in TOOL_SPECS})
    if not cases or problems:
        raise ValueError(f"Invalid dataset: {problems or ['empty']}")
    if args.validate_only:
        print(f"Valid: {len(cases)} cases; {len(routing_questions())} typed questions; no model calls")
        return 0
    out = args.out or ROOT / ".local-test/decision-model-eval/runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    versions = {}
    for package in ["openai", "httpx", "laya", "torch", "transformers", "huggingface-hub", "numpy"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    schedule = [(case.id, rep, arm) for rep in range(args.repetitions) for case in cases for arm in args.arms]
    random.Random(args.seed).shuffle(schedule)
    source_files = [ROOT / "scripts/decision-eval/run.py", *sorted((ROOT / "api/app/eval").glob("*.py")), ROOT / "api/app/router.py"]
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(), "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"), "dirty": bool(git("status", "--porcelain")),
        "code_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in source_files},
        "dataset_sha256": digest(args.dataset.read_bytes()), "dataset": str(args.dataset),
        "seed": args.seed, "repetitions": args.repetitions, "arms": args.arms,
        "schedule": schedule, "planned_observations": len(schedule), "threshold": 0.5,
        "python": sys.version, "platform": platform.platform(), "packages": versions,
        "price_snapshot": PRICE_SNAPSHOT, "laya_revision": LAYA_REVISION,
        "scope": "router-only development pilot; no database writes or worker episodes",
        "labels": "Codex-reviewed development labels, not human-confirmed holdout",
        "backend_setup": {}, "status": "prepared",
    }
    write_json(out / "manifest.json", manifest)
    # Freeze the exact bytes before loading a model or calling a provider.
    (out / "dataset.yaml").write_bytes(args.dataset.read_bytes())
    write_json(out / "questions.json", routing_questions())
    for source in source_files:
        snapshot = out / "source" / source.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(source.read_bytes())
    constructors = {"current": CurrentRouter, "atomic": AtomicNanoRouter, "jev": JevRouter,
                    "laya": lambda: LayaRouter(args.laya_path, device=args.device, threads=args.threads)}
    routers = {}
    openai_preflight_error = None
    if set(args.arms) & {"current", "atomic"}:
        # Check billing/access once. Authentication alone does not prove that a
        # key has credits; do not repeat known account failures across every case.
        from app.config import settings
        from openai import OpenAI
        manifest["openai_preflight"] = {"status": "checking", "purpose": "access/credit probe; excluded from scored cases"}
        try:
            with OpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=30) as client:
                probe = client.chat.completions.create(model=settings.openai_orchestrator_model,
                    messages=[{"role": "user", "content": "Reply OK"}], max_completion_tokens=1)
                manifest["openai_preflight"] = {"status": "ready", "model": probe.model,
                    "usage": probe.usage.model_dump() if probe.usage else None,
                    "note": "Separate setup usage; not included in routing case costs"}
        except Exception as exc:
            openai_preflight_error = type(exc).__name__
            manifest["openai_preflight"] = {"status": "unavailable", "error_type": openai_preflight_error,
                "error_code": getattr(exc, "code", None), "http_status": getattr(exc, "status_code", None)}
        write_json(out / "manifest.json", manifest)
    for arm in args.arms:
        print(f"Preparing {arm}...", flush=True)
        if arm in {"current", "atomic"} and openai_preflight_error:
            manifest["backend_setup"][arm] = {"status": "unavailable", "error_type": openai_preflight_error}
            write_json(out / "manifest.json", manifest)
            continue
        try:
            router = constructors[arm]()
            routers[arm] = router
            manifest["backend_setup"][arm] = {"status": "ready", **router.metadata}
            if arm == "laya":
                # A complete, separate warmup request; timing excludes model load/warmup.
                from app.eval.golden import GoldenCase
                started = perf_counter()
                router(GoldenCase(id="warmup", question="매출 합계를 계산해주세요", expected_intent="analysis"))
                manifest["backend_setup"][arm]["warmup_seconds"] = perf_counter()-started
        except Exception as exc:
            routers.pop(arm, None)
            # No exception payloads: providers can echo sensitive request details.
            manifest["backend_setup"][arm] = {"status": "unavailable", "error_type": type(exc).__name__}
            print(f"Unavailable: {arm} ({type(exc).__name__})", flush=True)
        write_json(out / "manifest.json", manifest)
    by_id = {c.id: c for c in cases}
    scores = {arm: [] for arm in args.arms}
    manifest["status"] = "running"
    write_json(out / "manifest.json", manifest)
    records = []
    try:
        with (out / "observations.jsonl").open("x", encoding="utf-8") as stream:
            for case_id, rep, arm in schedule:
                if arm not in routers:
                    record = {"case_id": case_id, "repetition": rep, "arm": arm, "status": "unavailable", "score": None}
                else:
                    evidence = {}
                    def call(case):
                        try:
                            decision = routers[arm](case)
                        except Exception as exc:
                            raise RuntimeError(type(exc).__name__) from None
                        evidence.update(decision.evidence)
                        evidence["accounting"] = decision.usage
                        return decision.tools, decision.intent, decision.usage
                    score = score_case(by_id[case_id], call, case_aware=True)
                    scores[arm].append(score)
                    record = {
                        "case_id": case_id, "family_id": by_id[case_id].family_id or case_id,
                        "repetition": rep, "arm": arm, "status": "error" if score.error else "ok",
                        "score": score.to_dict(), "evidence": evidence,
                        "raw_tools": score.actual_tools, "worker_executed_tools": None,
                        "effective_tools_before_scope": sorted(expand_tool_selection(by_id[case_id].question, score.actual_tools)) if not score.error else None,
                        "worker_note": "not run; selection is not an execution violation",
                    }
                records.append(record)
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+"\n")
                stream.flush()
                print(f"[{len(records)}/{len(schedule)}] {arm} {case_id}: {record['status']}" +
                      (f" pass={score.passed} {score.duration_s:.2f}s" if record["score"] else ""), flush=True)
    finally:
        for router in routers.values():
            if hasattr(router, "close"):
                router.close()
    summaries = {}
    for arm in args.arms:
        report = RoutingReport(scores[arm])
        latencies = sorted(s.duration_s for s in scores[arm])
        summaries[arm] = {
            "status": manifest["backend_setup"][arm]["status"],
            "planned": len(cases)*args.repetitions, "observed": report.total,
            "metrics": report.to_dict() if arm in routers else None,
            "p50_s": statistics.median(latencies) if latencies else None,
            "p95_s": latencies[max(0, math.ceil(0.95*len(latencies))-1)] if latencies else None,
            "forbidden_selection_cases": sum(bool(s.violated_tools) for s in scores[arm]),
            "errors": sum(bool(s.error) for s in scores[arm]),
        }
    complete = all(arm in routers for arm in args.arms) and len(records) == len(schedule)
    manifest.update(status="complete" if complete else "incomplete", finished_at=datetime.now(timezone.utc).isoformat(), observed=len(records))
    write_json(out / "manifest.json", manifest)
    write_json(out / "summary.json", summaries)
    print(f"Report: {out}", flush=True)
    return 0 if complete and not any(s["errors"] for s in summaries.values()) else 2

if __name__ == "__main__":
    raise SystemExit(main())
