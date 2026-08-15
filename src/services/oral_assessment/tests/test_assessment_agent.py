from __future__ import annotations

import unittest

from app.realtime.assessment_agent import LevelAssessmentAgent


def prompt(level: str, identifier: str) -> dict:
    return {
        "prompt_id": f"{identifier}:main",
        "item_id": identifier,
        "target_level": level,
        "prompt_kind": "main",
        "prompt": "Answer the next assessment question.",
        "clarification_prompt": "Give a direct answer to the question.",
        "response_limit_seconds": 60,
        "prompt_repetitions_allowed": 1,
        "preparation_seconds": 5,
        "reference_text": None,
    }


class FakeClient:
    def __init__(self, state: dict | None = None, submit_result: dict | None = None) -> None:
        self.state = state or {}
        self.submit_result = submit_result
        self.submissions: list[tuple[str, dict]] = []

    async def get_assessment_state_async(self, assessment_id: str) -> dict:
        return self.state

    async def submit_response_async(self, assessment_id: str, payload: dict) -> dict:
        self.submissions.append((assessment_id, payload))
        if self.submit_result is None:
            raise AssertionError("No submit result configured")
        return self.submit_result


class AssessmentAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_prompt_never_announces_internal_level_section(self) -> None:
        agent = LevelAssessmentAgent(
            FakeClient(),
            object(),
            "assessment-1",
            prompt("A1", "A1_ROUTINE_001"),
        )
        spoken = await agent._next_spoken_text(
            {
                "next_action": {"prompt": prompt("A2", "A2_TRAVEL_002")},
                "progress": {"current_section": "A2"},
            }
        )
        self.assertIn("Answer the next assessment question", spoken)
        self.assertNotIn("A2 section", spoken)
        self.assertNotIn("You are now", spoken)

    async def test_stale_prompt_recovers_from_backend_state_without_restart(self) -> None:
        current = prompt("B1", "B1_TEAMWORK_001")
        client = FakeClient(
            {
                "record": {"status": "in_progress"},
                "current_prompt": current,
                "progress": {"current_section": "B1"},
            }
        )
        agent = LevelAssessmentAgent(
            client,
            object(),
            "assessment-2",
            prompt("A2", "A2_TRAVEL_002"),
        )
        spoken = await agent._recover_session_state()
        self.assertEqual(current["prompt_id"], agent.current_prompt["prompt_id"])
        self.assertIn("Let's continue", spoken)
        self.assertNotIn("restart", spoken.lower())
        self.assertNotIn("out of sync", spoken.lower())

    async def test_deferred_payload_retries_the_exact_saved_response(self) -> None:
        next_prompt = prompt("A2", "A2_TRAVEL_002")
        client = FakeClient(
            submit_result={"next_action": {"prompt": next_prompt}}
        )
        agent = LevelAssessmentAgent(
            client,
            object(),
            "assessment-3",
            prompt("A1", "A1_ROUTINE_001"),
        )
        payload = {
            "response_id": "response-saved",
            "idempotency_key": "livekit-response-saved",
            "prompt_id": "A1_ROUTINE_001:main",
            "item_id": "A1_ROUTINE_001",
            "prompt_kind": "main",
            "transcript": "This exact answer must be retried without asking the learner again.",
        }
        agent._defer_submission(payload)

        spoken = await agent._retry_deferred_submission()

        self.assertEqual([("assessment-3", payload)], client.submissions)
        self.assertIsNone(agent._deferred_payload)
        self.assertEqual(next_prompt["prompt_id"], agent.current_prompt["prompt_id"])
        self.assertIn("Answer the next assessment question", spoken)


if __name__ == "__main__":
    unittest.main()
