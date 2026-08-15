from __future__ import annotations

import io
import json
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from app.realtime.assessment_agent import LevelAssessmentAgent
from app.services.assessment_client import AssessmentClient, AssessmentHTTPError


class FakeRecorder:
    async def pause_segment(self, *, preserve: bool) -> None:
        return None

    async def stop_and_upload(
        self,
        assessment_id: str,
        response_id: str,
        *,
        upload: bool,
    ) -> None:
        return None


class NonRetryableEvaluatorFailureClient:
    def __init__(self) -> None:
        self.state_reads = 0

    async def submit_response_async(self, assessment_id: str, payload: dict):
        raise AssessmentHTTPError(
            503,
            "Evaluator configuration failed",
            error_code="provider_configuration_error",
            retry_after_seconds=30,
            retryable=False,
        )

    async def get_assessment_state_async(self, assessment_id: str):
        self.state_reads += 1
        raise AssertionError("A provider 503 must not recover by replaying the current prompt")


class ProviderFailureRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_404_wrapped_as_503_saves_answer_without_repeating_prompt(self) -> None:
        prompt = {
            "prompt_id": "A1_PLACE_002:main",
            "item_id": "A1_PLACE_002",
            "prompt_kind": "main",
            "prompt": "Tell me about one place near your home that you visit often.",
        }
        client = NonRetryableEvaluatorFailureClient()
        agent = LevelAssessmentAgent(client, FakeRecorder(), "assessment-1", prompt)
        context = SimpleNamespace(
            items=[
                SimpleNamespace(
                    role="user",
                    text_content="I go to the mosque to pray. I usually go with my mother. Done.",
                    id="turn-1",
                )
            ]
        )

        spoken = [part async for part in agent.llm_node(context, None, None)]

        self.assertEqual(0, client.state_reads)
        self.assertEqual("A1_PLACE_002:main", agent.current_prompt["prompt_id"])
        self.assertIsNotNone(agent._deferred_payload)
        self.assertIn("mosque", agent._deferred_payload["transcript"])
        self.assertTrue(any("answer is saved" in part for part in spoken))
        self.assertFalse(any("Tell me about one place" in part for part in spoken))
        self.assertFalse(any("Let's continue" in part for part in spoken))

    def test_client_does_not_duplicate_evaluator_503_when_retry_after_is_supplied(self) -> None:
        body = json.dumps(
            {
                "detail": "scoring unavailable",
                "error_code": "provider_daily_quota_exhausted",
                "retryable": True,
            }
        ).encode()
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8080/test",
            503,
            "Service Unavailable",
            {"Retry-After": "49"},
            io.BytesIO(body),
        )
        client = AssessmentClient(
            base_url="http://127.0.0.1:8080",
            token="test-token",
            timeout_seconds=1,
        )
        with (
            patch("urllib.request.urlopen", side_effect=error) as urlopen,
            self.assertRaises(AssessmentHTTPError) as raised,
        ):
            client._request("POST", "/test", payload={"x": 1}, retry_idempotently=True)

        self.assertEqual(1, urlopen.call_count)
        self.assertEqual(49.0, raised.exception.retry_after_seconds)


if __name__ == "__main__":
    unittest.main()
