from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.oral_assessment.main import create_app
from services.oral_assessment.models import CEFRLevel
from services.oral_assessment.rubric_evaluator import (
    EvaluationUnavailable,
    ScriptedEvaluator,
)

from .helpers import PROJECT_ROOT, evaluator_output


class AlwaysUnavailableEvaluator:
    provider_name = "gemini"
    model_name = "gemini-test"

    def evaluate(self, request):
        raise EvaluationUnavailable(
            "simulated Gemini overload",
            provider="gemini",
            category="provider_overloaded",
            status_code=503,
            retryable=True,
        )


class APIRegressionTests(unittest.TestCase):
    def test_empty_provider_word_rows_no_longer_return_422(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "ASSESSMENT_DATABASE_URL": f"sqlite:///{Path(directory) / 'api.db'}",
                "ASSESSMENT_SERVICE_TOKEN": "api-regression-service-token",
                "ASSESSMENT_ADMIN_TOKEN": "api-regression-admin-token",
                "EVALUATOR_PROVIDER": "heuristic",
                "ALLOW_HEURISTIC_EVALUATOR": "true",
                "STORE_ALL_ASSESSMENT_AUDIO": "false",
                # A 0.1.2 .env may still contain this obsolete switch. It must
                # not restore the removed read-aloud task.
                "PRONUNCIATION_TASK_ENABLED": "true",
            }
            with patch.dict(os.environ, environment, clear=False):
                client = TestClient(create_app(PROJECT_ROOT))
                headers = {"Authorization": "Bearer api-regression-service-token"}
                created = client.post(
                    "/v1/assessments",
                    headers=headers,
                    json={"user_id": "api-regression-learner"},
                )
                self.assertEqual(201, created.status_code)
                body = created.json()
                prompt = body["current_item"]

                response = client.post(
                    f"/v1/assessments/{body['assessment_id']}/responses",
                    headers={**headers, "Idempotency-Key": "api-regression-response"},
                    json={
                        "response_id": "api-regression-response",
                        "idempotency_key": "api-regression-response",
                        "prompt_id": prompt["prompt_id"],
                        "item_id": prompt["item_id"],
                        "prompt_kind": prompt["prompt_kind"],
                        "transcript": "Clear voices are easy to hear.",
                        "words": [
                            {"word": "", "start": 0.0, "end": 0.1}
                            for _ in range(6)
                        ],
                    },
                )
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual("not_scored", response.json()["response_decision"])
                self.assertEqual("ask_main", response.json()["next_action"]["type"])

    def test_evaluator_503_preserves_prompt_and_same_response_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "ASSESSMENT_DATABASE_URL": f"sqlite:///{Path(directory) / 'api.db'}",
                "ASSESSMENT_SERVICE_TOKEN": "api-regression-service-token",
                "ASSESSMENT_ADMIN_TOKEN": "api-regression-admin-token",
                "EVALUATOR_PROVIDER": "heuristic",
                "ALLOW_HEURISTIC_EVALUATOR": "true",
                "STORE_ALL_ASSESSMENT_AUDIO": "false",
            }
            with patch.dict(os.environ, environment, clear=False):
                app = create_app(PROJECT_ROOT)
                client = TestClient(app)
                headers = {"Authorization": "Bearer api-regression-service-token"}
                created = client.post(
                    "/v1/assessments",
                    headers=headers,
                    json={"user_id": "api-503-learner"},
                ).json()
                assessment_id = created["assessment_id"]
                calibration = created["current_item"]
                client.post(
                    f"/v1/assessments/{assessment_id}/responses",
                    headers={**headers, "Idempotency-Key": "calibration-idempotency"},
                    json={
                        "response_id": "calibration-response",
                        "idempotency_key": "calibration-idempotency",
                        "prompt_id": calibration["prompt_id"],
                        "item_id": calibration["item_id"],
                        "prompt_kind": calibration["prompt_kind"],
                        "transcript": "Clear voices are easy to hear and I can hear clearly.",
                    },
                )
                state = client.get(
                    f"/v1/assessments/{assessment_id}", headers=headers
                ).json()
                prompt = state["current_prompt"]
                submission = {
                    "response_id": "retryable-response",
                    "idempotency_key": "retryable-idempotency",
                    "prompt_id": prompt["prompt_id"],
                    "item_id": prompt["item_id"],
                    "prompt_kind": prompt["prompt_kind"],
                    "transcript": "I gave a relevant clear answer to this familiar question.",
                }

                app.state.assessment_service.evaluator = AlwaysUnavailableEvaluator()
                unavailable = client.post(
                    f"/v1/assessments/{assessment_id}/responses",
                    headers={**headers, "Idempotency-Key": "retryable-idempotency"},
                    json=submission,
                )
                self.assertEqual(503, unavailable.status_code)
                self.assertEqual("provider_overloaded", unavailable.json()["error_code"])
                self.assertEqual("5", unavailable.headers["Retry-After"])

                unchanged = client.get(
                    f"/v1/assessments/{assessment_id}", headers=headers
                ).json()
                self.assertEqual(prompt["prompt_id"], unchanged["current_prompt"]["prompt_id"])
                self.assertEqual(1, unchanged["record"]["evaluator_failure_count"])

                app.state.assessment_service.evaluator = ScriptedEvaluator(
                    [evaluator_output(CEFRLevel(prompt["target_level"]), 3)]
                )
                recovered = client.post(
                    f"/v1/assessments/{assessment_id}/responses",
                    headers={**headers, "Idempotency-Key": "retryable-idempotency"},
                    json=submission,
                )
                self.assertEqual(200, recovered.status_code, recovered.text)
                self.assertEqual("pass", recovered.json()["response_decision"])
                evidence = client.get(
                    f"/v1/assessments/{assessment_id}/evidence", headers=headers
                )
                self.assertEqual(200, evidence.status_code)
                self.assertEqual(2, len(evidence.json()["responses"]))
                scored = evidence.json()["responses"][-1]
                self.assertEqual("retryable-response", scored["response_id"])
                self.assertEqual("scripted", scored["scored"]["evaluator_provider"])


if __name__ == "__main__":
    unittest.main()
