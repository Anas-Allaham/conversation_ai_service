from __future__ import annotations

from collections import defaultdict

from .models import (
    LEVELS,
    AssessmentRecord,
    AssessmentResult,
    AssessmentStatistics,
    CEFRLevel,
    PromptKind,
    PronunciationDiagnostic,
    ResponseDecision,
    ResultConfidence,
    StoredResponse,
)

DISCLAIMER = (
    "This is a CEFR-aligned conversational interaction placement estimate, not an official CEFR "
    "certificate or a complete English proficiency score. Grammar, reading, and writing are not "
    "independently assessed. Pronunciation diagnostics do not mathematically change the conversational result."
)


def _level_index(level: CEFRLevel) -> int:
    return LEVELS.index(level)


def _profile(record: AssessmentRecord, responses: list[StoredResponse]) -> dict[str, str]:
    dimensions = (
        "task_achievement",
        "interactive_communication",
        "fluency",
        "coherence",
        "lexical_adequacy",
        "intelligibility",
    )
    valid = [
        response
        for response in responses
        if response.scored
        and response.scored.decision != ResponseDecision.INVALID_AUDIO
        and response.submission.prompt_kind in {PromptKind.MAIN, PromptKind.FOLLOW_UP, PromptKind.TIE_BREAKER}
    ]
    if not valid:
        fallback = "Not determined" if record.completion_reason == "audio_unusable" else "Pre-A1"
        return {dimension: fallback for dimension in dimensions}

    profile: dict[str, str] = {}
    for dimension in dimensions:
        per_level: dict[CEFRLevel, list[int]] = defaultdict(list)
        for response in valid:
            assert response.scored is not None
            target = CEFRLevel(response.scored.model_extra["target_level"]) if response.scored.model_extra and "target_level" in response.scored.model_extra else None
            if target is None:
                item_prefix = response.submission.item_id[:2]
                target = CEFRLevel(item_prefix)
            per_level[target].append(getattr(response.scored.scores, dimension))
        demonstrated = "Pre-A1"
        for level in LEVELS:
            scores = per_level.get(level, [])
            if scores and sum(scores) / len(scores) >= 3.0:
                demonstrated = level.value
        profile[dimension] = demonstrated
    return profile


def _confidence_score(record: AssessmentRecord, responses: list[StoredResponse]) -> int:
    scored = [response.scored for response in responses if response.scored]
    if record.completion_reason in {"audio_unusable", "cancelled", "evaluator_unavailable"}:
        return 25
    # This index describes evidence sufficiency; it is deliberately capped
    # below 100 because the MVP has not undergone psychometric calibration.
    score = 95
    score -= min(40, record.invalid_audio_count * 20)
    score -= min(20, record.tie_breaker_count * 10)
    score -= min(40, record.evaluator_failure_count * 25)
    if any(item and item.used_fallback for item in scored):
        score -= 20
    if any(item and item.evaluator_confidence == "low" for item in scored):
        score -= 20
    elif any(item and item.evaluator_confidence == "medium" for item in scored):
        score -= 10
    if any(item and item.decision == ResponseDecision.BORDERLINE for item in scored):
        score -= 10
    if any(response.submission.session_interrupted for response in responses):
        score -= 15
    if record.first_unconfirmed_level is None:
        score -= 20

    valid_observations = sum(
        1
        for response in responses
        if response.scored
        and response.scored.decision != ResponseDecision.INVALID_AUDIO
        and response.submission.prompt_kind
        in {PromptKind.MAIN, PromptKind.FOLLOW_UP, PromptKind.TIE_BREAKER}
    )
    evidence_caps = {0: 25, 1: 35, 2: 50, 3: 60, 4: 70, 5: 80, 6: 85, 7: 90}
    evidence_cap = evidence_caps.get(valid_observations, 95)
    return max(0, min(100, score, evidence_cap))


def _confidence(score: int) -> ResultConfidence:
    if score >= 85:
        return ResultConfidence.HIGH
    if score >= 55:
        return ResultConfidence.MEDIUM
    return ResultConfidence.LOW


def _profile_scores_percent(responses: list[StoredResponse]) -> dict[str, int]:
    dimensions = (
        "task_achievement",
        "interactive_communication",
        "fluency",
        "coherence",
        "lexical_adequacy",
        "intelligibility",
    )
    valid = [
        response
        for response in responses
        if response.scored
        and response.scored.decision != ResponseDecision.INVALID_AUDIO
        and response.submission.prompt_kind
        in {PromptKind.MAIN, PromptKind.FOLLOW_UP, PromptKind.TIE_BREAKER}
    ]
    if not valid:
        return {dimension: 0 for dimension in dimensions}
    return {
        dimension: round(
            sum(getattr(response.scored.scores, dimension) for response in valid if response.scored)
            / len(valid)
            * 25
        )
        for dimension in dimensions
    }


def _statistics(record: AssessmentRecord, responses: list[StoredResponse]) -> AssessmentStatistics:
    completed_at = record.completed_at or record.updated_at
    duration = max(0.0, (completed_at - record.created_at).total_seconds())
    return AssessmentStatistics(
        duration_seconds=round(duration, 3),
        responses_submitted=len(responses),
        scored_responses=sum(1 for response in responses if response.scored),
        invalid_audio_responses=sum(
            1
            for response in responses
            if response.scored and response.scored.decision == ResponseDecision.INVALID_AUDIO
        ),
        prompt_repetitions=sum(response.submission.prompt_repetitions for response in responses),
        clarification_requests=sum(
            response.submission.clarification_requests for response in responses
        ),
        tie_breakers_used=record.tie_breaker_count,
    )


def _validity_warnings(
    record: AssessmentRecord,
    responses: list[StoredResponse],
) -> list[str]:
    warnings: list[str] = []
    if record.boundary_verification_levels:
        levels = ", ".join(level.value for level in record.boundary_verification_levels)
        warnings.append(f"A different same-level boundary task was required at: {levels}.")
    if record.invalid_audio_count:
        warnings.append(
            f"{record.invalid_audio_count} response(s) had unusable audio and were not scored downward."
        )
    if record.evaluator_failure_count:
        warnings.append(
            f"The external evaluator failed {record.evaluator_failure_count} time(s) before recovery."
        )
    if any(
        response.scored and response.scored.evaluator_confidence == "low"
        for response in responses
    ):
        warnings.append("At least one response received low evaluator confidence.")
    if any(response.submission.session_interrupted for response in responses):
        warnings.append("The assessment contained an interrupted response.")
    return warnings


def build_result(
    record: AssessmentRecord,
    responses: list[StoredResponse],
    pronunciation: PronunciationDiagnostic | None,
) -> AssessmentResult:
    if record.completion_reason == "audio_unusable" and record.highest_confirmed_level is None:
        confirmed: CEFRLevel | str = "Not determined"
    elif record.highest_confirmed_level is None:
        confirmed = "Pre-A1"
    else:
        confirmed = record.highest_confirmed_level
    ceiling = record.highest_confirmed_level == CEFRLevel.B2 and record.first_unconfirmed_level is None
    confidence_score = _confidence_score(record, responses)
    confidence = _confidence(confidence_score)
    if ceiling:
        next_level_result = "B2 was demonstrated and the assessment ceiling was reached"
    elif record.first_unconfirmed_level is not None:
        next_level_result = f"{record.first_unconfirmed_level.value} was not yet demonstrated"
    else:
        next_level_result = "No higher-level boundary was established"
    confirmed_text = confirmed.value if isinstance(confirmed, CEFRLevel) else str(confirmed)
    profile = _profile(record, responses)
    summary = (
        f"{confirmed_text} conversational interaction placement with {confidence.value} confidence. "
        f"Fluency was assessed at {profile['fluency']}. {next_level_result}."
    )
    return AssessmentResult(
        assessment_id=record.assessment_id,
        status=record.status,
        result_name="CEFR-aligned Conversational Interaction Placement",
        confirmed_level=confirmed,
        first_unconfirmed_level=record.first_unconfirmed_level,
        ceiling_reached=ceiling,
        confidence=confidence,
        confidence_score=confidence_score,
        confidence_score_interpretation=(
            "Deterministic evidence-sufficiency index, not a calibrated probability that the level is correct."
        ),
        profile=profile,
        profile_scores_percent=_profile_scores_percent(responses),
        next_level_result=next_level_result,
        summary=summary,
        statistics=_statistics(record, responses),
        grammar_assessed=False,
        pronunciation_diagnostic=pronunciation or PronunciationDiagnostic(status="not_requested"),
        versions=record.versions,
        disclaimer=DISCLAIMER,
        validity_warnings=_validity_warnings(record, responses),
        completed_at=record.completed_at,
        completion_reason=record.completion_reason or "placement_complete",
    )
