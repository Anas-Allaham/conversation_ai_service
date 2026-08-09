from __future__ import annotations

from itertools import pairwise

from .config import FluencySettings
from .feature_extractor import extract_features
from .models import (
    FluencyConfidence,
    FluencyEvidenceCount,
    FluencyFeatures,
    FluencyObservationRequest,
    FluencyObservationResult,
    FluencyScoreStatus,
    FluencySubscores,
)

FLUENCY_SCORER_VERSION = "fluency-v0.1"
WEIGHTS = {"speed": 0.30, "breakdown": 0.40, "continuity": 0.20, "repair": 0.10}
ASSESSMENT_LEVEL_ANCHORS = {"A1": 30, "A2": 45, "B1": 60, "B2": 75}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _interpolate(value: float, points: list[tuple[float, float]]) -> float:
    if value <= points[0][0]:
        return points[0][1]
    for (left_x, left_y), (right_x, right_y) in pairwise(points):
        if value <= right_x:
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)
    return points[-1][1]


def _subscores(features: FluencyFeatures, request: FluencyObservationRequest) -> FluencySubscores:
    speech_rate_score = _interpolate(
        features.speech_rate_wpm,
        [(0, 0), (30, 20), (50, 45), (70, 70), (90, 90), (110, 100), (170, 100), (210, 75), (250, 40)],
    )
    articulation_score = _interpolate(
        features.articulation_rate_wpm,
        [(0, 0), (60, 30), (90, 65), (120, 90), (150, 100), (220, 100), (260, 75), (300, 45)],
    )
    stability_score = (
        100.0 if features.pace_stability is None else features.pace_stability * 100.0
    )
    speed = 0.55 * speech_rate_score + 0.30 * articulation_score + 0.15 * stability_score

    pause_ratio_score = 100.0 * (
        1.0 - _clamp((features.pause_ratio - 0.08) / 0.55, 0.0, 1.0)
    )
    long_pause_score = 100.0 - min(100.0, features.long_pauses_per_minute * 18.0)
    pause_frequency_score = 100.0 - min(
        100.0, max(0.0, features.pauses_per_minute - 2.0) * 7.0
    )
    breakdown = (
        0.55 * pause_ratio_score + 0.30 * long_pause_score + 0.15 * pause_frequency_score
    )

    mean_run_score = _interpolate(
        features.mean_length_of_run_words,
        [(0, 0), (1, 10), (2, 30), (4, 55), (6, 72), (9, 88), (13, 100)],
    )
    longest_run_score = _interpolate(
        float(features.longest_run_words),
        [(0, 0), (2, 20), (4, 45), (7, 70), (11, 90), (16, 100)],
    )
    completion_score = 100.0 if request.completed else 35.0
    completion_score -= min(60.0, request.assistance_count * 15.0)
    continuity = 0.50 * mean_run_score + 0.30 * longest_run_score + 0.20 * completion_score

    repeats_per_100 = (
        (features.immediate_repeat_count + features.repeated_phrase_count)
        / features.word_count
        * 100.0
        if features.word_count
        else 0.0
    )
    corrections_per_100 = (
        features.self_correction_count / features.word_count * 100.0
        if features.word_count
        else 0.0
    )
    # Repair has the smallest overall weight. Successful self-correction is a
    # weak penalty because it can demonstrate control rather than breakdown.
    repair = 100.0
    repair -= min(55.0, features.fillers_per_100_words * 3.0)
    repair -= min(35.0, repeats_per_100 * 4.0)
    repair -= min(15.0, corrections_per_100 * 1.5)

    return FluencySubscores(
        speed=round(_clamp(speed)),
        breakdown=round(_clamp(breakdown)),
        continuity=round(_clamp(continuity)),
        repair=round(_clamp(repair)),
    )


def _feedback(features: FluencyFeatures, subscores: FluencySubscores) -> list[str]:
    values = subscores.model_dump()
    strongest = max(values, key=values.get)
    weakest = min(values, key=values.get)
    strengths = {
        "speed": f"Your speaking pace was functional at about {features.speech_rate_wpm:.0f} words per minute.",
        "breakdown": "Most of the response remained connected without excessive disruptive silence.",
        "continuity": f"You sustained an average run of {features.mean_length_of_run_words:.1f} words between qualifying pauses.",
        "repair": "Fillers and repeated phrases did not dominate the response.",
    }
    development = {
        "speed": "Aim for a steadier functional pace; speaking faster by itself is not the goal.",
        "breakdown": f"Work on reducing disruptive pauses; {features.long_pause_count} pause(s) exceeded the long-pause threshold.",
        "continuity": "Try linking two or three ideas before stopping so your speech runs become longer.",
        "repair": "Plan the next short phrase before speaking to reduce fillers and repeated starts.",
    }
    return [
        strengths[strongest],
        development[weakest],
        "This score measures delivery flow, not grammar, pronunciation accuracy, or accent.",
    ]


def _evidence(features: FluencyFeatures, eligible: bool) -> FluencyEvidenceCount:
    timestamped = int(features.timing_source == "word_timestamps")
    return FluencyEvidenceCount(
        eligible_turns=int(eligible),
        total_turns=1,
        total_words=features.word_count,
        learner_speech_seconds=features.speech_duration_seconds,
        timestamped_turns=timestamped,
        timestamp_coverage=float(timestamped),
    )


def _insufficiency_reasons(
    request: FluencyObservationRequest,
    features: FluencyFeatures,
    settings: FluencySettings,
) -> list[str]:
    reasons: list[str] = []
    if request.explicit_audio_issue:
        reasons.append(request.audio_issue_reason or "The audio was marked unusable.")
    if features.timing_source != "word_timestamps":
        reasons.append("Word-level timestamps were unavailable.")
    if features.word_count < settings.minimum_turn_words:
        reasons.append(
            f"The turn contained fewer than {settings.minimum_turn_words} timed words."
        )
    if features.response_duration_seconds < settings.minimum_turn_seconds:
        reasons.append(
            f"The turn contained less than {settings.minimum_turn_seconds:.1f} seconds of timed evidence."
        )
    return reasons


def score_observation(
    request: FluencyObservationRequest,
    settings: FluencySettings | None = None,
) -> FluencyObservationResult:
    settings = settings or FluencySettings.from_env()
    features = extract_features(request, settings)
    reasons = _insufficiency_reasons(request, features, settings)
    invalid = request.explicit_audio_issue
    eligible = not reasons
    status = (
        FluencyScoreStatus.INVALID_AUDIO
        if invalid
        else FluencyScoreStatus.SCORED
        if eligible
        else FluencyScoreStatus.INSUFFICIENT_EVIDENCE
    )

    if not eligible:
        return FluencyObservationResult(
            session_id=request.session_id,
            turn_id=request.turn_id,
            mode=request.mode,
            status=status,
            eligible=False,
            confidence=FluencyConfidence.LOW,
            evidence_count=_evidence(features, False),
            features=features,
            feedback=["More connected speech with usable word timings is needed before scoring."],
            insufficiency_reasons=reasons,
        )

    subscores = _subscores(features, request)
    values = subscores.model_dump()
    index = round(sum(values[name] * weight for name, weight in WEIGHTS.items()))
    confidence = (
        FluencyConfidence.MEDIUM
        if features.word_count >= 12 and features.response_duration_seconds >= 8.0
        else FluencyConfidence.LOW
    )
    return FluencyObservationResult(
        session_id=request.session_id,
        turn_id=request.turn_id,
        mode=request.mode,
        status=FluencyScoreStatus.SCORED,
        eligible=True,
        fluency_index=index,
        confidence=confidence,
        evidence_count=_evidence(features, True),
        features=features,
        subscores=subscores,
        feedback=_feedback(features, subscores),
    )


def cefr_estimate_from_index(index: int) -> str:
    demonstrated = "Pre-A1"
    for level, threshold in ASSESSMENT_LEVEL_ANCHORS.items():
        if index >= threshold:
            demonstrated = level
    return demonstrated


def assessment_dimension_score(observation: FluencyObservationResult, target_level: str) -> int | None:
    """Map an explainable index to the assessment's 0-4 target-level rubric.

    The anchors are provisional engineering thresholds. They are versioned and
    must be replaced by human calibration when labeled application data exists.
    """

    if observation.status != FluencyScoreStatus.SCORED or observation.fluency_index is None:
        return None
    threshold = ASSESSMENT_LEVEL_ANCHORS[target_level]
    difference = observation.fluency_index - threshold
    if difference >= 12:
        return 4
    if difference >= 0:
        return 3
    if difference >= -12:
        return 2
    if difference >= -24:
        return 1
    return 0
