"""Tests for the L1 routing evaluation harness.

The scorer is the thing CI trusts, so it is tested against hand-computed
values rather than against itself.
"""

import pytest

from app.agent_tools import TOOL_SPECS
from app.eval.golden import GoldenCase, load_cases, validate_cases
from app.eval.report import check_gates, routing_markdown
from app.eval.routing import CaseScore, run_routing_eval, score_case

KNOWN_TOOLS = {spec["function"]["name"] for spec in TOOL_SPECS}


def _score(expected_tools, actual_tools, mode="subset", expected_intent="crud",
           actual_intent="crud", fell_back=False):
    return CaseScore(
        case_id="t", question="q",
        expected_intent=expected_intent, actual_intent=actual_intent,
        expected_tools=expected_tools, actual_tools=actual_tools,
        tools_mode=mode, fell_back=fell_back,
    )


class TestGoldenDataset:
    def test_shipped_dataset_is_valid(self):
        """Every shipped case must reference real intents and real tools."""
        cases = load_cases()
        assert cases, "golden dataset is empty"
        assert validate_cases(cases, KNOWN_TOOLS) == []

    def test_dataset_covers_every_intent(self):
        cases = load_cases()
        covered = {c.expected_intent for c in cases}
        assert covered == {"schema", "crud", "analysis", "general"}

    def test_dataset_includes_adversarial_cases(self):
        """Injection and ambiguity cases are the ones a keyword filter fails."""
        tags = {tag for case in load_cases() for tag in case.tags}
        assert "injection" in tags
        assert "greeting" in tags

    def test_unknown_tool_name_is_rejected(self):
        bad = GoldenCase(id="x", question="q", expected_intent="crud",
                         expected_tools=["not_a_real_tool"])
        assert bad.validate(KNOWN_TOOLS)

    def test_unknown_intent_is_rejected(self):
        bad = GoldenCase(id="x", question="q", expected_intent="nonsense")
        assert bad.validate(KNOWN_TOOLS)

    def test_duplicate_ids_are_rejected(self):
        dupes = [
            GoldenCase(id="same", question="a", expected_intent="crud"),
            GoldenCase(id="same", question="b", expected_intent="crud"),
        ]
        assert any("duplicate" in p for p in validate_cases(dupes, KNOWN_TOOLS))


class TestScoring:
    def test_perfect_selection(self):
        s = _score(["query_data"], ["query_data"])
        assert s.precision == 1.0 and s.recall == 1.0 and s.f1 == 1.0
        assert s.passed

    def test_extra_tools_cost_precision_not_recall(self):
        """Selecting everything must not look like success."""
        s = _score(["query_data"], ["query_data", "delete_rows", "alter_table"])
        assert s.recall == 1.0
        assert s.precision == pytest.approx(1 / 3)
        assert s.f1 == pytest.approx(0.5)

    def test_missing_tool_costs_recall(self):
        s = _score(["query_data", "generate_chart"], ["query_data"])
        assert s.precision == 1.0
        assert s.recall == 0.5

    def test_exact_mode_rejects_extra_tools(self):
        s = _score([], ["query_data"], mode="exact")
        assert not s.tools_pass

    def test_exact_mode_accepts_empty_when_empty_expected(self):
        s = _score([], [], mode="exact")
        assert s.tools_pass and s.passed

    def test_subset_mode_allows_extras(self):
        s = _score(["query_data"], ["query_data", "list_tables"])
        assert s.tools_pass

    def test_wrong_intent_fails_the_case(self):
        s = _score(["query_data"], ["query_data"],
                   expected_intent="analysis", actual_intent="crud")
        assert not s.intent_correct and not s.passed

    def test_empty_selection_when_tools_expected_is_a_total_miss(self):
        s = _score(["query_data"], [])
        assert s.precision == 0.0 and s.recall == 0.0 and s.f1 == 0.0

    def test_fallback_is_recorded(self):
        s = _score(["query_data"], [], fell_back=True)
        assert s.fell_back


class TestRunner:
    def test_router_exception_is_captured_not_raised(self):
        """One broken case must not abort the whole run."""
        def boom(_question):
            raise RuntimeError("router down")

        case = GoldenCase(id="c1", question="q", expected_intent="crud",
                          expected_tools=["query_data"])
        score = score_case(case, boom)
        assert score.error and not score.passed

    def test_report_aggregates(self):
        cases = [
            GoldenCase(id="a", question="q1", expected_intent="crud",
                       expected_tools=["query_data"], tags=["read"]),
            GoldenCase(id="b", question="q2", expected_intent="analysis",
                       expected_tools=["query_data"], tags=["aggregate"]),
        ]
        report = run_routing_eval(cases, lambda q: (["query_data"], "crud"))
        assert report.total == 2
        assert report.intent_accuracy == 0.5
        assert report.macro_f1 == 1.0
        assert report.by_intent()["crud"]["accuracy"] == 1.0
        assert report.by_intent()["analysis"]["accuracy"] == 0.0

    def test_fallback_rate_is_reported(self):
        cases = [GoldenCase(id=f"c{i}", question="q", expected_intent="crud",
                            expected_tools=["query_data"]) for i in range(4)]
        calls = {"n": 0}

        def flaky(_q):
            calls["n"] += 1
            return (None, "general") if calls["n"] <= 1 else (["query_data"], "crud")

        report = run_routing_eval(cases, flaky)
        assert report.fallback_rate == 0.25


class TestGates:
    def _report(self, router, n=4):
        cases = [GoldenCase(id=f"c{i}", question="q", expected_intent="crud",
                            expected_tools=["query_data"]) for i in range(n)]
        return run_routing_eval(cases, router)

    def test_gates_pass_on_perfect_routing(self):
        report = self._report(lambda q: (["query_data"], "crud"))
        passed, failures = check_gates(
            report, {"intent_accuracy": 0.9, "tool_macro_f1": 0.85,
                     "max_fallback_rate": 0.05}
        )
        assert passed and failures == []

    def test_gates_fail_on_wrong_intent(self):
        report = self._report(lambda q: (["query_data"], "general"))
        passed, failures = check_gates(report, {"intent_accuracy": 0.9})
        assert not passed and "intent accuracy" in failures[0]

    def test_gates_fail_when_routing_always_falls_back(self):
        """The regression this gate exists to catch."""
        report = self._report(lambda q: (None, "general"))
        passed, failures = check_gates(report, {"max_fallback_rate": 0.05})
        assert not passed and "fallback" in failures[0]

    def test_markdown_scorecard_renders(self):
        report = self._report(lambda q: (["query_data"], "crud"))
        md = routing_markdown(report, {"intent_accuracy": 0.9})
        assert "L1 Routing Scorecard" in md
        assert "intent accuracy" in md


class TestOptionalTools:
    """Some selections are defensible but not required.

    The system prompt tells the agent to add search_schema when no table is
    named, so scoring it as a false positive would penalise the documented
    behaviour. Optional tools are neither credited nor penalised.
    """

    def _score_with_optional(self, actual, mode="subset"):
        case = GoldenCase(
            id="opt", question="q", expected_intent="crud",
            expected_tools=["query_data"], optional_tools=["search_schema"],
            tools_mode=mode,
        )
        return score_case(case, lambda q: (actual, "crud"))

    def test_optional_tool_does_not_cost_precision(self):
        s = self._score_with_optional(["search_schema", "query_data"])
        assert s.precision == 1.0
        assert s.f1 == 1.0
        assert s.passed

    def test_optional_tool_is_not_required(self):
        s = self._score_with_optional(["query_data"])
        assert s.recall == 1.0
        assert s.passed

    def test_non_optional_extras_still_cost_precision(self):
        """Only the listed tools are exempt."""
        s = self._score_with_optional(["query_data", "delete_rows"])
        assert s.precision == pytest.approx(0.5)

    def test_exact_mode_ignores_optional_tools(self):
        s = self._score_with_optional(["search_schema", "query_data"], mode="exact")
        assert s.tools_pass

    def test_optional_overlapping_expected_is_rejected(self):
        bad = GoldenCase(id="x", question="q", expected_intent="crud",
                         expected_tools=["query_data"], optional_tools=["query_data"])
        assert any("both expected and optional" in p for p in bad.validate(KNOWN_TOOLS))

    def test_unknown_optional_tool_is_rejected(self):
        bad = GoldenCase(id="x", question="q", expected_intent="crud",
                         optional_tools=["not_a_tool"])
        assert bad.validate(KNOWN_TOOLS)


class TestGreetingPreFilterRegression:
    """A greeting word plus a real request must reach the model."""

    def test_greeting_with_request_is_not_short_circuited(self):
        from app.router import _is_pure_greeting

        # "수고" matched the greeting list while "정리" was absent from the
        # data-keyword whitelist, so this was answered as a greeting.
        assert _is_pure_greeting("수고하셨습니다. 어제 것 좀 정리해주세요") is False

    def test_plain_greetings_still_short_circuit(self):
        from app.router import _is_pure_greeting

        for text in ("안녕하세요", "고마워요", "hi"):
            assert _is_pure_greeting(text) is True, text

    def test_greeting_plus_data_request_reaches_the_model(self):
        from app.router import _is_pure_greeting

        assert _is_pure_greeting("안녕하세요, 이번달 매출 좀 보여주세요") is False


class TestCostReporting:
    """A routing score without its price cannot settle a model choice."""

    def _report_with_usage(self, per_case_usage):
        cases = [GoldenCase(id=f"c{i}", question="q", expected_intent="crud",
                            expected_tools=["query_data"]) for i in range(3)]
        return run_routing_eval(
            cases, lambda q: (["query_data"], "crud", per_case_usage)
        )

    def test_tokens_and_cost_are_aggregated(self):
        report = self._report_with_usage({"total_tokens": 120, "cost_usd": 0.00006})
        assert report.total_tokens == 360
        assert report.total_cost_usd == pytest.approx(0.00018)
        assert report.cost_per_case_usd == pytest.approx(0.00006)

    def test_two_tuple_router_still_works(self):
        """Stubbed routers in tests return no usage; that must not break."""
        cases = [GoldenCase(id="c1", question="q", expected_intent="crud",
                            expected_tools=["query_data"])]
        report = run_routing_eval(cases, lambda q: (["query_data"], "crud"))
        assert report.total_tokens == 0
        assert report.total_cost_usd == 0.0
        assert report.pass_rate == 1.0

    def test_cost_appears_in_the_scorecard(self):
        report = self._report_with_usage({"total_tokens": 100, "cost_usd": 0.00005})
        md = routing_markdown(report)
        assert "routing cost" in md
        assert "routing tokens" in md

    def test_cost_omitted_when_unmeasured(self):
        """A dry run should not print a misleading $0.00000."""
        cases = [GoldenCase(id="c1", question="q", expected_intent="crud")]
        md = routing_markdown(run_routing_eval(cases, lambda q: ([], "crud")))
        assert "routing cost" not in md
