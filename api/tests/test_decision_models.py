"""Tests for experimental contracts, without optional Laya or provider calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.eval.decision_models import (
    AtomicNanoRouter, CurrentRouter, JevRouter, decode_answers,
    routing_questions, routing_state, shortcut,
)
from app.eval.golden import GoldenCase, load_cases, validate_cases
from app.eval.routing import score_case, run_routing_eval
from app.router import expand_tool_selection


def answers():
    result = {key: {"type": "noul", "noul": 0.01} for key in routing_questions()}
    result["intent"] = {"type": "choice", "choice": "schema", "probabilities": {
        "schema": 0.7, "crud": 0.1, "analysis": 0.1, "general": 0.1}}
    return result


def test_multilabel_threshold_and_intent():
    data = answers()
    data["tool__list_tables"]["noul"] = 0.5
    data["tool__describe_table"]["noul"] = 0.8
    assert decode_answers(data) == (["list_tables", "describe_table"], "schema")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.1, True, "0.8", None])
def test_bad_probability_is_a_failed_observation(value):
    data = answers()
    data["tool__delete_rows"]["noul"] = value
    with pytest.raises(ValueError):
        decode_answers(data)


def test_partial_response_cannot_silently_drop_a_tool():
    data = answers()
    del data["tool__delete_rows"]
    with pytest.raises(ValueError):
        decode_answers(data)


def test_native_answer_requires_probabilities_but_hard_atomic_answer_does_not():
    data = answers()
    del data["intent"]["probabilities"]
    with pytest.raises(ValueError, match="missing native"):
        decode_answers(data)
    assert decode_answers(data, require_probabilities=False)[1] == "schema"


def test_choice_confidence_is_not_used_as_correctness_probability():
    data = answers()
    data["intent"]["confidence"] = 0.99
    data["intent"]["probabilities"]["schema"] = 0.1
    with pytest.raises(ValueError, match="sum to one"):
        decode_answers(data)


def test_expected_labels_never_reach_model_state():
    case = GoldenCase(id="SECRET_LABEL", question="그거 보여줘", expected_intent="schema",
                      tags=["SECRET_TAG"], notes="SECRET_NOTE", conversation_messages=[
                          {"role": "user", "content": "x"*900} for _ in range(6)])
    state = routing_state(case)
    serialized = json.dumps(state)
    assert "SECRET" not in serialized
    assert len(state["recent_conversation_data"]) == 4
    assert len(state["recent_conversation_data"][0]["content"]) == 500


def test_common_shortcuts_match_current_order():
    case = GoldenCase(id="g", question="안녕하세요", expected_intent="general", has_attachments=True)
    assert shortcut(case).tools == []
    case.question = "첨부한 파일 가져와줘"
    assert shortcut(case).tools == ["list_tables", "describe_table", "import_file"]
    assert shortcut(case).usage["cost_usd"] == 0


def test_degraded_explicit_list_is_counted_as_fallback():
    case = GoldenCase(id="f", question="q", expected_intent="general")
    s = score_case(case, lambda _: (["list_tables"], "general", {"degraded": True}))
    assert s.fell_back


def test_context_is_passed_through_case_aware_runner():
    case = GoldenCase(id="c", question="그것", expected_intent="crud", has_attachments=True,
                      conversation_messages=[{"role": "user", "content": "이 파일"}])
    observed = []
    def router(value):
        observed.append(value)
        return [], "crud"
    assert score_case(case, router, case_aware=True).passed
    assert observed[0].has_attachments and observed[0].conversation_messages


def test_partial_cost_remains_unknown_and_exception_keeps_denominator():
    cases = [GoldenCase(id=str(i), question=str(i), expected_intent="general") for i in range(3)]
    def router(question):
        if question == "2":
            raise ValueError("transport")
        return [], "general", {"cost_usd": 0.1}
    report = run_routing_eval(cases, router)
    assert report.total == 3
    assert report.pass_rate == pytest.approx(2/3)
    assert report.total_cost_usd is None
    assert report.scores[-1].duration_s >= 0


def test_empty_gold_with_optional_selection_and_duplicate_selection():
    case = GoldenCase(id="o", question="q", expected_intent="schema", optional_tools=["list_tables"])
    score = score_case(case, lambda _: (["list_tables"], "schema"))
    assert score.f1 == 1
    case.expected_tools = ["query_data"]
    score = score_case(case, lambda _: (["query_data", "query_data"], "schema"))
    assert score.f1 == 1


def test_family_cannot_leak_into_test_split():
    from app.agent_tools import TOOL_SPECS
    cases = [GoldenCase(id=str(i), question="q", expected_intent="general", family_id="same",
                        split=split) for i, split in enumerate(["development", "test"])]
    assert any("leaks" in p for p in validate_cases(cases, {t['function']['name'] for t in TOOL_SPECS}))


def test_pilot_is_development_and_contains_real_context():
    from app.agent_tools import TOOL_SPECS
    cases = load_cases(Path(__file__).resolve().parents[2] / "samples/decision-routing-v1/pilot.yaml")
    assert len(cases) == 12
    assert all(c.split == "development" and c.label_status == "codex-reviewed" for c in cases)
    assert validate_cases(cases, {t['function']['name'] for t in TOOL_SPECS}) == []
    assert any(c.has_attachments for c in cases) and any(c.conversation_messages for c in cases)


def test_effective_dependency_order_matches_existing_worker_policy():
    # Multi-store expansion comes after metric expansion in the existing agent.
    assert expand_tool_selection("두 가게 합산", ["list_stores"]) == {
        "list_stores", "list_store_tables", "inspect_store_table", "search_store_schema",
        "preview_metric", "list_metrics", "get_metric_history"}
    assert {"draft_cash_entry", "list_cash_entries", "get_cash_entry"} == expand_tool_selection("현금 초안", ["draft_cash_entry"])


def test_jev_key_missing_fails_preflight(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        JevRouter()


def test_jev_pinned_payload_and_price(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "unit-test-only")
    router = JevRouter()
    router.client.close()
    router.client = Mock()
    router.client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {
        "model": "jev-1.13.0", "answers": answers(), "usage": {"input_tokens": 1000, "output_tokens": 200}})
    decision = router(GoldenCase(id="j", question="장부 이름 목록", expected_intent="schema"))
    assert decision.usage["cost_usd"] == pytest.approx(0.000042)
    assert router.client.post.call_args.kwargs["json"]["model"] == "jev-1.13.0"
    assert "expected_intent" not in json.dumps(router.client.post.call_args.kwargs)


def test_atomic_nano_retains_hard_decisions_without_claiming_probabilities():
    router = AtomicNanoRouter()
    from app.router import _TOOL_SUMMARIES
    raw = {"intent": "schema", "tools": {k: k == "list_tables" for k in _TOOL_SUMMARIES}}
    router.client = Mock()
    router.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)))], usage=None,
        model="gpt-5.4-nano-snapshot")
    decision = router(GoldenCase(id="a", question="장부 목록 보여줘", expected_intent="schema"))
    assert decision.tools == ["list_tables"]
    assert decision.evidence["probability_kind"] == "unavailable"
    assert decision.usage["cost_usd"] is None


def test_current_price_snapshot_replaces_legacy_table(monkeypatch):
    import app.eval.decision_models as module
    monkeypatch.setattr(module, "_live_router", lambda _: (["list_tables"], "schema", {
        "degraded": False, "cost_usd": 0.00009,
        "call_details": [{"model": "gpt-5.4-nano", "outcome": "ok", "prompt_tokens": 1000,
                          "completion_tokens": 100, "cost_usd": 0.00009}]}))
    decision = CurrentRouter()(GoldenCase(id="p", question="목록", expected_intent="schema"))
    assert decision.usage["cost_usd"] == pytest.approx(0.000325)
    assert "cost_usd" not in decision.usage["call_details"][0]


def test_legacy_live_runner_missing_usage_is_unknown_and_replays_context(monkeypatch):
    import app.router as router
    from app.eval.run import _live_router
    from app.llm_telemetry import LlmCallRecord
    seen = {}
    def fake(question, attachments, all_names, *, ledger, conversation_messages):
        seen.update(attachments=attachments, history=conversation_messages)
        ledger.add(LlmCallRecord(model="gpt-5.4-nano", role="orchestrator"))
        return router.OrchestratorResult(["query_data"], "crud")
    monkeypatch.setattr(router, "select_tools_via_orchestrator", fake)
    case = GoldenCase(id="context", question="다시 보여줘", expected_intent="crud", has_attachments=True,
                      conversation_messages=[{"role": "user", "content": "방금 파일"}])
    _, _, usage = _live_router(case)
    assert usage["cost_usd"] is None
    assert seen["attachments"] is True and seen["history"] == case.conversation_messages
