from __future__ import annotations

from collections.abc import Sequence

from .config import FluencySettings
from .models import (
    FluencyConfidence,
    FluencyEvidenceCount,
    FluencyMode,
    FluencyObservationResult,
    FluencyScoreStatus,
    FluencySessionResult,
    FluencySubscores,
)
from .scorer import cefr_estimate_from_index


def _evidence(observations: Sequence[FluencyObservationResult]) -> FluencyEvidenceCount:
    eligible = [item for item in observations if item.eligible]
    timestamped = sum(item.evidence_count.timestamped_turns for item in observations)
    total = len(observations)
    return FluencyEvidenceCount(
        eligible_turns=len(eligible),
        total_turns=total,
        total_words=sum(item.features.word_count for item in eligible),
        learner_speech_seconds=round(
            sum(item.features.speech_duration_seconds for item in eligible), 3
        ),
        timestamped_turns=timestamped,
        timestamp_coverage=round(timestamped / total, 4) if total else 0.0,
    )


def _enough_evidence(
    mode: FluencyMode,
    evidence: FluencyEvidenceCount,
    settings: FluencySettings,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if mode == FluencyMode.ASSESSMENT:
        if evidence.eligible_turns < settings.assessment_minimum_turns:
            reasons.append(
                f"At least {settings.assessment_minimum_turns} eligible assessment responses are required."
            )
        if evidence.learner_speech_seconds < settings.assessment_minimum_speech_seconds:
            reasons.append(
                f"At least {settings.assessment_minimum_speech_seconds:.0f} seconds of learner speech are required."
            )
    elif mode == FluencyMode.GUIDED:
        if evidence.eligible_turns < settings.guided_minimum_turns:
            reasons.append(
                f"At least {settings.guided_minimum_turns} eligible guided lines are required."
            )
        if (
            evidence.eligible_turns < settings.guided_target_turns
            and evidence.learner_speech_seconds < settings.guided_minimum_speech_seconds
        ):
            reasons.append(
                f"Collect {settings.guided_target_turns} eligible guided lines or about "
                f"{settings.guided_minimum_speech_seconds:.0f} seconds of learner speech."
            )
    else:
        if evidence.eligible_turns < settings.conversation_minimum_turns:
            reasons.append(
                f"At least {settings.conversation_minimum_turns} eligible conversation turns are required."
            )
        if (
            evidence.eligible_turns < settings.conversation_target_turns
            and evidence.learner_speech_seconds < settings.conversation_minimum_speech_seconds
        ):
            reasons.append(
                f"Collect {settings.conversation_target_turns} eligible turns or about "
                f"{settings.conversation_minimum_speech_seconds:.0f} seconds of learner speech."
            )
    return not reasons, reasons


def _weighted_average(
    observations: Sequence[FluencyObservationResult],
    field: str,
) -> int:
    weighted = 0.0
    total_weight = 0.0
    for item in observations:
        if not item.eligible or item.subscores is None:
            continue
        # Cap a single turn's influence so one monologue cannot dominate an
        # otherwise interactive session.
        weight = max(1.0, min(30.0, item.features.speech_duration_seconds))
        weighted += float(getattr(item.subscores, field)) * weight
        total_weight += weight
    return round(weighted / total_weight) if total_weight else 0


def _session_feedback(
    subscores: FluencySubscores,
    evidence: FluencyEvidenceCount,
) -> list[str]:
    values = subscores.model_dump()
    strongest = max(values, key=values.get)
    weakest = min(values, key=values.get)
    strength_text = {
        "speed": "Your pace was generally functional across the eligible turns.",
        "breakdown": "You generally maintained the flow without excessive disruptive silence.",
        "continuity": "You were able to sustain connected stretches of speech.",
        "repair": "Fillers and repeated starts were controlled overall.",
    }
    development_text = {
        "speed": "Focus on a steadier functional pace rather than simply speaking faster.",
        "breakdown": "Reduce the longest planning pauses by preparing the next short phrase.",
        "continuity": "Connect ideas into slightly longer speech runs before stopping.",
        "repair": "Use a brief planning pause instead of repeated fillers or restarts.",
    }
    return [
        strength_text[strongest],
        development_text[weakest],
        (
            f"This result is based on {evidence.eligible_turns} eligible turn(s), "
            f"{evidence.total_words} timed words, and "
            f"{evidence.learner_speech_seconds:.1f} seconds of learner speech."
        ),
    ]


def aggregate_session(
    session_id: str,
    mode: FluencyMode,
    observations: Sequence[FluencyObservationResult],
    settings: FluencySettings | None = None,
) -> FluencySessionResult:
    settings = settings or FluencySettings.from_env()
    for observation in observations:
        if observation.session_id != session_id:
            raise ValueError("All fluency observations must belong to the requested session")
        if observation.mode != mode:
            raise ValueError("All fluency observations must use the session's mode")

    evidence = _evidence(observations)
    enough, reasons = _enough_evidence(mode, evidence, settings)
    eligible = [item for item in observations if item.eligible and item.fluency_index is not None]
    if not enough or not eligible:
        return FluencySessionResult(
            session_id=session_id,
            mode=mode,
            status=FluencyScoreStatus.INSUFFICIENT_EVIDENCE,
            confidence=FluencyConfidence.LOW,
            evidence_count=evidence,
            feedback=["More eligible connected speech is needed before a session score is shown."],
            insufficiency_reasons=reasons or ["No eligible timed learner turns were available."],
        )

    subscores = FluencySubscores(
        speed=_weighted_average(eligible, "speed"),
        breakdown=_weighted_average(eligible, "breakdown"),
        continuity=_weighted_average(eligible, "continuity"),
        repair=_weighted_average(eligible, "repair"),
    )
    total_weight = 0.0
    weighted_index = 0.0
    for item in eligible:
        assert item.fluency_index is not None
        weight = max(1.0, min(30.0, item.features.speech_duration_seconds))
        weighted_index += item.fluency_index * weight
        total_weight += weight
    index = round(weighted_index / total_weight)

    if (
        evidence.eligible_turns >= 8
        and evidence.learner_speech_seconds >= 60.0
        and evidence.timestamp_coverage >= 0.90
    ) or (
        mode == FluencyMode.ASSESSMENT
        and evidence.eligible_turns >= 6
        and evidence.learner_speech_seconds >= 45.0
        and evidence.timestamp_coverage >= 0.90
    ):
        confidence = FluencyConfidence.HIGH
    else:
        confidence = FluencyConfidence.MEDIUM

    return FluencySessionResult(
        session_id=session_id,
        mode=mode,
        status=FluencyScoreStatus.SCORED,
        fluency_index=index,
        confidence=confidence,
        evidence_count=evidence,
        subscores=subscores,
        feedback=_session_feedback(subscores, evidence),
        cefr_fluency_estimate=(
            cefr_estimate_from_index(index) if mode == FluencyMode.ASSESSMENT else None
        ),
    )
