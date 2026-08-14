from __future__ import annotations

import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class SessionJobMetadata(BaseModel):
    """Strict contract supplied to the worker through LiveKit dispatch."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    session_id: uuid.UUID
    subject_id: uuid.UUID
    lesson_id: str | None = Field(default=None, min_length=1, max_length=128)
    locale: str = Field(default="en", min_length=2, max_length=16)

    @classmethod
    def local_fallback(cls) -> SessionJobMetadata:
        return cls(
            schema_version=1,
            session_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            locale="en",
        )


class PracticeJobMetadata(BaseModel):
    """Trusted dispatch contract emitted by the practice-session API."""

    model_config = ConfigDict(extra="forbid")

    conversation_mode: Literal["free", "guided"]
    practice_session_id: str = Field(min_length=1, max_length=160)
    user_id: str = Field(min_length=1, max_length=128)
    guided_session_id: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def guided_mode_has_session(self) -> PracticeJobMetadata:
        if self.conversation_mode == "guided" and self.guided_session_id is None:
            raise ValueError("guided practice requires guided_session_id")
        if self.conversation_mode == "free" and self.guided_session_id is not None:
            raise ValueError("guided_session_id is allowed only for guided practice")
        return self


TutorJobMetadata = SessionJobMetadata | PracticeJobMetadata


class JobMetadataError(ValueError):
    pass


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


def parse_tutor_job_metadata(raw: str | None, *, production: bool) -> TutorJobMetadata:
    """Validate either the existing main contract or Aya's practice contract."""

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

    model = PracticeJobMetadata if "conversation_mode" in payload else SessionJobMetadata
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise JobMetadataError(f"Invalid dispatch metadata: {exc}") from exc
