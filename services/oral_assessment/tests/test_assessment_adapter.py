from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from app.realtime.assessment_payload import (
    extract_words,
    valid_submission_words,
)
from app.realtime.assessment_turns import assessment_endpointing_options
@dataclass
class FakeTimedString:
    text: str
    start_time: float
    end_time: float
    confidence: float | None = None


class AssessmentAdapterTests(unittest.TestCase):
    def test_livekit_timed_strings_keep_text_and_rebase_timings(self) -> None:
        words = extract_words(
            [
                FakeTimedString("Clear", 12.0, 12.4, 0.98),
                FakeTimedString("voices", 12.5, 13.0, 0.96),
            ]
        )
        self.assertEqual(["Clear", "voices"], [word["word"] for word in words])
        self.assertEqual(0.0, words[0]["start"])
        self.assertAlmostEqual(1.0, words[1]["end"])

    def test_mapping_words_are_normalized_and_empty_entries_removed(self) -> None:
        words = extract_words(
            [
                {"word": "", "start": 0.0, "end": 0.1},
                {"text": "sunlight", "start_time": 2.0, "end_time": 2.5},
                {"punctuated_word": "enters.", "start": 2.6, "end": 3.0},
            ]
        )
        self.assertEqual(["sunlight", "enters."], [word["word"] for word in words])

    def test_service_boundary_can_never_emit_empty_words(self) -> None:
        words = valid_submission_words(
            [
                {"word": "", "start": 0.0, "end": 0.1},
                {"word": "brush", "start": 0.1, "end": 0.4},
                object(),
            ]
        )
        self.assertEqual(1, len(words))
        self.assertEqual("brush", words[0]["word"])

    def test_assessment_endpointing_is_deliberately_more_patient(self) -> None:
        environment = {
            "ASSESSMENT_ENDPOINTING_MODE": "fixed",
            "ASSESSMENT_ENDPOINTING_MIN_DELAY_SECONDS": "1.5",
            "ASSESSMENT_ENDPOINTING_MAX_DELAY_SECONDS": "4.0",
        }
        with patch.dict(os.environ, environment, clear=False):
            options = assessment_endpointing_options()
        self.assertEqual("fixed", options["mode"])
        self.assertEqual(1.5, options["min_delay"])
        self.assertEqual(4.0, options["max_delay"])

if __name__ == "__main__":
    unittest.main()
