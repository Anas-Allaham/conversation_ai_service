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

logger = logging.getLogger("english-tutor.fluency")


def conversation_mode(room: Any) -> str:
    """Resolve the backend-selected mode without trusting learner speech."""

    selected = os.getenv("CONVERSATION_MODE", "free").strip().lower()
    raw_metadata = getattr(room, "metadata", None)
    if isinstance(raw_metadata, str) and raw_metadata.strip():
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, dict):
            candidate = metadata.get("conversation_mode") or metadata.get("mode")
            if isinstance(candidate, str):
                selected = candidate.strip().lower()
    aliases = {
        "guided": "guided",
        "scenario": "guided",
        "practice": "guided",
        "free": "free",
        "conversation": "free",
    }
    if selected not in aliases:
        logger.warning("Unknown conversation mode %r; using free", selected)
        return "free"
    return aliases[selected]


class ConversationFluencyTracker:
    """Non-blocking Flux timing adapter for guided and free conversation."""

    def __init__(
        self,
        session_id: str,
        mode: str,
        client: AssessmentClient | None = None,
    ) -> None:
        if mode not in {"guided", "free"}:
            raise ValueError("Conversation fluency mode must be guided or free")
        self.session_id = session_id
        self.mode = mode
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
