from __future__ import annotations

from services.fluency import (
    FluencyMode,
    FluencyObservationRequest,
    FluencyObservationResult,
    extract_features,
    score_observation,
)

from .models import ResponseSubmission, SpeechMetrics


def fluency_request(
    session_id: str,
    submission: ResponseSubmission,
    *,
    target_level: str | None = None,
) -> FluencyObservationRequest:
    """Translate the assessment payload into the application-wide contract."""

    return FluencyObservationRequest(
        session_id=session_id,
        turn_id=submission.response_id,
        mode=FluencyMode.ASSESSMENT,
        transcript=submission.transcript,
        words=[word.model_dump(mode="json") for word in submission.words],
        response_started_at_ms=submission.response_started_at_ms,
        response_ended_at_ms=submission.response_ended_at_ms,
        completed=not submission.session_interrupted,
        assistance_count=(
            submission.prompt_repetitions + submission.clarification_requests
        ),
        target_level=target_level,
        explicit_audio_issue=submission.explicit_audio_issue,
        audio_issue_reason=submission.audio_issue_reason,
    )


def extract_fluency_observation(
    assessment_id: str,
    submission: ResponseSubmission,
    *,
    target_level: str | None = None,
) -> FluencyObservationResult:
    return score_observation(
        fluency_request(assessment_id, submission, target_level=target_level)
    )


def extract_speech_metrics(submission: ResponseSubmission) -> SpeechMetrics:
    """Backward-compatible evaluator view backed by the shared extractor."""

    features = extract_features(fluency_request("metrics-only", submission))
    return SpeechMetrics(
        word_count=features.word_count,
        response_duration_seconds=features.response_duration_seconds,
        speech_duration_seconds=features.speech_duration_seconds,
        speech_rate_wpm=features.speech_rate_wpm,
        pause_duration_seconds=features.pause_duration_seconds,
        pause_ratio=features.pause_ratio,
        mean_length_of_run_words=features.mean_length_of_run_words,
        long_pause_count=features.long_pause_count,
        max_inter_word_gap_seconds=features.max_inter_word_gap_seconds,
        response_start_latency_seconds=None,
        repeated_phrase_count=features.repeated_phrase_count,
        timing_source=(
            "estimated"
            if features.timing_source == "unavailable"
            else features.timing_source
        ),
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
