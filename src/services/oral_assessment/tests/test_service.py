from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.oral_assessment.item_bank import ItemBankRepository
from services.oral_assessment.models import (
    LEVELS,
    AssessmentCreateRequest,
    CEFRLevel,
    NextActionType,
    PromptKind,
    PronunciationDiagnostic,
    ResponseSubmission,
    WordTiming,
)
from services.oral_assessment.repository import SQLRepository
from services.oral_assessment.rubric_evaluator import ScriptedEvaluator
from services.oral_assessment.service import AssessmentService, SubmissionConflict

from .helpers import evaluator_output, make_test_settings


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.temp.name) / 'assessment.db'}"
        self.settings = make_test_settings(self.database_url)
        self.repository = SQLRepository(self.database_url)
        self.repository.initialize()
        self.bank = ItemBankRepository(self.settings.item_bank_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def submission(prompt, index: int, text: str = "This is a clear connected response with enough relevant detail for the task and follow-up."):
        return ResponseSubmission(
            response_id=f"response-{index}",
            idempotency_key=f"idempotency-{index}",
            prompt_id=prompt.prompt_id,
            item_id=prompt.item_id,
            prompt_kind=prompt.prompt_kind,
            transcript=text,
            response_started_at_ms=1_000,
            response_ended_at_ms=11_000,
        )

    def _service(self, outputs):
        return AssessmentService(
            self.settings,
            self.repository,
            self.bank,
            ScriptedEvaluator(list(outputs)),
        )

    def test_full_a1_to_b2_ceiling_flow(self) -> None:
        service = self._service([evaluator_output(level, 3) for level in LEVELS for _ in range(2)])
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner", form_seed="fixed"))
        record = self.repository.get_assessment(created.assessment_id)
        self.assertIsNotNone(record)
        for index in range(9):
            prompt = service.current_prompt(record)
            service.submit_response(created.assessment_id, self.submission(prompt, index))
            record = self.repository.get_assessment(created.assessment_id)
        final = service.get_result(created.assessment_id)
        self.assertEqual(CEFRLevel.B2, final.confirmed_level)
        self.assertTrue(final.ceiling_reached)
        self.assertEqual("medium", final.confidence.value)
        self.assertFalse(final.grammar_assessed)

    def test_a1_failure_uses_different_a1_boundary_item_before_pre_a1_result(self) -> None:
        service = self._service(
            [
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
            ]
        )
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        for index in range(3):
            prompt = service.current_prompt(record)
            service.submit_response(created.assessment_id, self.submission(prompt, index))
            record = self.repository.get_assessment(created.assessment_id)
        self.assertEqual("in_progress", record.status.value)
        self.assertEqual(CEFRLevel.A1, LEVELS[record.current_level_index])
        self.assertEqual(PromptKind.TIE_BREAKER, record.current_prompt_kind)
        self.assertEqual([CEFRLevel.A1], record.boundary_verification_levels)

        for index in range(3, 4):
            prompt = service.current_prompt(record)
            service.submit_response(created.assessment_id, self.submission(prompt, index))
            record = self.repository.get_assessment(created.assessment_id)
        final = service.get_result(created.assessment_id)
        self.assertEqual("Pre-A1", final.confirmed_level)
        self.assertEqual(CEFRLevel.A1, final.first_unconfirmed_level)
        self.assertEqual("first_unconfirmed_level_reached", final.completion_reason)
        self.assertLess(final.confidence_score, 100)
        self.repository.save_pronunciation(
            created.assessment_id,
            PronunciationDiagnostic(
                status="completed",
                phoneme_error_rate=0.75,
                impact_on_conversational_level="none",
            ),
        )
        with_pronunciation = service.get_result(created.assessment_id)
        self.assertEqual("Pre-A1", with_pronunciation.confirmed_level)
        self.assertEqual(0.75, with_pronunciation.pronunciation_diagnostic.phoneme_error_rate)

    def test_same_level_boundary_pass_recovers_initial_a1_false_negative(self) -> None:
        service = self._service(
            [
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 3),
            ]
        )
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        for index in range(4):
            prompt = service.current_prompt(record)
            service.submit_response(created.assessment_id, self.submission(prompt, 50 + index))
            record = self.repository.get_assessment(created.assessment_id)
        self.assertEqual("in_progress", record.status.value)
        self.assertEqual(CEFRLevel.A1, record.highest_confirmed_level)
        self.assertEqual(CEFRLevel.A2, LEVELS[record.current_level_index])

    def test_borderline_path_requires_and_passes_tie_breaker(self) -> None:
        outputs = [
            evaluator_output(CEFRLevel.A1, 3),
            evaluator_output(CEFRLevel.A1, 2, task=3, interaction=3, intelligibility=2),
            evaluator_output(CEFRLevel.A1, 3),
        ]
        service = self._service(outputs)
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        actions = []
        for index in range(4):
            prompt = service.current_prompt(record)
            result = service.submit_response(created.assessment_id, self.submission(prompt, index))
            actions.append(result.next_action.type)
            record = self.repository.get_assessment(created.assessment_id)
        self.assertIn(NextActionType.ASK_TIE_BREAKER, actions)
        self.assertEqual(CEFRLevel.A1, record.highest_confirmed_level)
        self.assertEqual(1, record.tie_breaker_count)

    def test_response_retry_is_idempotent(self) -> None:
        service = self._service([])
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        prompt = service.current_prompt(record)
        submission = self.submission(prompt, 0)
        first = service.submit_response(created.assessment_id, submission)
        second = service.submit_response(created.assessment_id, submission)
        self.assertFalse(first.idempotent_replay)
        self.assertTrue(second.idempotent_replay)
        self.assertEqual(1, len(self.repository.list_responses(created.assessment_id)))

    def test_reused_response_id_with_new_key_is_rejected(self) -> None:
        service = self._service([])
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        prompt = service.current_prompt(record)
        submission = self.submission(prompt, 0)
        service.submit_response(created.assessment_id, submission)
        with self.assertRaises(SubmissionConflict):
            service.submit_response(
                created.assessment_id,
                submission.model_copy(update={"idempotency_key": "another-idempotency-key"}),
            )

    def test_two_unusable_calibration_attempts_assign_no_level(self) -> None:
        service = self._service([])
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        for index in range(2):
            record = self.repository.get_assessment(created.assessment_id)
            prompt = service.current_prompt(record)
            submission = self.submission(prompt, index, text="").model_copy(
                update={"explicit_audio_issue": True, "audio_issue_reason": "microphone clipping"}
            )
            service.submit_response(created.assessment_id, submission)
        final = service.get_result(created.assessment_id)
        self.assertEqual("Not determined", final.confirmed_level)
        self.assertEqual("low", final.confidence.value)
        self.assertEqual("audio_unusable", final.completion_reason)

    def test_calibration_moves_directly_to_a1_without_a_read_aloud_task(self) -> None:
        service = self._service([])
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        calibration = service.current_prompt(record)
        first = service.submit_response(
            created.assessment_id,
            self.submission(
                calibration,
                100,
                text="Aya. Clear voices are easy to hear. I can hear clearly.",
            ),
        )
        self.assertEqual(NextActionType.ASK_MAIN, first.next_action.type)
        self.assertEqual(CEFRLevel.A1, first.next_action.prompt.target_level)
        record = self.repository.get_assessment(created.assessment_id)
        self.assertEqual("in_progress", record.status.value)
        self.assertEqual(PromptKind.MAIN, record.current_prompt_kind)
        self.assertIsNone(self.repository.get_pronunciation(created.assessment_id))

    def test_result_contract_contains_backend_confidence_and_statistics(self) -> None:
        service = self._service(
            [
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
            ]
        )
        created = service.create_assessment(AssessmentCreateRequest(user_id="learner"))
        record = self.repository.get_assessment(created.assessment_id)
        for index in range(4):
            prompt = service.current_prompt(record)
            service.submit_response(created.assessment_id, self.submission(prompt, 200 + index))
            record = self.repository.get_assessment(created.assessment_id)
        final = service.get_result(created.assessment_id)
        self.assertGreaterEqual(final.confidence_score, 0)
        self.assertLessEqual(final.confidence_score, 100)
        self.assertIn("probability", final.confidence_score_interpretation)
        self.assertEqual(4, final.statistics.responses_submitted)
        self.assertLess(final.confidence_score, 100)
        self.assertIn("fluency", final.profile_scores_percent)
        self.assertEqual("complete", service.progress(record).current_section)

    def test_result_contains_authoritative_feature_based_fluency(self) -> None:
        service = self._service(
            [
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
                evaluator_output(CEFRLevel.A1, 1),
            ]
        )
        created = service.create_assessment(AssessmentCreateRequest(user_id="timed-learner"))
        record = self.repository.get_assessment(created.assessment_id)
        for index in range(4):
            prompt = service.current_prompt(record)
            submission = self.submission(prompt, 400 + index).model_copy(
                update={
                    "words": [
                        WordTiming(
                            word=f"word{word_index}",
                            start=word_index * 0.5,
                            end=word_index * 0.5 + 0.24,
                        )
                        for word_index in range(14)
                    ]
                }
            )
            service.submit_response(created.assessment_id, submission)
            record = self.repository.get_assessment(created.assessment_id)
        final = service.get_result(created.assessment_id)
        self.assertEqual("scored", final.fluency.status.value)
        self.assertIsNotNone(final.fluency.fluency_index)
        self.assertEqual(final.fluency.cefr_fluency_estimate, final.profile["fluency"])
        self.assertEqual(
            final.fluency.fluency_index,
            final.profile_scores_percent["fluency"],
        )
        self.assertEqual("fluency-v0.1", final.versions.fluency)


if __name__ == "__main__":
    unittest.main()
