from __future__ import annotations

import unittest

from app.realtime.assessment_turns import (
    PendingResponse,
    control_intent,
    learner_result_announcement,
    spoken_prompt,
    strip_optional_completion_marker,
)


class AssessmentTurnTests(unittest.TestCase):
    def test_clarification_request_is_not_an_assessment_answer(self) -> None:
        self.assertEqual("clarify", control_intent("Can you explain the question again?"))
        self.assertEqual("repeat", control_intent("Could you repeat the question?"))
        self.assertEqual("thinking", control_intent("Give me a moment to think."))
        self.assertEqual(
            "answer",
            control_intent("I asked my teacher to explain the problem, and then I solved it."),
        )

    def test_optional_done_marker_is_removed_from_an_answer(self) -> None:
        text, done = strip_optional_completion_marker(
            "I would choose the conversation club because it is more social. I'm done."
        )
        self.assertTrue(done)
        self.assertEqual(
            "I would choose the conversation club because it is more social.",
            text,
        )

    def test_committed_fragments_are_merged_before_submission(self) -> None:
        pending = PendingResponse()
        first_generation = pending.add(
            prompt_id="A2_TRAVEL_002:main",
            turn_id="turn-1",
            transcript="Excuse me. Can I have a ticket to Aleppo?",
            words=[{"word": "Excuse", "start": 0.0, "end": 0.4}],
            confidence=0.90,
            response_started_at_ms=1_000,
        )
        pending.add(
            prompt_id="A2_TRAVEL_002:main",
            turn_id="turn-2",
            transcript="When does the bus leave?",
            words=[{"word": "When", "start": 0.0, "end": 0.3}],
            confidence=0.80,
            response_started_at_ms=4_000,
        )
        final_generation = pending.add(
            prompt_id="A2_TRAVEL_002:main",
            turn_id="turn-3",
            transcript="I am in a hurry.",
            words=[{"word": "I", "start": 0.0, "end": 0.2}],
            confidence=0.85,
            response_started_at_ms=7_000,
        )
        self.assertFalse(pending.claim(first_generation))
        self.assertTrue(pending.claim(final_generation))
        self.assertFalse(pending.claim(final_generation))
        self.assertEqual(
            "Excuse me. Can I have a ticket to Aleppo? When does the bus leave? I am in a hurry.",
            pending.transcript,
        )
        self.assertEqual(1_000, pending.response_started_at_ms)
        self.assertAlmostEqual(0.85, pending.confidence or 0.0)
        self.assertLess(pending.words[0]["end"], pending.words[1]["start"])
        self.assertLess(pending.words[1]["end"], pending.words[2]["start"])

    def test_spoken_result_contains_only_placement_confidence_and_fluency(self) -> None:
        spoken = learner_result_announcement(
            {
                "confirmed_level": "B1",
                "confidence": "high",
                "confidence_score": 92,
                "profile": {
                    "task_achievement": "B1",
                    "interactive_communication": "B1",
                    "fluency": "B2",
                    "coherence": "B1",
                    "lexical_adequacy": "B1",
                    "intelligibility": "B2",
                },
                "next_level_result": "B2 was not yet demonstrated",
            }
        )
        self.assertIn("conversational English level is B1", spoken)
        self.assertIn("evidence confidence is high", spoken)
        self.assertIn("fluency is assessed at B2", spoken)
        self.assertNotIn("92", spoken)
        self.assertNotIn("task achievement", spoken)
        self.assertNotIn("Grammar", spoken)
        self.assertNotIn("B2 was not yet demonstrated", spoken)

    def test_prompt_preparation_is_explicit_but_not_forced(self) -> None:
        spoken = spoken_prompt(
            {
                "prompt": "Compare the two options.",
                "prompt_kind": "main",
                "preparation_seconds": 15,
            }
        )
        self.assertIn("up to 15 seconds", spoken)
        self.assertIn("Start when you are ready", spoken)


if __name__ == "__main__":
    unittest.main()
