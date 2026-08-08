from __future__ import annotations

import unittest

from services.oral_assessment.models import CEFRLevel
from services.oral_assessment.rubric_evaluator import (
    LEVEL_ANCHORS,
    SYSTEM_INSTRUCTION,
    GeminiEvaluator,
    classify_gemini_error,
    gemini_retry_after_seconds,
    gemini_structured_output_config,
)


class FakeGeminiError(Exception):
    def __init__(self, code: int, details: dict) -> None:
        self.code = code
        self.details = details
        self.response = None


class FakeModels:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class EvaluatorContractTests(unittest.TestCase):
    def test_gemini_uses_google_structured_output_fields(self) -> None:
        config = gemini_structured_output_config()
        self.assertEqual("application/json", config["response_mime_type"])
        self.assertIn("response_json_schema", config)
        self.assertNotIn("response_format", config)

    def test_level_anchors_do_not_turn_task_format_or_asr_noise_into_failure(self) -> None:
        self.assertIn("structured", LEVEL_ANCHORS[CEFRLevel.A2])
        self.assertIn("some help", LEVEL_ANCHORS[CEFRLevel.A2])
        self.assertIn("non-central detail", SYSTEM_INSTRUCTION)
        self.assertIn("ASR substitutions", SYSTEM_INSTRUCTION)
        self.assertIn("One permitted repetition or clarification", SYSTEM_INSTRUCTION)

    def test_google_retry_info_delay_is_extracted_and_daily_quota_is_classified(self) -> None:
        error = FakeGeminiError(
            429,
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "49s",
                        },
                    ]
                }
            },
        )
        self.assertEqual(49.0, gemini_retry_after_seconds(error))
        category, status, retryable, retry_after = classify_gemini_error(error)
        self.assertEqual("provider_daily_quota_exhausted", category)
        self.assertEqual(429, status)
        self.assertTrue(retryable)
        self.assertEqual(49.0, retry_after)

    def test_gemini_waits_for_provider_delay_instead_of_immediate_retries(self) -> None:
        error = FakeGeminiError(
            429,
            {"error": {"details": [{"retryDelay": "4s"}]}},
        )
        expected = object()
        models = FakeModels([error, expected])
        evaluator = GeminiEvaluator.__new__(GeminiEvaluator)
        evaluator.model_name = "gemini-2.5-flash-lite"
        evaluator._api_error_type = FakeGeminiError
        evaluator._max_retries = 3
        evaluator._max_retry_wait_seconds = 60.0
        waits: list[float] = []
        evaluator._sleep = waits.append
        evaluator._client = FakeClient(models)

        self.assertIs(expected, evaluator._generate("score this"))
        self.assertEqual([4.0], waits)
        self.assertEqual(2, models.calls)

    def test_gemini_404_is_configuration_error_and_not_immediately_retryable(self) -> None:
        category, status, retryable, retry_after = classify_gemini_error(
            FakeGeminiError(404, {"error": {"message": "Not Found"}})
        )
        self.assertEqual("provider_configuration_error", category)
        self.assertEqual(404, status)
        self.assertFalse(retryable)
        self.assertIsNone(retry_after)


if __name__ == "__main__":
    unittest.main()
