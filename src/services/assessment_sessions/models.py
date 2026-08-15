from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.oral_assessment.models import AssessmentCreateResponse


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssessmentSessionCreateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=128)
    participant_name: str | None = Field(default=None, max_length=128)
    interface_language: Literal["en", "ar"] = "en"


class AssessmentSessionCreateResponse(StrictModel):
    assessment_id: str
    room_name: str
    server_url: str
    participant_token: str
    participant_identity: str
    token_expires_at: datetime
    agent_name: str = "english-level-assessor"
    result_url: str
    assessment: AssessmentCreateResponse
