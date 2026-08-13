from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FluencyMode(str, Enum):
    ASSESSMENT = "assessment"
    GUIDED = "guided"
    FREE = "free"


class PracticeMode(str, Enum):
    """The only two learner-selectable practice modes in the application."""

    FREE = "free"
    GUIDED = "guided"


class FluencyScoreStatus(str, Enum):
    SCORED = "scored"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID_AUDIO = "invalid_audio"


class FluencyConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FluencyWord(StrictModel):
    word: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> FluencyWord:
        if self.end < self.start:
            raise ValueError("word end must be greater than or equal to start")
        return self


class FluencyObservationRequest(StrictModel):
    """One committed learner turn sent by any application mode.

    Word timestamps are seconds relative to the beginning of the full learner
    response. System latency, tutor speech, and silence after the last learner
    word must not be included.
    """

    session_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    mode: FluencyMode
    transcript: str = Field(default="", max_length=20_000)
    words: list[FluencyWord] = Field(default_factory=list, max_length=5_000)
    response_started_at_ms: int | None = Field(default=None, ge=0)
    response_ended_at_ms: int | None = Field(default=None, ge=0)
    completed: bool = True
    assistance_count: int = Field(default=0, ge=0, le=20)
    target_level: Literal["A1", "A2", "B1", "B2"] | None = None
    task_type: str | None = Field(default=None, max_length=100)
    explicit_audio_issue: bool = False
    audio_issue_reason: str | None = Field(default=None, max_length=500)

    @field_validator("words", mode="before")
    @classmethod
    def normalize_provider_words(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        normalized: list[Any] = []
        for item in value:
            if isinstance(item, FluencyWord):
                normalized.append(item)
                continue
            if not isinstance(item, Mapping):
                normalized.append(item)
                continue
            word = item.get("word") or item.get("text") or item.get("punctuated_word")
            if not isinstance(word, str) or not word.strip():
                continue
            start = item.get("start", item.get("start_time", 0.0))
            end = item.get("end", item.get("end_time", start))
            normalized.append(
                {
                    "word": word.strip(),
                    "start": start,
                    "end": end,
                    "confidence": item.get("confidence"),
                }
            )
        return normalized

    @model_validator(mode="after")
    def validate_context(self) -> FluencyObservationRequest:
        if (
            self.response_started_at_ms is not None
            and self.response_ended_at_ms is not None
            and self.response_ended_at_ms < self.response_started_at_ms
        ):
            raise ValueError("response_ended_at_ms must be >= response_started_at_ms")
        if self.target_level is not None and self.mode != FluencyMode.ASSESSMENT:
            raise ValueError("target_level is allowed only in controlled assessment mode")
        return self


class FluencyFeatures(StrictModel):
    word_count: int = Field(ge=0)
    response_duration_seconds: float = Field(ge=0)
    speech_duration_seconds: float = Field(ge=0)
    speech_rate_wpm: float = Field(ge=0)
    articulation_rate_wpm: float = Field(ge=0)
    pace_stability: float | None = Field(default=None, ge=0, le=1)
    pause_count: int = Field(ge=0)
    pauses_per_minute: float = Field(ge=0)
    pause_duration_seconds: float = Field(ge=0)
    pause_ratio: float = Field(ge=0, le=1)
    phonation_ratio: float = Field(ge=0, le=1)
    mean_length_of_run_words: float = Field(ge=0)
    longest_run_words: int = Field(ge=0)
    long_pause_count: int = Field(ge=0)
    long_pauses_per_minute: float = Field(ge=0)
    max_inter_word_gap_seconds: float = Field(ge=0)
    filler_count: int = Field(ge=0)
    fillers_per_100_words: float = Field(ge=0)
    immediate_repeat_count: int = Field(ge=0)
    repeated_phrase_count: int = Field(ge=0)
    self_correction_count: int = Field(ge=0)
    timing_source: Literal["word_timestamps", "response_window", "unavailable"]


class FluencySubscores(StrictModel):
    speed: int = Field(ge=0, le=100)
    breakdown: int = Field(ge=0, le=100)
    continuity: int = Field(ge=0, le=100)
    repair: int = Field(ge=0, le=100)


class FluencyEvidenceCount(StrictModel):
    eligible_turns: int = Field(ge=0)
    total_turns: int = Field(ge=0)
    total_words: int = Field(ge=0)
    learner_speech_seconds: float = Field(ge=0)
    timestamped_turns: int = Field(ge=0)
    timestamp_coverage: float = Field(ge=0, le=1)


class FluencyObservationResult(StrictModel):
    session_id: str
    turn_id: str
    mode: FluencyMode
    status: FluencyScoreStatus
    eligible: bool
    fluency_index: int | None = Field(default=None, ge=0, le=100)
    confidence: FluencyConfidence
    evidence_count: FluencyEvidenceCount
    features: FluencyFeatures
    subscores: FluencySubscores | None = None
    feedback: list[str] = Field(default_factory=list)
    insufficiency_reasons: list[str] = Field(default_factory=list)
    cefr_fluency_estimate: Literal["Pre-A1", "A1", "A2", "B1", "B2"] | None = None
    scorer_version: Literal["fluency-v0.1"] = "fluency-v0.1"
    score_interpretation: str = (
        "Explainable delivery-fluency index, not a probability or official CEFR score."
    )

    @model_validator(mode="after")
    def cefr_only_for_assessment(self) -> FluencyObservationResult:
        if self.cefr_fluency_estimate is not None and self.mode != FluencyMode.ASSESSMENT:
            raise ValueError("CEFR fluency labels are allowed only for controlled assessment")
        if self.status != FluencyScoreStatus.SCORED and self.fluency_index is not None:
            raise ValueError("non-scored observations cannot have a fluency index")
        return self


class FluencySessionResult(StrictModel):
    session_id: str
    mode: FluencyMode
    status: FluencyScoreStatus
    fluency_index: int | None = Field(default=None, ge=0, le=100)
    confidence: FluencyConfidence
    evidence_count: FluencyEvidenceCount
    subscores: FluencySubscores | None = None
    feedback: list[str] = Field(default_factory=list)
    insufficiency_reasons: list[str] = Field(default_factory=list)
    cefr_fluency_estimate: Literal["Pre-A1", "A1", "A2", "B1", "B2"] | None = None
    scorer_version: Literal["fluency-v0.1"] = "fluency-v0.1"
    score_interpretation: str = (
        "Session delivery-fluency index from eligible learner turns; not a probability."
    )

    @model_validator(mode="after")
    def validate_result(self) -> FluencySessionResult:
        if self.cefr_fluency_estimate is not None and self.mode != FluencyMode.ASSESSMENT:
            raise ValueError("CEFR fluency labels are allowed only for controlled assessment")
        if self.status != FluencyScoreStatus.SCORED and self.fluency_index is not None:
            raise ValueError("non-scored sessions cannot have a fluency index")
        return self
