"""Tests for LLM cost accounting and per-turn usage tracking.

The behaviour under test is the gap this module was written to close: token
counts used to be computed and discarded, and the orchestrator's own call was
never counted at all, so every reported total understated real spend.
"""

import pytest

from app.llm_cost import estimate_cost_usd, is_priced, resolve_price
from app.llm_telemetry import (
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
    TurnLedger,
    track_llm_call,
)


class _Usage:
    """Stand-in for the OpenAI usage object."""

    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class TestPricing:
    def test_longest_prefix_wins(self):
        """gpt-5.4-nano must not resolve to the pricier gpt-5.4 row."""
        nano = resolve_price("gpt-5.4-nano")
        full = resolve_price("gpt-5.4")
        assert nano.input_per_1m < full.input_per_1m

    def test_dated_snapshot_resolves_to_base_model(self):
        assert resolve_price("gpt-5.4-nano-2026-01-01") == resolve_price("gpt-5.4-nano")

    def test_unknown_model_costs_zero_rather_than_guessing(self):
        assert estimate_cost_usd("some-unreleased-model", 1000, 1000) == 0.0
        assert is_priced("some-unreleased-model") is False

    def test_cost_scales_with_tokens(self):
        one = estimate_cost_usd("gpt-5.4", 1_000_000, 0)
        two = estimate_cost_usd("gpt-5.4", 2_000_000, 0)
        assert two == pytest.approx(one * 2)

    def test_output_priced_above_input(self):
        price = resolve_price("gpt-5.4")
        assert price.output_per_1m > price.input_per_1m


class TestTurnLedger:
    def test_orchestrator_and_worker_calls_are_both_counted(self):
        """The whole point: routing cost must not be invisible."""
        ledger = TurnLedger()
        with track_llm_call("gpt-5.4", ROLE_ORCHESTRATOR, ledger) as call:
            call.record_usage(_Usage(prompt_tokens=500, completion_tokens=50))
        with track_llm_call("gpt-5.4-nano", ROLE_WORKER, ledger) as call:
            call.record_usage(_Usage(prompt_tokens=2000, completion_tokens=300))

        assert ledger.total_tokens == 2850
        by_role = ledger.by_role()
        assert set(by_role) == {ROLE_ORCHESTRATOR, ROLE_WORKER}
        assert by_role[ROLE_ORCHESTRATOR]["tokens"] == 550
        assert by_role[ROLE_WORKER]["tokens"] == 2300

    def test_cost_is_accumulated_across_calls(self):
        ledger = TurnLedger()
        for _ in range(3):
            with track_llm_call("gpt-5.4", ROLE_WORKER, ledger) as call:
                call.record_usage(_Usage(prompt_tokens=1_000_000, completion_tokens=0))
        expected = estimate_cost_usd("gpt-5.4", 1_000_000, 0) * 3
        assert ledger.cost_usd == pytest.approx(expected)

    def test_summary_shape_is_persistable(self):
        ledger = TurnLedger()
        with track_llm_call("gpt-5.4-nano", ROLE_WORKER, ledger) as call:
            call.record_usage(_Usage(prompt_tokens=10, completion_tokens=5))
        summary = ledger.summary()
        assert summary["calls"] == 1
        assert summary["total_tokens"] == 15
        assert summary["prompt_tokens"] == 10
        assert summary["completion_tokens"] == 5
        assert ROLE_WORKER in summary["by_role"]

    def test_empty_ledger_reports_zeroes(self):
        summary = TurnLedger().summary()
        assert summary["calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["cost_usd"] == 0

    def test_failed_call_is_still_recorded(self):
        """A call that raises still consumed time and must stay countable."""
        ledger = TurnLedger()
        with pytest.raises(RuntimeError):
            with track_llm_call("gpt-5.4", ROLE_WORKER, ledger):
                raise RuntimeError("api exploded")
        assert len(ledger.calls) == 1
        assert ledger.calls[0].outcome == "error"

    def test_missing_usage_does_not_break_accounting(self):
        """Streamed responses can omit usage; that must not raise."""
        ledger = TurnLedger()
        with track_llm_call("gpt-5.4", ROLE_WORKER, ledger) as call:
            call.record_usage(None)
        assert ledger.total_tokens == 0

    def test_non_integer_usage_is_treated_as_unknown(self):
        """Anything non-numeric from the SDK must not reach a metric counter."""
        ledger = TurnLedger()
        with track_llm_call("gpt-5.4", ROLE_WORKER, ledger) as call:
            call.record_usage(_Usage(prompt_tokens=object(), completion_tokens=None))
        assert ledger.total_tokens == 0

    def test_duration_is_measured(self):
        ledger = TurnLedger()
        with track_llm_call("gpt-5.4", ROLE_WORKER, ledger) as call:
            call.record_usage(_Usage(1, 1))
        assert ledger.calls[0].duration_s >= 0
