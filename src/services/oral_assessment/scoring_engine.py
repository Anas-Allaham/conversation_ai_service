from __future__ import annotations

from services.fluency import FluencyObservationResult, assessment_dimension_score

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
    fluency_observation: FluencyObservationResult | None = None,
    target_level: str | None = None,
) -> ScoredResponse:
    scores = output.scores
    evidence = output.evidence
    fluency_source = "evaluator_fallback"
    if fluency_observation is not None and target_level is not None:
        rule_score = assessment_dimension_score(fluency_observation, target_level)
        if rule_score is not None:
            scores = scores.model_copy(update={"fluency": rule_score})
            evidence = evidence.model_copy(
                update={
                    "fluency": (
                        f"{fluency_observation.scorer_version} index "
                        f"{fluency_observation.fluency_index}/100 from "
                        f"{fluency_observation.features.word_count} timed words; "
                        f"target-level rubric score {rule_score}/4."
                    )
                }
            )
            fluency_source = "rule_scorer"
    score = weighted_score(scores)
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
            scores.task_achievement >= 3
            and scores.interactive_communication >= 3
            and scores.intelligibility >= 2
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
        scores=scores,
        weighted_score=score,
        decision=decision,
        meaning_blocked=output.meaning_blocked,
        audio_quality=output.audio_quality,
        evaluator_confidence=output.evaluator_confidence,
        evidence=evidence,
        decision_reasons=reasons,
        evaluator_provider=provider,
        evaluator_model=model,
        used_fallback=used_fallback,
        task_achieved=output.task_achieved,
        task_relevant=output.task_relevant,
        fluency_observation=fluency_observation,
        fluency_source=fluency_source,
    )
