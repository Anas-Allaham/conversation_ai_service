from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from .config import Settings
from .models import (
    AssessmentItem,
    AudioQuality,
    CEFRLevel,
    DimensionEvidence,
    DimensionScores,
    EvaluatorOutput,
    PromptKind,
    ResponseSubmission,
    SpeechMetrics,
)

logger = logging.getLogger(__name__)


class EvaluationUnavailable(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        category: str = "unavailable",
        status_code: int | None = None,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: AssessmentItem
    prompt_kind: PromptKind
    prompt_text: str
    submission: ResponseSubmission
    metrics: SpeechMetrics


class RubricEvaluator(Protocol):
    provider_name: str
    model_name: str

    def validate(self) -> None: ...

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput: ...


class UnavailableEvaluator:
    provider_name = "unavailable"
    model_name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def validate(self) -> None:
        raise EvaluationUnavailable(
            self.reason,
            provider=self.provider_name,
            category="evaluator_not_configured",
            retryable=False,
        )

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput:
        raise EvaluationUnavailable(
            self.reason,
            provider=self.provider_name,
            category="evaluator_not_configured",
            retryable=False,
        )


SYSTEM_INSTRUCTION = """You rate one CEFR-aligned conversational task against its supplied target level.

Rules:
- Evaluate only the supplied response, fixed task, objective metrics, support used, and required evidence.
- Never assign a global CEFR level and never choose the learner's final placement.
- Score exactly six dimensions from 0 to 4. A score of 3 means the response meets the current target-level task requirement; 4 clearly exceeds it; 2 partially meets it; 1 is far below it; 0 provides no usable evidence.
- Do not independently score grammatical accuracy. Do not reduce a score merely because grammar errors exist. Consider grammar only if its communicative consequence blocks meaning, prevents task achievement, or repeatedly forces clarification.
- Do not infer pronunciation quality from transcript spelling or ASR confidence. Judge intelligibility only from supplied evidence and explicit communication breakdowns.
- ASR confidence is a validity flag, never a proficiency score.
- Short length is evidence insufficiency, not an automatic CEFR failure. Consider whether the task was actually completed.
- Judge interaction for this turn by whether the learner understood and responded appropriately to this part of the exchange. Do not require evidence from a future follow-up question.
- Treat the required-evidence list as a task blueprint, not a word-for-word script. Missing one non-central detail should normally make task achievement partial or borderline, not a complete failure, when the central communicative purpose was achieved.
- One permitted repetition or clarification is compatible with A1/A2 performance and must not by itself force a fail.
- Do not treat obvious ASR substitutions or homophones as learner language errors when the intended meaning remains recoverable from context.
- If audio evidence is unusable, set audio_quality to invalid rather than assigning low proficiency scores.
- Evidence strings must cite concise observable facts from the transcript or metrics.
"""


LEVEL_ANCHORS = {
    CEFRLevel.A1: (
        "A1 anchor: simple statements and direct answers on very familiar matters can meet the level. "
        "Repetition, rephrasing, and support are compatible with A1. Do not require connected narration."
    ),
    CEFRLevel.A2: (
        "A2 anchor: the learner can manage short, structured, predictable everyday exchanges with "
        "some help. Formulaic but appropriate requests, questions, choices, and confirmations can meet "
        "the level; do not require an elaborate monologue."
    ),
    CEFRLevel.B1: (
        "B1 anchor: the learner should communicate with some confidence on familiar routine and "
        "non-routine matters, connect a sequence, and explain reasons, results, or advice with limited help."
    ),
    CEFRLevel.B2: (
        "B2 anchor: the learner should sustain a clear comparison or position, explain advantages and "
        "disadvantages, and respond spontaneously to a counterargument without significant strain."
    ),
}


def build_user_prompt(request: EvaluationInput) -> str:
    item = request.item
    payload = {
        "target_level": item.target_level.value,
        "prompt_kind": request.prompt_kind.value,
        "task_type": item.task_type,
        "prompt": request.prompt_text,
        "required_evidence": item.required_evidence,
        "level_anchor": LEVEL_ANCHORS[item.target_level],
        "support_policy": item.support_policy.model_dump(),
        "transcript": request.submission.transcript,
        "speech_metrics": request.metrics.model_dump(),
        "prompt_repetitions": request.submission.prompt_repetitions,
        "clarification_requests": request.submission.clarification_requests,
        "asr_confidence_validity_flag_only": request.submission.asr_confidence,
        "explicit_audio_issue": request.submission.explicit_audio_issue,
        "audio_issue_reason": request.submission.audio_issue_reason,
    }
    return "Score this single response. Return the required structured object.\n" + json.dumps(
        payload, ensure_ascii=False
    )


def gemini_structured_output_config() -> dict:
    """Return the Google Gen AI SDK structured-output configuration."""
    return {
        "temperature": 0,
        "response_mime_type": "application/json",
        "response_json_schema": EvaluatorOutput.model_json_schema(),
    }


def _duration_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s?\s*", value)
        return float(match.group(1)) if match else None
    if isinstance(value, dict):
        seconds = _duration_seconds(value.get("seconds"))
        if seconds is None:
            return None
        nanos = value.get("nanos", 0)
        try:
            return max(0.0, seconds + float(nanos) / 1_000_000_000)
        except (TypeError, ValueError):
            return seconds
    return None


def gemini_retry_after_seconds(error: Exception) -> float | None:
    """Extract Google's RetryInfo delay or Retry-After header from an SDK error."""

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        header_delay = _duration_seconds(headers.get("Retry-After"))
        if header_delay is not None:
            return header_delay

    def walk(value: object) -> float | None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).replace("_", "").lower() == "retrydelay":
                    parsed = _duration_seconds(child)
                    if parsed is not None:
                        return parsed
                nested = walk(child)
                if nested is not None:
                    return nested
        elif isinstance(value, list):
            for child in value:
                nested = walk(child)
                if nested is not None:
                    return nested
        return None

    return walk(getattr(error, "details", None))


def classify_gemini_error(error: Exception) -> tuple[str, int | None, bool, float | None]:
    code = getattr(error, "code", None)
    try:
        status_code = int(code) if code is not None else None
    except (TypeError, ValueError):
        status_code = None
    retry_after = gemini_retry_after_seconds(error)
    serialized = json.dumps(getattr(error, "details", {}), default=str).lower()
    if status_code == 429 and (
        "requestsperday" in serialized
        or "requests_per_day" in serialized
        or "perday" in serialized
    ):
        category = "provider_daily_quota_exhausted"
    else:
        category = {
            401: "provider_authentication_failed",
            403: "provider_permission_denied",
            404: "provider_configuration_error",
            408: "provider_timeout",
            429: "provider_rate_limited",
            500: "provider_overloaded",
            502: "provider_overloaded",
            503: "provider_overloaded",
            504: "provider_timeout",
        }.get(status_code, "provider_request_failed")
    retryable = status_code in {408, 429, 500, 502, 503, 504}
    return category, status_code, retryable, retry_after


class GeminiEvaluator:
    provider_name = "gemini"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise EvaluationUnavailable("GEMINI_API_KEY is not configured")
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise EvaluationUnavailable("Install google-genai to use Gemini evaluation") from exc
        self.model_name = settings.gemini_model
        self._api_error_type = errors.APIError
        self._max_retries = settings.evaluator_max_retries
        self._max_retry_wait_seconds = settings.evaluator_max_retry_wait_seconds
        self._sleep = time.sleep
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                api_version=settings.gemini_api_version,
                timeout=max(1, int(settings.evaluator_timeout_seconds * 1000)),
                retry_options=types.HttpRetryOptions(
                    # Provider RetryInfo is handled below. The SDK's generic
                    # exponential retry ignores Google's explicit retryDelay
                    # and exhausted the learner's free-tier quota faster.
                    attempts=1,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )

    def _unavailable(self, error: Exception, *, prefix: str) -> EvaluationUnavailable:
        category, status_code, retryable, retry_after = classify_gemini_error(error)
        return EvaluationUnavailable(
            prefix,
            provider=self.provider_name,
            category=category,
            status_code=status_code,
            retryable=retryable,
            retry_after_seconds=retry_after,
        )

    def validate(self) -> None:
        """Validate the configured key/model without consuming a generation request."""
        try:
            self._client.models.get(model=self.model_name)
        except self._api_error_type as exc:
            raise self._unavailable(
                exc,
                prefix="Gemini API key or model validation failed",
            ) from exc

    def _generate(self, prompt: str):
        total_wait = 0.0
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=gemini_structured_output_config(),
                )
            except self._api_error_type as exc:
                category, status_code, retryable, retry_after = classify_gemini_error(exc)
                can_retry = retryable and attempt < self._max_retries
                if category == "provider_daily_quota_exhausted" and retry_after is None:
                    can_retry = False
                delay = retry_after if retry_after is not None else min(2**attempt, 8.0)
                if total_wait + delay > self._max_retry_wait_seconds:
                    can_retry = False
                if not can_retry:
                    logger.warning(
                        "Gemini evaluator unavailable: category=%s status=%s retry_after=%s",
                        category,
                        status_code,
                        retry_after,
                    )
                    raise EvaluationUnavailable(
                        "Gemini evaluator request failed",
                        provider=self.provider_name,
                        category=category,
                        status_code=status_code,
                        retryable=retryable,
                        retry_after_seconds=retry_after,
                    ) from exc
                logger.warning(
                    "Gemini evaluator asked to retry in %.1fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                self._sleep(delay)
                total_wait += delay
        raise AssertionError("unreachable Gemini retry state")

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput:
        prompt = SYSTEM_INSTRUCTION + "\n\n" + build_user_prompt(request)
        last_error: Exception | None = None
        for validation_attempt in range(2):
            try:
                response = self._generate(prompt)
                parsed = getattr(response, "parsed", None)
                result = (
                    EvaluatorOutput.model_validate(parsed)
                    if parsed is not None
                    else EvaluatorOutput.model_validate_json(response.text or "")
                )
                if result.target_level != request.item.target_level:
                    raise ValueError("Evaluator returned the wrong target level")
                return result
            except EvaluationUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - normalize any provider response-shape failure
                last_error = exc
                logger.warning(
                    "Gemini evaluator structured output attempt %s failed: %s",
                    validation_attempt + 1,
                    type(exc).__name__,
                )
                if validation_attempt == 0:
                    prompt += (
                        "\n\nYour previous output failed schema validation. Return exactly the required "
                        "JSON object, keep target_level unchanged, and include all required fields."
                    )
        raise EvaluationUnavailable(
            "Gemini evaluator returned invalid structured output",
            provider=self.provider_name,
            category="invalid_structured_output",
            retryable=True,
        ) from last_error


class OpenAIEvaluator:
    provider_name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise EvaluationUnavailable("OPENAI_API_KEY is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EvaluationUnavailable("Install openai to use OpenAI evaluation") from exc
        self.model_name = settings.openai_model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.evaluator_timeout_seconds,
            max_retries=settings.evaluator_max_retries,
        )

    def validate(self) -> None:
        return None

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput:
        last_error: Exception | None = None
        for validation_attempt in range(2):
            try:
                response = self._client.responses.parse(
                    model=self.model_name,
                    input=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": build_user_prompt(request)},
                    ],
                    text_format=EvaluatorOutput,
                )
                result = response.output_parsed
                if result is None:
                    raise ValueError("Model returned no parsed evaluator output")
                if result.target_level != request.item.target_level:
                    raise ValueError("Evaluator returned the wrong target level")
                return result
            except Exception as exc:
                last_error = exc
                status_code = getattr(exc, "status_code", None)
                if status_code is not None:
                    raise EvaluationUnavailable(
                        "OpenAI evaluator request failed",
                        provider=self.provider_name,
                        category=(
                            "provider_rate_limited"
                            if status_code == 429
                            else "provider_request_failed"
                        ),
                        status_code=int(status_code),
                        retryable=int(status_code) in {408, 409, 429, 500, 502, 503, 504},
                    ) from exc
                logger.warning(
                    "OpenAI evaluator structured output attempt %s failed: %s",
                    validation_attempt + 1,
                    type(exc).__name__,
                )
        raise EvaluationUnavailable(
            "OpenAI evaluator returned invalid structured output",
            provider=self.provider_name,
            category="invalid_structured_output",
            retryable=True,
        ) from last_error


class HeuristicDemoEvaluator:
    """Deterministic offline smoke-test evaluator; never enable for real placement."""

    provider_name = "heuristic"
    model_name = "offline-demo-v1"

    LEVEL_WORD_TARGETS: ClassVar[dict[CEFRLevel, tuple[int, int]]] = {
        CEFRLevel.A1: (8, 18),
        CEFRLevel.A2: (15, 30),
        CEFRLevel.B1: (28, 55),
        CEFRLevel.B2: (42, 80),
    }

    def validate(self) -> None:
        return None

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput:
        metrics = request.metrics
        minimum, strong = self.LEVEL_WORD_TARGETS[request.item.target_level]
        transcript = request.submission.transcript.strip()
        if not transcript:
            base = 0
        elif metrics.word_count >= strong:
            base = 4
        elif metrics.word_count >= minimum:
            base = 3
        elif metrics.word_count >= max(3, minimum // 2):
            base = 2
        else:
            base = 1
        if request.submission.clarification_requests > 1:
            interaction = max(0, base - 1)
        else:
            interaction = base
        fluency = base
        if metrics.pause_ratio > 0.45 or metrics.long_pause_count >= 4:
            fluency = max(1, fluency - 1)
        relevance_tokens = set(re.findall(r"[a-z]+", request.prompt_text.lower())) - {
            "the", "a", "an", "and", "or", "you", "your", "what", "how", "tell", "me"
        }
        answer_tokens = set(re.findall(r"[a-z]+", transcript.lower()))
        relevant = bool(relevance_tokens & answer_tokens) or metrics.word_count >= minimum
        audio = AudioQuality.INVALID if request.submission.explicit_audio_issue else AudioQuality.USABLE
        scores = DimensionScores(
            task_achievement=base if relevant else min(base, 1),
            interactive_communication=interaction,
            fluency=fluency,
            coherence=base,
            lexical_adequacy=base,
            intelligibility=base,
        )
        note = "Offline demo estimate based on evidence quantity; use Gemini or OpenAI in production."
        return EvaluatorOutput(
            target_level=request.item.target_level,
            scores=scores,
            meaning_blocked=False,
            task_achieved=base >= 2 and relevant,
            task_relevant=relevant,
            audio_quality=audio,
            evaluator_confidence="low",
            evidence=DimensionEvidence(
                task_achievement=note,
                interactive_communication=note,
                fluency=f"{note} Pause ratio={metrics.pause_ratio}.",
                coherence=note,
                lexical_adequacy=note,
                intelligibility=note,
            ),
            grammar_was_independently_scored=False,
        )


@dataclass(slots=True)
class ScriptedEvaluator:
    """Test-only evaluator that returns a controlled sequence."""

    outputs: list[EvaluatorOutput]
    provider_name: str = "scripted"
    model_name: str = "scripted-v1"

    def validate(self) -> None:
        return None

    def evaluate(self, request: EvaluationInput) -> EvaluatorOutput:
        if not self.outputs:
            raise EvaluationUnavailable("No scripted evaluator output remains")
        result = self.outputs.pop(0)
        if result.target_level != request.item.target_level:
            result = result.model_copy(update={"target_level": request.item.target_level})
        return result


def build_evaluator(settings: Settings) -> RubricEvaluator:
    if settings.evaluator_provider == "gemini":
        return GeminiEvaluator(settings)
    if settings.evaluator_provider == "openai":
        return OpenAIEvaluator(settings)
    if settings.evaluator_provider == "heuristic" and settings.allow_heuristic_evaluator:
        return HeuristicDemoEvaluator()
    raise EvaluationUnavailable(
        "No valid evaluator is configured. Use gemini/openai, or explicitly enable heuristic demo mode.",
        category="evaluator_not_configured",
        retryable=False,
    )
