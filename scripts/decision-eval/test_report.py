import importlib.util
from pathlib import Path

import pytest

from app.eval.golden import GoldenCase

spec = importlib.util.spec_from_file_location("decision_report", Path(__file__).with_name("report.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_brier_uses_explicit_labels_and_native_probabilities_only():
    case = GoldenCase(id="x", question="q", expected_intent="schema",
                      expected_tools=["list_tables"], forbidden_tools=["delete_rows"],
                      optional_tools=["describe_table"])
    native = {"case_id": "x", "status": "ok", "score": {"fell_back": False}, "evidence": {"answers": {
        "intent": {"probabilities": {"schema": .7, "crud": .1, "analysis": .1, "general": .1}},
        "tool__list_tables": {"noul": .8}, "tool__delete_rows": {"noul": .3},
        "tool__describe_table": {"noul": 1},
    }}}
    hard = {"case_id": "x", "status": "ok", "score": {"fell_back": False}, "evidence": {"raw_decisions": {}}}
    result = module.probability_metrics([native, hard], {"x": case})
    assert result["intent_brier_multiclass"] == pytest.approx(.12)
    assert result["explicit_tool_brier"] == pytest.approx(.065)
    assert result["explicit_tool_label_count"] == 2
    assert result["native_probability_cases"] == 1
