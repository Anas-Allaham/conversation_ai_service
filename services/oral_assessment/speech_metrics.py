from __future__ import annotations

import re
from collections import Counter

from .models import ResponseSubmission, SpeechMetrics, WordTiming


WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")


def transcript_words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _ordered_words(submission: ResponseSubmission) -> list[WordTiming]:
    return sorted(submission.words, key=lambda word: (word.start, word.end))


def _repeated_phrase_count(words: list[str]) -> int:
    lowered = [word.lower() for word in words]
    repeats = 0
    for size in (2, 3, 4):
        phrases = Counter(tuple(lowered[index : index + size]) for index in range(len(lowered) - size + 1))
        repeats += sum(count - 1 for count in phrases.values() if count > 1)
    return repeats


def extract_speech_metrics(submission: ResponseSubmission) -> SpeechMetrics:
    recognized = _ordered_words(submission)
    tokens = transcript_words(submission.transcript)
    word_count = len(tokens) if tokens else len(recognized)

    window_duration: float | None = None
    if submission.response_started_at_ms is not None and submission.response_ended_at_ms is not None:
        window_duration = max(0.0, (submission.response_ended_at_ms - submission.response_started_at_ms) / 1000.0)

    if recognized:
        timed_duration = max(0.0, recognized[-1].end - recognized[0].start)
        speech_duration = sum(max(0.0, word.end - word.start) for word in recognized)
        gaps = [max(0.0, current.start - previous.end) for previous, current in zip(recognized, recognized[1:])]
        response_duration = window_duration if window_duration and window_duration > 0 else timed_duration
        timing_source = "word_timestamps"
    elif window_duration is not None and window_duration > 0:
        response_duration = window_duration
        speech_duration = min(response_duration, word_count * 0.32)
        gaps = []
        timing_source = "response_window"
    else:
        response_duration = word_count / 1.65 if word_count else 0.0
        speech_duration = response_duration
        gaps = []
        timing_source = "estimated"

    pause_gaps = [gap for gap in gaps if gap > 0.5]
    pause_duration = sum(pause_gaps)
    if recognized and response_duration > timed_duration:
        pause_duration += response_duration - timed_duration
    pause_duration = min(response_duration, max(0.0, pause_duration))
    pause_ratio = pause_duration / response_duration if response_duration else 0.0
    speech_rate = word_count / (response_duration / 60.0) if response_duration else 0.0

    runs: list[int] = []
    if word_count:
        run = 1
        for gap in gaps:
            if gap > 0.5:
                runs.append(run)
                run = 1
            else:
                run += 1
        runs.append(run)

    return SpeechMetrics(
        word_count=word_count,
        response_duration_seconds=round(response_duration, 3),
        speech_duration_seconds=round(max(0.0, speech_duration), 3),
        speech_rate_wpm=round(speech_rate, 2),
        pause_duration_seconds=round(pause_duration, 3),
        pause_ratio=round(min(1.0, pause_ratio), 4),
        mean_length_of_run_words=round(sum(runs) / len(runs), 2) if runs else 0.0,
        long_pause_count=sum(gap > 1.5 for gap in gaps),
        max_inter_word_gap_seconds=round(max(gaps, default=0.0), 3),
        response_start_latency_seconds=None,
        repeated_phrase_count=_repeated_phrase_count(tokens),
        timing_source=timing_source,
    )


def invalid_audio_reason(submission: ResponseSubmission, metrics: SpeechMetrics) -> str | None:
    """Return an audio-validity reason without treating ASR confidence as proficiency."""
    if submission.explicit_audio_issue:
        return submission.audio_issue_reason or "The client marked the audio as unusable."
    if metrics.word_count == 0 and metrics.speech_duration_seconds < 0.5:
        return "No usable speech evidence was captured."
    if not submission.transcript.strip() and not submission.words:
        return "No transcript or word-timing evidence was captured."
    return None

