from __future__ import annotations

from .models import (
    AudioQuality,
    DimensionScores,
    EvaluatorOutput,
    ResponseDecision,
    ScoredResponse,
)

WEIGHTS = {
    "task_achievement": 0.25,
    "interactive_communication": 0.20,
    "fluency": 0.20,
    "coherence": 0.15,
    "lexical_adequacy": 0.10,
    "intelligibility": 0.10,
}

PASS_THRESHOLD = 2.8
BORDERLINE_THRESHOLD = 2.4


def weighted_score(scores: DimensionScores) -> float:
    values = scores.model_dump()
    return round(sum(values[name] * weight for name, weight in WEIGHTS.items()), 3)


def score_evaluator_output(
    output: EvaluatorOutput,
    *,
    provider: str,
    model: str,
    used_fallback: bool = False,
) -> ScoredResponse:
    score = weighted_score(output.scores)
    reasons: list[str] = []

    if output.audio_quality == AudioQuality.INVALID:
        decision = ResponseDecision.INVALID_AUDIO
        reasons.append("Audio was explicitly judged unusable; the response must be repeated without penalty.")
    elif output.meaning_blocked:
        decision = ResponseDecision.FAIL
        reasons.append("The intended meaning could not be recovered reliably.")
    elif not output.task_relevant:
        decision = ResponseDecision.FAIL
        reasons.append("The response did not address the supplied task.")
    elif not output.task_achieved or output.scores.task_achievement <= 1:
        decision = ResponseDecision.FAIL
        reasons.append("The communicative task was not achieved.")
    else:
        critical_met = (
            output.scores.task_achievement >= 3
            and output.scores.interactive_communication >= 3
            and output.scores.intelligibility >= 2
        )
        if score >= PASS_THRESHOLD and critical_met:
            decision = ResponseDecision.PASS
            reasons.append("Weighted and critical-dimension pass requirements were met.")
        elif score < BORDERLINE_THRESHOLD:
            decision = ResponseDecision.FAIL
            reasons.append("Weighted score was below the provisional evidence threshold.")
        else:
            decision = ResponseDecision.BORDERLINE
            if score >= PASS_THRESHOLD:
                reasons.append("Weighted score was sufficient, but a critical dimension was below threshold.")
            else:
                reasons.append("Evidence fell within the provisional borderline range.")

    return ScoredResponse(
        scores=output.scores,
        weighted_score=score,
        decision=decision,
        meaning_blocked=output.meaning_blocked,
        audio_quality=output.audio_quality,
        evaluator_confidence=output.evaluator_confidence,
        evidence=output.evidence,
        decision_reasons=reasons,
        evaluator_provider=provider,
        evaluator_model=model,
        used_fallback=used_fallback,
        task_achieved=output.task_achieved,
        task_relevant=output.task_relevant,
    )
