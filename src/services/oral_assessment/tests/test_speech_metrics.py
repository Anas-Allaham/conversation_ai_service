from __future__ import annotations

import unittest

from services.oral_assessment.models import PromptKind, ResponseSubmission, WordTiming
from services.oral_assessment.speech_metrics import extract_speech_metrics, invalid_audio_reason


class SpeechMetricTests(unittest.TestCase):
    def test_response_submission_drops_empty_provider_words(self) -> None:
        submission = ResponseSubmission(
            response_id="response-provider-shape",
            idempotency_key="idempotency-provider-shape",
            prompt_id="CALIBRATION:1",
            item_id="CALIBRATION",
            prompt_kind=PromptKind.CALIBRATION,
            transcript="Clear voices are easy to hear.",
            words=[
                {"word": "", "start": 0.0, "end": 0.1},
                {"text": "Clear", "start_time": 0.1, "end_time": 0.4},
                {"word": "voices", "start": 0.5, "end": 0.9},
            ],
        )
        self.assertEqual(["Clear", "voices"], [word.word for word in submission.words])

    def test_word_timestamps_produce_pause_evidence(self) -> None:
        submission = ResponseSubmission(
            response_id="response-1",
            idempotency_key="idempotency-1",
            prompt_id="A1:item",
            item_id="A1_ITEM",
            prompt_kind=PromptKind.MAIN,
            transcript="I study English every day",
            words=[
                WordTiming(word="I", start=0.0, end=0.2),
                WordTiming(word="study", start=0.25, end=0.6),
                WordTiming(word="English", start=2.3, end=2.8),
                WordTiming(word="every", start=2.9, end=3.2),
                WordTiming(word="day", start=3.3, end=3.5),
            ],
        )
        metrics = extract_speech_metrics(submission)
        self.assertEqual(5, metrics.word_count)
        self.assertEqual(1, metrics.long_pause_count)
        self.assertGreater(metrics.pause_ratio, 0)
        self.assertEqual("word_timestamps", metrics.timing_source)

    def test_low_asr_confidence_alone_is_not_invalid_audio(self) -> None:
        submission = ResponseSubmission(
            response_id="response-2",
            idempotency_key="idempotency-2",
            prompt_id="A1:item",
            item_id="A1_ITEM",
            prompt_kind=PromptKind.MAIN,
            transcript="My answer is understandable.",
            asr_confidence=0.10,
        )
        metrics = extract_speech_metrics(submission)
        self.assertIsNone(invalid_audio_reason(submission, metrics))


if __name__ == "__main__":
    unittest.main()
