from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from services.oral_assessment.config import Settings
from services.oral_assessment.models import (
    AudioQuality,
    CEFRLevel,
    DimensionEvidence,
    DimensionScores,
    EvaluatorOutput,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def make_test_settings(database_url: str) -> Settings:
    settings = Settings.from_env(PROJECT_ROOT)
    return replace(
        settings,
        database_url=database_url,
        evaluator_provider="heuristic",
        allow_heuristic_evaluator=True,
        service_token="test-service-token",
        admin_token="test-admin-token",
        store_all_assessment_audio=False,
    )


def evaluator_output(
    level: CEFRLevel,
    value: int = 3,
    *,
    task: int | None = None,
    interaction: int | None = None,
    intelligibility: int | None = None,
    meaning_blocked: bool = False,
    task_achieved: bool = True,
    task_relevant: bool = True,
    confidence: str = "high",
) -> EvaluatorOutput:
    note = "Controlled evaluator evidence for deterministic test."
    return EvaluatorOutput(
        target_level=level,
        scores=DimensionScores(
            task_achievement=value if task is None else task,
            interactive_communication=value if interaction is None else interaction,
            fluency=value,
            coherence=value,
            lexical_adequacy=value,
            intelligibility=value if intelligibility is None else intelligibility,
        ),
        meaning_blocked=meaning_blocked,
        task_achieved=task_achieved,
        task_relevant=task_relevant,
        audio_quality=AudioQuality.GOOD,
        evaluator_confidence=confidence,
        evidence=DimensionEvidence(
            task_achievement=note,
            interactive_communication=note,
            fluency=note,
            coherence=note,
            lexical_adequacy=note,
            intelligibility=note,
        ),
        grammar_was_independently_scored=False,
    )
