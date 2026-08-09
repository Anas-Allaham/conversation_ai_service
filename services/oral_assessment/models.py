from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.fluency.models import FluencyObservationResult, FluencySessionResult


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CEFRLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"


LEVELS: tuple[CEFRLevel, ...] = (CEFRLevel.A1, CEFRLevel.A2, CEFRLevel.B1, CEFRLevel.B2)


class AssessmentStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PromptKind(str, Enum):
    CALIBRATION = "calibration"
    MAIN = "main"
    FOLLOW_UP = "follow_up"
    TIE_BREAKER = "tie_breaker"


class ResponseDecision(str, Enum):
    PASS = "pass"
    BORDERLINE = "borderline"
    FAIL = "fail"
    INVALID_AUDIO = "invalid_audio"
    NOT_SCORED = "not_scored"


class StageDecision(str, Enum):
    PASS = "pass"
    TIE_BREAKER = "tie_breaker"
    FAIL = "fail"


class AudioQuality(str, Enum):
    GOOD = "good"
    USABLE = "usable"
    POOR = "poor"
    INVALID = "invalid"


class ResultConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NextActionType(str, Enum):
    ASK_MAIN = "ask_main"
    ASK_FOLLOW_UP = "ask_follow_up"
    ASK_TIE_BREAKER = "ask_tie_breaker"
    REPEAT_PROMPT = "repeat_prompt"
    SHOW_RESULT = "show_result"
    END = "end"


class WordTiming(StrictModel):
    word: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_range(self) -> WordTiming:
        if self.end < self.start:
            raise ValueError("word end must be greater than or equal to start")
        return self


class ResponseWindow(StrictModel):
    minimum: int = Field(ge=1, le=300)
    maximum: int = Field(ge=1, le=600)

    @model_validator(mode="after")
    def validate_order(self) -> ResponseWindow:
        if self.maximum < self.minimum:
            raise ValueError("maximum response time must be >= minimum")
        return self


class SupportPolicy(StrictModel):
    repeat_prompt: int = Field(default=1, ge=0, le=3)
    paraphrase_prompt: bool = False


class ItemReview(StrictModel):
    author: str
    reviewer: str
    review_status: Literal["approved", "pilot", "retired"]
    reviewed_at: str
    notes: str = ""


class AssessmentItem(StrictModel):
    item_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    version: str
    status: Literal["active", "retired", "pilot"]
    source: Literal["original_project_item"]
    target_level: CEFRLevel
    kind: Literal["normal", "tie_breaker"]
    task_type: str
    domain: str
    communicative_functions: list[str] = Field(min_length=1)
    main_prompt: str = Field(min_length=10)
    main_clarification_prompt: str | None = Field(default=None, min_length=10)
    follow_up_prompt: str | None = None
    follow_up_clarification_prompt: str | None = None
    expected_response_seconds: ResponseWindow
    follow_up_response_seconds: ResponseWindow | None = None
    support_policy: SupportPolicy
    required_evidence: list[str] = Field(min_length=1)
    grammar_independently_scored: Literal[False] = False
    review: ItemReview

    @model_validator(mode="after")
    def normal_item_has_followup(self) -> AssessmentItem:
        if self.kind == "normal" and not self.follow_up_prompt:
            raise ValueError("normal items require a follow-up prompt")
        return self


class ItemBank(StrictModel):
    bank_name: str
    version: str
    frozen_at: str
    content_policy: str
    items: list[AssessmentItem]


class CurrentPrompt(StrictModel):
    prompt_id: str
    item_id: str
    target_level: CEFRLevel | None
    prompt_kind: PromptKind
    prompt: str
    clarification_prompt: str
    response_limit_seconds: int
    prompt_repetitions_allowed: int
    preparation_seconds: int = Field(default=0, ge=0, le=60)
    reference_text: str | None = None


class AssessmentProgress(StrictModel):
    status: AssessmentStatus
    current_section: str
    current_prompt_kind: PromptKind | None
    questions_answered: int = Field(ge=0)
    confirmed_levels: list[CEFRLevel] = Field(default_factory=list)
    estimated_questions_remaining_min: int = Field(ge=0)
    estimated_questions_remaining_max: int = Field(ge=0)
    adaptive_length: Literal[True] = True
    display_text: str


class AssessmentCreateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    assessment_type: Literal["conversational-placement"] = "conversational-placement"
    target_range: list[CEFRLevel] = Field(default_factory=lambda: list(LEVELS))
    language: Literal["en"] = "en"
    interface_language: Literal["en", "ar"] = "en"
    form_seed: str | None = Field(default=None, max_length=128)

    @field_validator("target_range")
    @classmethod
    def target_range_is_supported(cls, value: list[CEFRLevel]) -> list[CEFRLevel]:
        if value != list(LEVELS):
            raise ValueError("MVP target_range must be exactly A1, A2, B1, B2")
        return value


class AssessmentCreateResponse(StrictModel):
    assessment_id: str
    status: AssessmentStatus
    current_item: CurrentPrompt
    assessment_version: str
    item_bank_version: str
    progress: AssessmentProgress


class ResponseSubmission(StrictModel):
    response_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    prompt_id: str = Field(min_length=1, max_length=160)
    item_id: str = Field(min_length=1, max_length=128)
    prompt_kind: PromptKind
    transcript: str = Field(default="", max_length=20_000)
    words: list[WordTiming] = Field(default_factory=list, max_length=5_000)
    response_started_at_ms: int | None = Field(default=None, ge=0)
    response_ended_at_ms: int | None = Field(default=None, ge=0)
    audio_uri: str | None = Field(default=None, max_length=2_000)
    prompt_repetitions: int = Field(default=0, ge=0, le=10)
    clarification_requests: int = Field(default=0, ge=0, le=20)
    asr_confidence: float | None = Field(default=None, ge=0, le=1)
    explicit_audio_issue: bool = False
    audio_issue_reason: str | None = Field(default=None, max_length=500)
    session_interrupted: bool = False

    @field_validator("words", mode="before")
    @classmethod
    def normalize_provider_words(cls, value: Any) -> Any:
        """Accept supported provider shapes and discard textless timing rows.

        The LiveKit adapter normally performs this conversion. Keeping the API
        boundary tolerant prevents a harmless provider-version difference from
        becoming an HTTP 422 and aborting an otherwise valid assessment turn.
        Structural errors outside these known word shapes remain validation
        errors.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            return value

        normalized: list[Any] = []
        for item in value:
            if isinstance(item, WordTiming):
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
    def timestamps_are_ordered(self) -> ResponseSubmission:
        if (
            self.response_started_at_ms is not None
            and self.response_ended_at_ms is not None
            and self.response_ended_at_ms < self.response_started_at_ms
        ):
            raise ValueError("response_ended_at_ms must be >= response_started_at_ms")
        return self


Score = Annotated[int, Field(ge=0, le=4)]


class DimensionScores(StrictModel):
    task_achievement: Score
    interactive_communication: Score
    fluency: Score
    coherence: Score
    lexical_adequacy: Score
    intelligibility: Score


class DimensionEvidence(StrictModel):
    task_achievement: str
    interactive_communication: str
    fluency: str
    coherence: str
    lexical_adequacy: str
    intelligibility: str


class EvaluatorOutput(StrictModel):
    target_level: CEFRLevel
    scores: DimensionScores
    meaning_blocked: bool
    task_achieved: bool
    task_relevant: bool
    audio_quality: AudioQuality
    evaluator_confidence: Literal["high", "medium", "low"]
    evidence: DimensionEvidence
    grammar_was_independently_scored: Literal[False] = False


class SpeechMetrics(StrictModel):
    word_count: int = Field(ge=0)
    response_duration_seconds: float = Field(ge=0)
    speech_duration_seconds: float = Field(ge=0)
    speech_rate_wpm: float = Field(ge=0)
    pause_duration_seconds: float = Field(ge=0)
    pause_ratio: float = Field(ge=0, le=1)
    mean_length_of_run_words: float = Field(ge=0)
    long_pause_count: int = Field(ge=0)
    max_inter_word_gap_seconds: float = Field(ge=0)
    response_start_latency_seconds: float | None = Field(default=None, ge=0)
    repeated_phrase_count: int = Field(default=0, ge=0)
    timing_source: Literal["word_timestamps", "response_window", "estimated"]


class ScoredResponse(StrictModel):
    scores: DimensionScores
    weighted_score: float = Field(ge=0, le=4)
    decision: ResponseDecision
    meaning_blocked: bool
    audio_quality: AudioQuality
    evaluator_confidence: Literal["high", "medium", "low"]
    evidence: DimensionEvidence
    decision_reasons: list[str]
    evaluator_provider: str
    evaluator_model: str
    used_fallback: bool = False
    task_achieved: bool = True
    task_relevant: bool = True
    fluency_observation: FluencyObservationResult | None = None
    fluency_source: Literal["rule_scorer", "evaluator_fallback", "not_scored"] = "not_scored"


class NextAction(StrictModel):
    type: NextActionType
    prompt: CurrentPrompt | None = None
    message: str | None = None


class ResponseResult(StrictModel):
    assessment_id: str
    response_id: str
    response_decision: ResponseDecision
    weighted_score: float | None = None
    stage_status: str
    next_action: NextAction
    current_level: CEFRLevel | None
    progress: AssessmentProgress
    idempotent_replay: bool = False


class VersionSet(StrictModel):
    assessment: str
    item_bank: str
    rubric: str
    scorer: str
    fluency: str = "fluency-v0.1"


class PronunciationDiagnostic(StrictModel):
    status: Literal["not_requested", "pending", "completed", "unavailable", "failed"]
    phoneme_error_rate: float | None = Field(default=None, ge=0)
    substitutions: list[dict[str, Any]] = Field(default_factory=list)
    deletions: list[str] = Field(default_factory=list)
    insertions: list[str] = Field(default_factory=list)
    phonological_similarity: float | None = Field(default=None, ge=0, le=1)
    feature_accuracy: dict[str, float] = Field(default_factory=dict)
    feedback: list[str] = Field(default_factory=list)
    impact_on_conversational_level: Literal["none"] = "none"
    failure_reason: str | None = None


class AssessmentStatistics(StrictModel):
    duration_seconds: float = Field(ge=0)
    responses_submitted: int = Field(ge=0)
    scored_responses: int = Field(ge=0)
    invalid_audio_responses: int = Field(ge=0)
    prompt_repetitions: int = Field(ge=0)
    clarification_requests: int = Field(ge=0)
    tie_breakers_used: int = Field(ge=0)


class AssessmentResult(StrictModel):
    assessment_id: str
    status: AssessmentStatus
    result_name: Literal["CEFR-aligned Conversational Interaction Placement"]
    confirmed_level: CEFRLevel | Literal["Pre-A1", "Not determined"]
    first_unconfirmed_level: CEFRLevel | None
    ceiling_reached: bool
    confidence: ResultConfidence
    confidence_score: int = Field(ge=0, le=100)
    confidence_score_interpretation: str
    profile: dict[str, CEFRLevel | Literal["Pre-A1", "Not determined"]]
    profile_scores_percent: dict[str, int]
    fluency: FluencySessionResult
    next_level_result: str
    summary: str
    statistics: AssessmentStatistics
    grammar_assessed: Literal[False] = False
    pronunciation_diagnostic: PronunciationDiagnostic
    versions: VersionSet
    disclaimer: str
    validity_warnings: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    completion_reason: str


class AssessmentRecord(StrictModel):
    assessment_id: str
    user_id: str
    status: AssessmentStatus
    current_level_index: int = Field(ge=0, le=4)
    current_item_id: str
    current_prompt_kind: PromptKind
    current_prompt_id: str
    highest_confirmed_level: CEFRLevel | None = None
    first_unconfirmed_level: CEFRLevel | None = None
    provisional_unconfirmed_level: CEFRLevel | None = None
    early_boundary_verification_used: bool = False
    boundary_verification_levels: list[CEFRLevel] = Field(default_factory=list)
    form_seed: str
    invalid_audio_count: int = 0
    tie_breaker_count: int = 0
    evaluator_failure_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    versions: VersionSet
    interface_language: str = "en"
    revision: int = Field(default=0, ge=0)
    completion_reason: str = ""


class StoredResponse(StrictModel):
    assessment_id: str
    submission: ResponseSubmission
    metrics: SpeechMetrics
    scored: ScoredResponse | None
    created_at: datetime


class PronunciationRequestedEvent(StrictModel):
    event_type: Literal["assessment.pronunciation_requested"]
    event_id: str
    occurred_at: datetime
    assessment_id: str
    response_id: str
    reference_text: str
    audio_uri: str
    callback_url: str | None = None


class PronunciationResultEvent(StrictModel):
    event_type: Literal["assessment.pronunciation_completed", "assessment.pronunciation_failed"]
    event_id: str
    occurred_at: datetime
    assessment_id: str
    response_id: str
    status: Literal["completed", "failed"]
    diagnostic: PronunciationDiagnostic
