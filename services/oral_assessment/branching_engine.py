from __future__ import annotations

from .models import ResponseDecision, ScoredResponse, StageDecision

STAGE_PASS_THRESHOLD = 2.8


def decide_stage(main: ResponseDecision, follow_up: ResponseDecision) -> StageDecision:
    """Apply the documented two-observation stage table."""
    if ResponseDecision.INVALID_AUDIO in {main, follow_up}:
        raise ValueError("Invalid-audio observations must be repeated before stage branching")
    if main == ResponseDecision.PASS and follow_up == ResponseDecision.PASS:
        return StageDecision.PASS
    if main == ResponseDecision.BORDERLINE and follow_up == ResponseDecision.BORDERLINE:
        return StageDecision.TIE_BREAKER
    if ResponseDecision.PASS in {main, follow_up}:
        return StageDecision.TIE_BREAKER
    return StageDecision.FAIL


def decide_stage_evidence(main: ScoredResponse, follow_up: ScoredResponse) -> StageDecision:
    """Judge the stage from both observations instead of two isolated labels.

    A learner can answer one part more strongly than the other. Averaging the
    supplied evidence avoids under-placing a learner because one otherwise
    adequate response missed a non-central detail. A clearly irrelevant or
    meaning-blocked pair still fails and is sent to a different same-level
    boundary item by the service.
    """
    if ResponseDecision.INVALID_AUDIO in {main.decision, follow_up.decision}:
        raise ValueError("Invalid-audio observations must be repeated before stage branching")

    observations = (main, follow_up)
    if all(item.decision == ResponseDecision.PASS for item in observations):
        return StageDecision.PASS

    averages = {
        name: sum(getattr(item.scores, name) for item in observations) / 2
        for name in (
            "task_achievement",
            "interactive_communication",
            "fluency",
            "coherence",
            "lexical_adequacy",
            "intelligibility",
        )
    }
    average_weighted = (main.weighted_score + follow_up.weighted_score) / 2
    stage_critical_met = (
        averages["task_achievement"] >= 3
        and averages["interactive_communication"] >= 3
        and averages["intelligibility"] >= 2
    )
    usable_exchange = (
        all(item.task_relevant for item in observations)
        and all(item.task_achieved for item in observations)
        and not any(item.meaning_blocked for item in observations)
    )
    if average_weighted >= STAGE_PASS_THRESHOLD and stage_critical_met and usable_exchange:
        return StageDecision.PASS

    if all(
        item.decision == ResponseDecision.FAIL
        and (item.meaning_blocked or not item.task_relevant)
        for item in observations
    ):
        return StageDecision.FAIL
    return StageDecision.TIE_BREAKER


def tie_breaker_passed(decision: ResponseDecision) -> bool:
    return decision == ResponseDecision.PASS
