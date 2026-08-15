from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app.realtime.assessment_payload import (
    extract_words,
    optional_confidence,
    read_value,
    valid_submission_words,
)
from app.services.assessment_client import AssessmentClient, AssessmentClientError
from services.fluency.models import PracticeMode

logger = logging.getLogger("english-tutor.fluency")


def _metadata(source: Any) -> dict[str, Any]:
    """Read trusted dispatch metadata first, then legacy room metadata."""

    candidates = [
        getattr(getattr(source, "job", None), "metadata", None),
        getattr(getattr(source, "room", None), "metadata", None),
        getattr(source, "metadata", None),
    ]
    for raw_metadata in candidates:
        if not isinstance(raw_metadata, str) or not raw_metadata.strip():
            continue
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            continue
        if isinstance(metadata, dict):
            return metadata
    return {}


def conversation_mode(source: Any) -> PracticeMode:
    """Resolve one of the two backend-selected practice modes.

    LiveKit explicit-dispatch job metadata is authoritative. Room metadata is
    retained as a compatibility fallback for an already integrated backend.
    Unknown values are rejected instead of silently creating a third behavior.
    """

    metadata = _metadata(source)
    selected = metadata.get("conversation_mode", os.getenv("CONVERSATION_MODE", "free"))
    if not isinstance(selected, str):
        raise TypeError("conversation_mode must be the string 'free' or 'guided'")
    try:
        return PracticeMode(selected.strip().lower())
    except ValueError as exc:
        raise RuntimeError(
            f"Unsupported conversation_mode {selected!r}; use only 'free' or 'guided'"
        ) from exc


def conversation_metadata(source: Any) -> dict[str, Any]:
    """Expose parsed trusted metadata to the selected practice runtime."""

    return _metadata(source)


class ConversationFluencyTracker:
    """Non-blocking Flux timing adapter for dynamic free conversation."""

    def __init__(
        self,
        session_id: str,
        mode: str,
        client: AssessmentClient | None = None,
    ) -> None:
        if mode != PracticeMode.FREE and mode != PracticeMode.FREE.value:
            raise ValueError(
                "The dynamic conversation tracker is free-mode only; guided scoring "
                "is owned by the deterministic scenario service"
            )
        self.session_id = session_id
        self.mode = PracticeMode.FREE.value
        self.client = client or AssessmentClient()
        self._words: list[dict[str, Any]] = []
        self._asr_confidence: float | None = None
        self._turn_started_ms: int | None = None

    def mark_user_speaking(self) -> None:
        if self._turn_started_ms is None:
            self._turn_started_ms = int(time.time() * 1000)

    def observe_stt_event(self, event: Any) -> None:
        alternatives = read_value(event, "alternatives", default=[]) or []
        if not alternatives:
            return
        alternative = alternatives[0]
        captured = extract_words(read_value(alternative, "words", default=[]))
        if captured:
            self._words = captured
        confidence = optional_confidence(read_value(alternative, "confidence"))
        if confidence is not None:
            self._asr_confidence = confidence

    async def submit_turn(self, transcript: str, turn_id: str) -> dict[str, Any] | None:
        ended_ms = int(time.time() * 1000)
        payload = {
            "session_id": self.session_id,
            "turn_id": turn_id,
            "mode": self.mode,
            "transcript": transcript,
            "words": valid_submission_words(self._words),
            "response_started_at_ms": self._turn_started_ms,
            "response_ended_at_ms": ended_ms,
            "completed": True,
            "assistance_count": 0,
            "task_type": None,
            "explicit_audio_issue": False,
            "audio_issue_reason": None,
        }
        self._words = []
        self._asr_confidence = None
        self._turn_started_ms = None
        try:
            result = await self.client.submit_fluency_turn_async(self.session_id, payload)
        except AssessmentClientError as exc:
            # Fluency analytics must never interrupt the learning conversation.
            logger.warning("Fluency observation was not stored: %s", exc)
            return None
        session = result.get("session") or {}
        logger.info(
            "[FLUENCY] mode=%s status=%s index=%s eligible-turns=%s",
            self.mode,
            session.get("status"),
            session.get("fluency_index"),
            (session.get("evidence_count") or {}).get("eligible_turns"),
        )
        return result
