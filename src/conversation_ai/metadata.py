from __future__ import annotations

import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SESSION_NAMESPACE = uuid.UUID("d0e29c4d-2505-4a08-bf95-61182325372d")
SUBJECT_NAMESPACE = uuid.UUID("19cc7b38-c0e9-4079-8af7-b01eaff4b003")


class SessionJobMetadata(BaseModel):
    """Strict contract supplied to the worker through LiveKit dispatch."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    session_id: uuid.UUID
    subject_id: uuid.UUID
    lesson_id: str | None = Field(default=None, min_length=1, max_length=128)
    locale: str = Field(default="en", min_length=2, max_length=16)
    conversation_mode: Literal["free", "guided"] = "free"
    practice_session_id: str | None = Field(default=None, min_length=1, max_length=160)
    guided_session_id: str | None = Field(default=None, min_length=1, max_length=160)

    @classmethod
    def local_fallback(cls) -> SessionJobMetadata:
        return cls(
            schema_version=1,
            session_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            locale="en",
        )


class JobMetadataError(ValueError):
    pass


class PracticeDispatchMetadata(BaseModel):
    """Contract emitted by the integrated ``/v1/practice-sessions`` API."""

    model_config = ConfigDict(extra="forbid")

    conversation_mode: Literal["free", "guided"]
    practice_session_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=128)
    guided_session_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_guided_session(self) -> PracticeDispatchMetadata:
        if self.conversation_mode == "guided" and not self.guided_session_id:
            raise ValueError("guided_session_id is required for guided mode")
        if self.conversation_mode == "free" and self.guided_session_id is not None:
            raise ValueError("guided_session_id is allowed only for guided mode")
        return self


class WorkerJobMetadata(BaseModel):
    """Normalized worker metadata for both legacy and integrated API dispatches."""

    session: SessionJobMetadata
    source: Literal["conversation-api", "practice-api", "local"]
    source_user_id: str | None = None

    @property
    def conversation_mode(self) -> Literal["free", "guided"]:
        return self.session.conversation_mode

    @property
    def practice_session_id(self) -> str | None:
        return self.session.practice_session_id

    @property
    def guided_session_id(self) -> str | None:
        return self.session.guided_session_id


def parse_job_metadata(raw: str | None, *, production: bool) -> SessionJobMetadata:
    if not raw or not raw.strip():
        if production:
            raise JobMetadataError("Production jobs require dispatch metadata.")
        return SessionJobMetadata.local_fallback()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JobMetadataError("Dispatch metadata must be valid JSON.") from exc

    if not isinstance(payload, dict):
        raise JobMetadataError("Dispatch metadata must be a JSON object.")

    try:
        return SessionJobMetadata.model_validate(payload)
    except ValidationError as exc:
        raise JobMetadataError(f"Invalid dispatch metadata: {exc}") from exc


def stable_session_id(practice_session_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(practice_session_id)
    except ValueError:
        return uuid.uuid5(SESSION_NAMESPACE, practice_session_id)


def stable_subject_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        return uuid.uuid5(SUBJECT_NAMESPACE, user_id)


def parse_worker_job_metadata(raw: str | None, *, production: bool) -> WorkerJobMetadata:
    """Accept both existing team dispatches and the tutor practice dispatch contract."""

    if not raw or not raw.strip():
        session = parse_job_metadata(raw, production=production)
        return WorkerJobMetadata(session=session, source="local")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JobMetadataError("Dispatch metadata must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise JobMetadataError("Dispatch metadata must be a JSON object.")

    if "schema_version" in payload:
        return WorkerJobMetadata(
            session=parse_job_metadata(raw, production=production),
            source="conversation-api",
        )

    try:
        practice = PracticeDispatchMetadata.model_validate(payload)
    except ValidationError as exc:
        raise JobMetadataError(f"Invalid practice dispatch metadata: {exc}") from exc

    session = SessionJobMetadata(
        schema_version=1,
        session_id=stable_session_id(practice.practice_session_id),
        subject_id=stable_subject_id(practice.user_id),
        lesson_id=(practice.guided_session_id or practice.practice_session_id)[:128],
        locale="en",
        conversation_mode=practice.conversation_mode,
        practice_session_id=practice.practice_session_id,
        guided_session_id=practice.guided_session_id,
    )
    return WorkerJobMetadata(
        session=session,
        source="practice-api",
        source_user_id=practice.user_id,
    )
