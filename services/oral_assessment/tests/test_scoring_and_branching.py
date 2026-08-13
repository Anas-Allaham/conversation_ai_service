from __future__ import annotations

import unittest

from services.oral_assessment.branching_engine import decide_stage
from services.oral_assessment.models import (
    CEFRLevel,
    DimensionScores,
    ResponseDecision,
    StageDecision,
)
from services.oral_assessment.scoring_engine import score_evaluator_output

from .helpers import evaluator_output


class BranchingTests(unittest.TestCase):
    def test_documented_stage_matrix(self) -> None:
        expected = {
            (ResponseDecision.PASS, ResponseDecision.PASS): StageDecision.PASS,
            (ResponseDecision.PASS, ResponseDecision.BORDERLINE): StageDecision.TIE_BREAKER,
            (ResponseDecision.PASS, ResponseDecision.FAIL): StageDecision.TIE_BREAKER,
            (ResponseDecision.BORDERLINE, ResponseDecision.PASS): StageDecision.TIE_BREAKER,
            (ResponseDecision.BORDERLINE, ResponseDecision.BORDERLINE): StageDecision.TIE_BREAKER,
            (ResponseDecision.BORDERLINE, ResponseDecision.FAIL): StageDecision.FAIL,
            (ResponseDecision.FAIL, ResponseDecision.PASS): StageDecision.TIE_BREAKER,
            (ResponseDecision.FAIL, ResponseDecision.BORDERLINE): StageDecision.FAIL,
            (ResponseDecision.FAIL, ResponseDecision.FAIL): StageDecision.FAIL,
        }
        for pair, decision in expected.items():
            self.assertEqual(decision, decide_stage(*pair))

    def test_invalid_audio_is_not_a_stage_failure(self) -> None:
        with self.assertRaises(ValueError):
            decide_stage(ResponseDecision.INVALID_AUDIO, ResponseDecision.PASS)


class ScoringTests(unittest.TestCase):
    def test_clear_pass(self) -> None:
        scored = score_evaluator_output(
            evaluator_output(CEFRLevel.B1, 3), provider="test", model="test"
        )
        self.assertEqual(ResponseDecision.PASS, scored.decision)
        self.assertEqual(3.0, scored.weighted_score)

    def test_weighted_pass_with_critical_shortfall_is_borderline(self) -> None:
        scored = score_evaluator_output(
            evaluator_output(CEFRLevel.B1, 4, interaction=2), provider="test", model="test"
        )
        self.assertEqual(ResponseDecision.BORDERLINE, scored.decision)

    def test_meaning_blocked_fails_even_with_high_numbers(self) -> None:
        scored = score_evaluator_output(
            evaluator_output(CEFRLevel.A2, 4, meaning_blocked=True),
            provider="test",
            model="test",
        )
        self.assertEqual(ResponseDecision.FAIL, scored.decision)

    def test_grammar_is_not_a_scored_dimension(self) -> None:
        fields = set(DimensionScores.model_fields)
        self.assertNotIn("grammar", fields)


if __name__ == "__main__":
    unittest.main()
