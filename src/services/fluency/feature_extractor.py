from __future__ import annotations

import math
import re
from collections import Counter
from itertools import pairwise

from .config import FluencySettings
from .models import FluencyFeatures, FluencyObservationRequest, FluencyWord

WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
SINGLE_FILLERS = {"uh", "um", "erm", "er", "ah", "hmm", "mm"}
SELF_CORRECTION_PATTERNS = (
    re.compile(r"\bi mean\b", re.IGNORECASE),
    re.compile(r"\bsorry[, ]", re.IGNORECASE),
    re.compile(r"\bor rather\b", re.IGNORECASE),
    re.compile(r"\blet me rephrase\b", re.IGNORECASE),
    re.compile(r"\bwhat i mean is\b", re.IGNORECASE),
)


def transcript_words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _ordered_words(request: FluencyObservationRequest) -> list[FluencyWord]:
    return sorted(request.words, key=lambda word: (word.start, word.end))


def _repeated_phrase_count(words: list[str]) -> int:
    lowered = [word.lower() for word in words]
    repeats = 0
    for size in (2, 3, 4):
        phrases = Counter(
            tuple(lowered[index : index + size])
            for index in range(len(lowered) - size + 1)
        )
        repeats += sum(count - 1 for count in phrases.values() if count > 1)
    return repeats


def _immediate_repeat_count(words: list[str]) -> int:
    lowered = [word.lower() for word in words]
    return sum(current == previous for previous, current in pairwise(lowered))


def _filler_count(words: list[str]) -> int:
    lowered = [word.lower() for word in words]
    singles = sum(word in SINGLE_FILLERS for word in lowered)
    joined = " ".join(lowered)
    # These are counted only as exact multi-word discourse markers. The common
    # content word "like" is deliberately excluded to reduce false penalties.
    phrases = len(re.findall(r"\byou know\b", joined)) + len(
        re.findall(r"\bkind of\b|\bsort of\b", joined)
    )
    return singles + phrases


def _pace_stability(words: list[FluencyWord], pause_threshold: float) -> float | None:
    if len(words) < 8:
        return None
    runs: list[tuple[float, int]] = []
    run_start = words[0].start
    run_words = 1
    for previous, current in pairwise(words):
        if current.start - previous.end > pause_threshold:
            duration = max(0.2, previous.end - run_start)
            runs.append((duration, run_words))
            run_start = current.start
            run_words = 1
        else:
            run_words += 1
    runs.append((max(0.2, words[-1].end - run_start), run_words))
    if len(runs) < 2:
        return 1.0
    rates = [count / (duration / 60.0) for duration, count in runs]
    mean = sum(rates) / len(rates)
    if mean <= 0:
        return None
    variance = sum((rate - mean) ** 2 for rate in rates) / len(rates)
    coefficient = math.sqrt(variance) / mean
    return round(max(0.0, min(1.0, 1.0 - coefficient)), 4)


def extract_features(
    request: FluencyObservationRequest,
    settings: FluencySettings | None = None,
) -> FluencyFeatures:
    settings = settings or FluencySettings.from_env()
    recognized = _ordered_words(request)
    tokens = transcript_words(request.transcript)
    word_count = len(recognized) if recognized else len(tokens)

    window_duration = 0.0
    if request.response_started_at_ms is not None and request.response_ended_at_ms is not None:
        window_duration = max(
            0.0,
            (request.response_ended_at_ms - request.response_started_at_ms) / 1000.0,
        )

    if recognized:
        response_duration = max(0.0, recognized[-1].end - recognized[0].start)
        gaps = [
            max(0.0, current.start - previous.end)
            for previous, current in pairwise(recognized)
        ]
        timing_source = "word_timestamps"
    elif window_duration > 0:
        response_duration = window_duration
        gaps = []
        timing_source = "response_window"
    else:
        response_duration = 0.0
        gaps = []
        timing_source = "unavailable"

    pause_gaps = [gap for gap in gaps if gap > settings.pause_threshold_seconds]
    pause_duration = min(response_duration, sum(pause_gaps))
    active_duration = max(0.0, response_duration - pause_duration)
    speech_rate = word_count / (response_duration / 60.0) if response_duration else 0.0
    articulation_rate = word_count / (active_duration / 60.0) if active_duration else 0.0

    runs: list[int] = []
    if recognized:
        run = 1
        for gap in gaps:
            if gap > settings.pause_threshold_seconds:
                runs.append(run)
                run = 1
            else:
                run += 1
        runs.append(run)
    elif word_count:
        runs = [word_count]

    minutes = response_duration / 60.0
    pause_count = len(pause_gaps)
    long_pause_count = sum(gap > settings.long_pause_threshold_seconds for gap in gaps)
    filler_count = _filler_count(tokens)
    immediate_repeats = _immediate_repeat_count(tokens)
    self_corrections = sum(len(pattern.findall(request.transcript)) for pattern in SELF_CORRECTION_PATTERNS)

    return FluencyFeatures(
        word_count=word_count,
        response_duration_seconds=round(response_duration, 3),
        speech_duration_seconds=round(active_duration, 3),
        speech_rate_wpm=round(speech_rate, 2),
        articulation_rate_wpm=round(articulation_rate, 2),
        pace_stability=_pace_stability(recognized, settings.pause_threshold_seconds),
        pause_count=pause_count,
        pauses_per_minute=round(pause_count / minutes, 2) if minutes else 0.0,
        pause_duration_seconds=round(pause_duration, 3),
        pause_ratio=round(pause_duration / response_duration, 4) if response_duration else 0.0,
        phonation_ratio=round(active_duration / response_duration, 4) if response_duration else 0.0,
        mean_length_of_run_words=round(sum(runs) / len(runs), 2) if runs else 0.0,
        longest_run_words=max(runs, default=0),
        long_pause_count=long_pause_count,
        long_pauses_per_minute=round(long_pause_count / minutes, 2) if minutes else 0.0,
        max_inter_word_gap_seconds=round(max(gaps, default=0.0), 3),
        filler_count=filler_count,
        fillers_per_100_words=round(filler_count / word_count * 100.0, 2)
        if word_count
        else 0.0,
        immediate_repeat_count=immediate_repeats,
        repeated_phrase_count=_repeated_phrase_count(tokens),
        self_correction_count=self_corrections,
        timing_source=timing_source,
    )
