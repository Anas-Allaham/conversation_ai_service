from __future__ import annotations

from typing import Protocol

from .models import GuidedAttemptResult, GuidedSessionRecord


class GuidedConversationRepository(Protocol):
    def create_guided_session(
        self, record: GuidedSessionRecord, correlation_id: str = ""
    ) -> None: ...

    def get_guided_session(self, session_id: str) -> GuidedSessionRecord | None: ...

    def save_guided_record(
        self, record: GuidedSessionRecord, event_type: str = "guided.session_updated"
    ) -> None: ...

    def save_guided_transition(
        self,
        record: GuidedSessionRecord,
        idempotency_key: str,
        result: GuidedAttemptResult,
        correlation_id: str = "",
    ) -> None: ...

    def get_guided_attempt_replay(
        self, session_id: str, idempotency_key: str
    ) -> GuidedAttemptResult | None: ...

    def save_guided_audio(self, session_id: str, attempt_id: str, audio_uri: str) -> None: ...

    def get_guided_audio(self, session_id: str, attempt_id: str) -> str | None: ...
