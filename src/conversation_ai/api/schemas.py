from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from ..metadata import SessionJobMetadata


class StartConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    subject_id: uuid.UUID
    lesson_id: str | None = Field(default=None, min_length=1, max_length=128)
    locale: str = Field(default="en", min_length=2, max_length=16)

    def job_metadata(self) -> SessionJobMetadata:
        return SessionJobMetadata(
            schema_version=1,
            session_id=self.session_id,
            subject_id=self.subject_id,
            lesson_id=self.lesson_id,
            locale=self.locale,
        )
