from __future__ import annotations

import json
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SessionJobMetadata(BaseModel):
    """Strict contract supplied by the future core through LiveKit dispatch."""

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
