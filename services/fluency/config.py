from __future__ import annotations

import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None or not value.strip() else float(value)


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or not value.strip() else int(value)


@dataclass(frozen=True, slots=True)
class FluencySettings:
    pause_threshold_seconds: float = 0.50
    long_pause_threshold_seconds: float = 1.50
    minimum_turn_words: int = 5
    minimum_turn_seconds: float = 2.50
    assessment_minimum_turns: int = 2
    assessment_minimum_speech_seconds: float = 12.0
    conversation_minimum_turns: int = 3
    conversation_target_turns: int = 5
    conversation_minimum_speech_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> FluencySettings:
        settings = cls(
            pause_threshold_seconds=_float("FLUENCY_PAUSE_THRESHOLD_SECONDS", 0.50),
            long_pause_threshold_seconds=_float(
                "FLUENCY_LONG_PAUSE_THRESHOLD_SECONDS", 1.50
            ),
            minimum_turn_words=_int("FLUENCY_MINIMUM_TURN_WORDS", 5),
            minimum_turn_seconds=_float("FLUENCY_MINIMUM_TURN_SECONDS", 2.50),
            assessment_minimum_turns=_int("FLUENCY_ASSESSMENT_MINIMUM_TURNS", 2),
            assessment_minimum_speech_seconds=_float(
                "FLUENCY_ASSESSMENT_MINIMUM_SPEECH_SECONDS", 12.0
            ),
            conversation_minimum_turns=_int("FLUENCY_CONVERSATION_MINIMUM_TURNS", 3),
            conversation_target_turns=_int("FLUENCY_CONVERSATION_TARGET_TURNS", 5),
            conversation_minimum_speech_seconds=_float(
                "FLUENCY_CONVERSATION_MINIMUM_SPEECH_SECONDS", 30.0
            ),
        )
        if settings.pause_threshold_seconds <= 0:
            raise RuntimeError("FLUENCY_PAUSE_THRESHOLD_SECONDS must be greater than zero")
        if settings.long_pause_threshold_seconds <= settings.pause_threshold_seconds:
            raise RuntimeError(
                "FLUENCY_LONG_PAUSE_THRESHOLD_SECONDS must exceed the pause threshold"
            )
        if settings.minimum_turn_words < 1 or settings.minimum_turn_seconds <= 0:
            raise RuntimeError("Fluency turn evidence thresholds must be positive")
        return settings
