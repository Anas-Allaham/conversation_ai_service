from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

CONTROL_MAX_WORDS = 16
logger = logging.getLogger("english-level-assessor")


@dataclass(slots=True)
class PendingResponse:
    """Accumulate provider-committed fragments that belong to one learner answer.

    Flux may commit a deliberate learner's multi-sentence answer as several
    turns. The assessment service, however, must receive exactly one response
    for the current prompt. This state object keeps those fragments together
    until the learner has been quiet for the configured collection window.
    """

    prompt_id: str | None = None
    fragments: list[str] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    response_started_at_ms: int | None = None
    generation: int = 0
    seen_turn_ids: set[str] = field(default_factory=set)
    claimed_generation: int | None = None

    def reset(self) -> None:
        self.generation += 1
        self.prompt_id = None
        self.fragments.clear()
        self.words.clear()
        self.confidences.clear()
        self.response_started_at_ms = None
        self.seen_turn_ids.clear()
        self.claimed_generation = None

    def postpone_submission(self) -> None:
        """Invalidate an existing quiet-window waiter without losing evidence."""
        self.generation += 1
        self.claimed_generation = None

    def add(
        self,
        *,
        prompt_id: str,
        turn_id: str,
        transcript: str,
        words: Sequence[Mapping[str, Any]],
        confidence: float | None,
        response_started_at_ms: int | None,
    ) -> int:
        if self.prompt_id not in {None, prompt_id}:
            self.reset()
        self.prompt_id = prompt_id

        if turn_id in self.seen_turn_ids:
            return self.generation
        self.seen_turn_ids.add(turn_id)

        cleaned = transcript.strip()
        if cleaned:
            self.fragments.append(cleaned)

        if words:
            offset = self.words[-1]["end"] + 0.35 if self.words else 0.0
            for word in words:
                text = str(word.get("word") or "").strip()
                if not text:
                    continue
                raw_start = max(0.0, float(word.get("start") or 0.0))
                raw_end = max(raw_start, float(word.get("end") or raw_start))
                start = raw_start + offset
                end = raw_end + offset
                self.words.append(
                    {
                        "word": text,
                        "start": start,
                        "end": end,
                        "confidence": word.get("confidence"),
                    }
                )

        if confidence is not None:
            self.confidences.append(confidence)
        if self.response_started_at_ms is None:
            self.response_started_at_ms = response_started_at_ms

        self.generation += 1
        self.claimed_generation = None
        return self.generation

    def claim(self, generation: int) -> bool:
        if generation != self.generation or self.claimed_generation == generation:
            return False
        self.claimed_generation = generation
        return True

    @property
    def has_content(self) -> bool:
        return bool(self.fragments or self.words)

    @property
    def transcript(self) -> str:
        return " ".join(self.fragments).strip()

    @property
    def confidence(self) -> float | None:
        if not self.confidences:
            return None
        return sum(self.confidences) / len(self.confidences)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number; received {raw!r}.") from exc


def assessment_endpointing_options() -> dict[str, Any]:
    """Add a grace period after STT EOT so thinking pauses do not split answers."""
    mode = os.getenv("ASSESSMENT_ENDPOINTING_MODE", "fixed").strip().lower()
    if mode not in {"fixed", "dynamic"}:
        raise RuntimeError("ASSESSMENT_ENDPOINTING_MODE must be 'fixed' or 'dynamic'")
    min_delay = _env_float("ASSESSMENT_ENDPOINTING_MIN_DELAY_SECONDS", 1.50)
    max_delay = _env_float("ASSESSMENT_ENDPOINTING_MAX_DELAY_SECONDS", 4.00)
    if min_delay < 0 or max_delay < min_delay:
        raise RuntimeError(
            "Assessment endpointing requires 0 <= minimum delay <= maximum delay"
        )
    options: dict[str, Any] = {
        "mode": mode,
        "min_delay": min_delay,
        "max_delay": max_delay,
    }
    if mode == "dynamic":
        alpha = _env_float("ASSESSMENT_ENDPOINTING_ALPHA", 0.90)
        if not 0.0 <= alpha <= 1.0:
            raise RuntimeError("ASSESSMENT_ENDPOINTING_ALPHA must be between 0 and 1")
        options["alpha"] = alpha
    logger.info(
        "[ASSESSMENT TURN] endpointing=%s | min-delay=%.2fs | max-delay=%.2fs",
        mode,
        min_delay,
        max_delay,
    )
    return options


def control_intent(transcript: str) -> str:
    """Classify short assessment-control requests without using the scoring LLM."""
    normalized = " ".join(re.findall(r"[a-z']+", transcript.lower())).strip()
    tokens = normalized.split()
    if not normalized or len(tokens) > CONTROL_MAX_WORDS:
        return "answer"

    if normalized in {"done", "i'm done", "i am done", "finished", "i finished", "that's all"}:
        return "done"
    if normalized in {
        "continue",
        "please continue",
        "try again",
        "retry",
        "resume",
        "i am ready",
        "i'm ready",
    }:
        return "resume"
    if any(
        phrase in normalized
        for phrase in (
            "repeat the question",
            "repeat that",
            "say that again",
            "say the question again",
            "what was the question",
            "can you repeat",
            "could you repeat",
        )
    ):
        return "repeat"
    if any(
        phrase in normalized
        for phrase in (
            "explain the question",
            "explain that",
            "what does the question mean",
            "what do you mean",
            "i don't understand",
            "i do not understand",
            "can you explain",
            "could you explain",
            "can you clarify",
            "could you clarify",
        )
    ):
        return "clarify"
    if any(
        phrase in normalized
        for phrase in (
            "give me a moment",
            "give me some time",
            "let me think",
            "one moment",
            "wait a moment",
            "i need time",
        )
    ):
        return "thinking"
    return "answer"


def strip_optional_completion_marker(transcript: str) -> tuple[str, bool]:
    """Allow, but never require, a learner to explicitly finish an answer."""
    marker = re.compile(
        r"(?:\s+|^)(?:i(?:'m| am)\s+done|i(?:'m| am)\s+finished|done|finished|"
        r"that's\s+all|that\s+is\s+all|that's\s+it|that\s+is\s+it)[.!?]*\s*$",
        re.IGNORECASE,
    )
    match = marker.search(transcript.strip())
    if not match:
        return transcript.strip(), False
    return transcript[: match.start()].strip(), True


def learner_result_announcement(result: Mapping[str, Any]) -> str:
    """Return only the result details that are useful in the spoken exchange."""
    confirmed = str(result.get("confirmed_level") or "Not determined")
    if result.get("ceiling_reached"):
        placement = "B2 or higher within this assessment's range"
    elif confirmed == "Pre-A1":
        placement = "below A1"
    elif confirmed == "Not determined":
        placement = "not determined because there was not enough usable audio"
    else:
        placement = confirmed

    confidence = str(result.get("confidence") or "low").lower()
    profile = result.get("profile") or {}
    fluency = str(profile.get("fluency") or "Not determined")
    if fluency == "Pre-A1":
        fluency = "below A1"

    return (
        f"That completes the assessment. Your estimated conversational English level is {placement}. "
        f"The evidence confidence is {confidence}, and your fluency is assessed at {fluency}. "
        "You can see your complete skill profile in the application."
    )


def scoring_deferred_message(
    *,
    retry_after_seconds: float | None,
    retryable: bool,
) -> str:
    """Keep provider details out of speech while giving truthful retry guidance."""
    saved = "Your answer is saved, so please do not repeat it. "
    if retryable and retry_after_seconds is not None:
        wait = max(1, math.ceil(retry_after_seconds))
        return (
            saved
            + f"Scoring is temporarily busy. Please wait about {wait} seconds, then say continue."
        )
    if retryable:
        return saved + "Scoring is temporarily busy. Please wait a short time, then say continue."
    return saved + "Scoring is unavailable right now. Please try saying continue later."


def spoken_prompt(prompt: Mapping[str, Any]) -> str:
    text = str(prompt["prompt"])
    seconds = int(prompt.get("preparation_seconds") or 0)
    if seconds <= 0:
        return text
    return (
        f"{text} You may take up to {seconds} seconds to think. "
        "Start when you are ready."
    )
