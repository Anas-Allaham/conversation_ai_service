from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.oral_assessment.item_bank import ItemBankRepository
from services.oral_assessment.models import (
    AssessmentCreateRequest,
    CEFRLevel,
    PromptKind,
    ResponseSubmission,
)
from services.oral_assessment.repository import SQLRepository
from services.oral_assessment.rubric_evaluator import (
    EvaluationUnavailable,
    ScriptedEvaluator,
)
from services.oral_assessment.service import AssessmentService

from .helpers import evaluator_output, make_test_settings


class FlakyEvaluator:
    provider_name = "flaky-test"
    model_name = "flaky-test-v1"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        if self.calls == 1:
            raise EvaluationUnavailable(
                "simulated overload",
                provider="gemini",
                category="provider_overloaded",
                status_code=503,
                retryable=True,
            )
        return evaluator_output(request.item.target_level, 3)


class PilotRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        database_url = f"sqlite:///{Path(self.temp.name) / 'assessment.db'}"
        self.settings = make_test_settings(database_url)
        self.repository = SQLRepository(database_url)
        self.repository.initialize()
        self.bank = ItemBankRepository(self.settings.item_bank_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def submission(prompt, index: int, transcript: str) -> ResponseSubmission:
        return ResponseSubmission(
            response_id=f"pilot-response-{index}",
            idempotency_key=f"pilot-idempotency-{index}",
            prompt_id=prompt.prompt_id,
            item_id=prompt.item_id,
            prompt_kind=prompt.prompt_kind,
            transcript=transcript,
            response_started_at_ms=1_000,
            response_ended_at_ms=13_000,
        )

    def test_morning_routine_pilot_answers_do_not_end_at_a1(self) -> None:
        service = AssessmentService(
            self.settings,
            self.repository,
            self.bank,
            ScriptedEvaluator(
                [
                    evaluator_output(CEFRLevel.A1, 3),
                    evaluator_output(CEFRLevel.A1, 3),
                ]
            ),
        )
        created = service.create_assessment(
            AssessmentCreateRequest(user_id="aya-pilot", form_seed="appointment-seed-0")
        )
        record = self.repository.get_assessment(created.assessment_id)
        calibration = service.current_prompt(record)
        service.submit_response(
            created.assessment_id,
            self.submission(
                calibration,
                0,
                "My name is Aya. Clear voices are easy to hear. I can hear clearly.",
            ),
        )
        record = self.repository.get_assessment(created.assessment_id)
        main = service.current_prompt(record)
        service.submit_response(
            created.assessment_id,
            self.submission(
                main,
                1,
                "I brush my hair, brush my teeth, wash my face, tidy my room and my bed, "
                "and open the curtains to let sunlight enter my room.",
            ),
        )
        record = self.repository.get_assessment(created.assessment_id)
        follow_up = service.current_prompt(record)
        service.submit_response(
            created.assessment_id,
            self.submission(
                follow_up,
                2,
                "I like the early morning because it feels like a new start. I like being alone "
                "while everyone is sleeping because it is the calmest moment in my day.",
            ),
        )
        record = self.repository.get_assessment(created.assessment_id)
        self.assertEqual("in_progress", record.status.value)
        self.assertEqual(CEFRLevel.A1, record.highest_confirmed_level)
        self.assertEqual(CEFRLevel.A2, service.current_prompt(record).target_level)

    def test_failed_appointment_pair_uses_a_different_a2_task_before_stopping(self) -> None:
        outputs = [
            evaluator_output(CEFRLevel.A1, 3),
            evaluator_output(CEFRLevel.A1, 3),
            evaluator_output(CEFRLevel.A2, 1, task_achieved=False),
            evaluator_output(CEFRLevel.A2, 1, task_achieved=False),
        ]
        service = AssessmentService(
            self.settings,
            self.repository,
            self.bank,
            ScriptedEvaluator(outputs),
        )
        created = service.create_assessment(
            AssessmentCreateRequest(user_id="appointment-pilot", form_seed="appointment-seed-0")
        )
        record = self.repository.get_assessment(created.assessment_id)
        transcripts = [
            "Clear voices are easy to hear and I can hear clearly.",
            "I visit a place near my home because it is quiet.",
            "I usually go there alone and sometimes with my father.",
            "Four PM suits me. Is it good for you too?",
            "What times are available for Monday?",
        ]
        for index, transcript in enumerate(transcripts):
            prompt = service.current_prompt(record)
            service.submit_response(
                created.assessment_id,
                self.submission(prompt, 20 + index, transcript),
            )
            record = self.repository.get_assessment(created.assessment_id)

        boundary = service.current_prompt(record)
        self.assertEqual("in_progress", record.status.value)
        self.assertEqual(CEFRLevel.A2, boundary.target_level)
        self.assertEqual(PromptKind.TIE_BREAKER, boundary.prompt_kind)
        self.assertNotEqual("A2_APPOINTMENT_003", boundary.item_id)

    def test_503_keeps_prompt_and_same_idempotent_response_can_recover(self) -> None:
        evaluator = FlakyEvaluator()
        service = AssessmentService(
            self.settings,
            self.repository,
            self.bank,
            evaluator,
        )
        created = service.create_assessment(AssessmentCreateRequest(user_id="retry-pilot"))
        record = self.repository.get_assessment(created.assessment_id)
        calibration = service.current_prompt(record)
        service.submit_response(
            created.assessment_id,
            self.submission(calibration, 40, "I can hear clearly."),
        )
        record = self.repository.get_assessment(created.assessment_id)
        prompt = service.current_prompt(record)
        submission = self.submission(
            prompt,
            41,
            "I answer the familiar question directly with enough clear information.",
        )

        with self.assertRaises(EvaluationUnavailable):
            service.submit_response(created.assessment_id, submission)

        failed_record = self.repository.get_assessment(created.assessment_id)
        self.assertEqual(1, failed_record.evaluator_failure_count)
        self.assertEqual(prompt.prompt_id, failed_record.current_prompt_id)
        self.assertEqual([], self.repository.list_responses(created.assessment_id)[1:])

        recovered = service.submit_response(created.assessment_id, submission)
        self.assertEqual("pass", recovered.response_decision.value)
        self.assertEqual(2, evaluator.calls)
        self.assertEqual(2, len(self.repository.list_responses(created.assessment_id)))


if __name__ == "__main__":
    unittest.main()
