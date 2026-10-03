"""Exercise run artifacts and unavailable denominators with fake providers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import openai

from app.eval import decision_models
from app.eval.decision_models import Decision

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("decision_runner", ROOT / "scripts/decision-eval/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def dataset(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: a\n    question: first\n    expected_intent: general\n  - id: b\n    question: second\n    expected_intent: general\n", encoding="utf-8")
    return path


def test_error_keeps_planned_denominator_and_freezes_sources(tmp_path, monkeypatch):
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=False)
    probe.chat.completions.create.return_value = SimpleNamespace(model="test-model", usage=None)
    monkeypatch.setattr(openai, "OpenAI", Mock(return_value=probe))

    class Router:
        metadata = {"arm": "A0", "model": "fake"}
        def __call__(self, case):
            if case.id == "b":
                raise ValueError("sensitive exception payload must not be persisted")
            return Decision([], "general", {"cost_usd": 0.0})
    monkeypatch.setattr(decision_models, "CurrentRouter", Router)
    out = tmp_path / "run"
    result = runner.main(["--dataset", str(dataset(tmp_path)), "--arms", "current", "--out", str(out)])
    assert result == 2
    summary = json.loads((out / "summary.json").read_text())
    assert summary["current"]["planned"] == summary["current"]["observed"] == 2
    assert summary["current"]["metrics"]["pass_rate"] == .5
    assert summary["current"]["metrics"]["total_cost_usd"] is None
    assert "sensitive exception payload" not in (out / "observations.jsonl").read_text()
    assert (out / "source/api/app/eval/decision_models.py").is_file()


def test_quota_failure_does_not_repeatedly_call_backends(tmp_path, monkeypatch):
    class QuotaError(Exception):
        code = "credit_balance_exhausted"
        status_code = 429
    monkeypatch.setattr(openai, "OpenAI", Mock(side_effect=QuotaError("private payload")))
    construct = Mock(side_effect=AssertionError("backend must not be constructed"))
    monkeypatch.setattr(decision_models, "CurrentRouter", construct)
    monkeypatch.setattr(decision_models, "AtomicNanoRouter", construct)
    out = tmp_path / "unavailable"
    assert runner.main(["--dataset", str(dataset(tmp_path)), "--arms", "current", "atomic", "--out", str(out)]) == 2
    assert construct.call_count == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert manifest["planned_observations"] == 4
    assert manifest["openai_preflight"]["error_code"] == "credit_balance_exhausted"
    assert "private payload" not in (out / "manifest.json").read_text()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["current"]["observed"] == 0 and summary["current"]["planned"] == 2
    assert summary["atomic"]["metrics"] is None
