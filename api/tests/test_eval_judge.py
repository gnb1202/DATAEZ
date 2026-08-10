"""Tests for the LLM-as-a-judge layer.

Covers the three defects this module shipped with: a hardcoded judge model,
a position-swap run whose disagreement signal was discarded, and a pairwise
suite average computed as max(score_a, score_b).
"""

from unittest.mock import MagicMock, patch

import pytest

from app.eval_judge import (
    EvalTestCase,
    PairwiseResult,
    _winner_from_scores,
    pairwise_evaluate,
    run_eval_suite,
)


def _response(payload: str):
    """Build a stand-in OpenAI chat completion carrying `payload`."""
    message = MagicMock()
    message.content = payload
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


class TestJudgeModelConfiguration:
    def test_judge_model_comes_from_settings(self):
        from app.config import settings
        from app.eval_judge import _get_eval_client

        with patch("app.openai_clients.get_openai_client", return_value=MagicMock()):
            _client, model = _get_eval_client()
        assert model == settings.openai_judge_model

    def test_explicit_model_overrides_settings(self):
        from app.eval_judge import _get_eval_client

        with patch("app.openai_clients.get_openai_client", return_value=MagicMock()):
            _client, model = _get_eval_client("some-other-judge")
        assert model == "some-other-judge"


class TestWinnerFromScores:
    def test_close_scores_are_a_tie(self):
        assert _winner_from_scores(4.0, 4.2) == "tie"

    def test_clear_margin_picks_a_winner(self):
        assert _winner_from_scores(4.5, 3.0) == "A"
        assert _winner_from_scores(3.0, 4.5) == "B"


class TestPositionBias:
    """A verdict that changes when the responses swap places is about
    position, not quality — averaging alone would hide that."""

    @patch("app.eval_judge._get_eval_client")
    def test_flip_is_detected_and_reported(self, mock_client):
        client = MagicMock()
        # Both runs favour whichever response was presented first.
        client.chat.completions.create.side_effect = [
            _response('{"winner": "A", "score_a": 5, "score_b": 2, "explanation": "first"}'),
            _response('{"winner": "A", "score_a": 5, "score_b": 2, "explanation": "second"}'),
        ]
        mock_client.return_value = (client, "judge-model")

        result = pairwise_evaluate(
            user_question="q", response_a="A답변", response_b="B답변",
        )
        assert result.position_bias_check is True
        assert result.verdict_flipped is True
        assert result.winner_run1 == "A"
        assert result.winner_run2 == "B"

    @patch("app.eval_judge._get_eval_client")
    def test_consistent_verdict_is_not_flagged(self, mock_client):
        client = MagicMock()
        # Run 2 has the labels swapped, so B-first winning as "B" means the
        # original A won again.
        client.chat.completions.create.side_effect = [
            _response('{"winner": "A", "score_a": 5, "score_b": 2, "explanation": "1"}'),
            _response('{"winner": "B", "score_a": 2, "score_b": 5, "explanation": "2"}'),
        ]
        mock_client.return_value = (client, "judge-model")

        result = pairwise_evaluate(user_question="q", response_a="A", response_b="B")
        assert result.verdict_flipped is False
        assert result.winner == "A"

    @patch("app.eval_judge._get_eval_client")
    def test_single_run_mode_skips_the_swap(self, mock_client):
        client = MagicMock()
        client.chat.completions.create.return_value = _response(
            '{"winner": "B", "score_a": 2, "score_b": 5, "explanation": "x"}'
        )
        mock_client.return_value = (client, "judge-model")

        result = pairwise_evaluate(
            user_question="q", response_a="A", response_b="B",
            mitigate_position_bias=False,
        )
        assert result.position_bias_check is False
        assert result.winner == "B"
        assert client.chat.completions.create.call_count == 1


class TestPairwiseSuiteAggregation:
    """The old aggregate was mean(max(score_a, score_b)), which rose whenever
    either variant scored well and never revealed which one won."""

    @patch("app.eval_judge.pairwise_evaluate")
    def test_suite_reports_win_rates_not_a_meaningless_mean(self, mock_pairwise):
        mock_pairwise.side_effect = [
            PairwiseResult(winner="A", score_a=5, score_b=2),
            PairwiseResult(winner="A", score_a=4, score_b=3),
            PairwiseResult(winner="B", score_a=2, score_b=5),
            PairwiseResult(winner="tie", score_a=4, score_b=4),
        ]
        cases = [EvalTestCase(id=f"c{i}", user_question="q") for i in range(4)]

        result = run_eval_suite(cases, mode="pairwise")

        assert result.win_rate_a == 0.5
        assert result.win_rate_b == 0.25
        assert result.tie_rate == 0.25
        assert result.avg_score == 0.0

    @patch("app.eval_judge.pairwise_evaluate")
    def test_flip_rate_is_aggregated(self, mock_pairwise):
        mock_pairwise.side_effect = [
            PairwiseResult(winner="A", score_a=5, score_b=2, verdict_flipped=True),
            PairwiseResult(winner="B", score_a=2, score_b=5, verdict_flipped=False),
        ]
        cases = [EvalTestCase(id=f"c{i}", user_question="q") for i in range(2)]

        result = run_eval_suite(cases, mode="pairwise")
        assert result.flip_rate == 0.5

    @patch("app.eval_judge.pointwise_evaluate")
    def test_pointwise_mode_still_averages_scores(self, mock_pointwise):
        from app.eval_judge import PointwiseResult

        mock_pointwise.side_effect = [
            PointwiseResult(overall_score=4.0, criteria_scores={"tool_selection": 4.0}),
            PointwiseResult(overall_score=2.0, criteria_scores={"tool_selection": 2.0}),
        ]
        cases = [EvalTestCase(id=f"c{i}", user_question="q") for i in range(2)]

        result = run_eval_suite(cases, mode="pointwise")
        assert result.avg_score == 3.0
        assert result.criteria_averages["tool_selection"] == 3.0
