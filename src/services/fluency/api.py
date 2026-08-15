from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .aggregator import aggregate_session
from .models import (
    FluencyMode,
    FluencyObservationRequest,
    FluencyObservationResult,
    FluencySessionResult,
)
from .scorer import score_observation

router = APIRouter()


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FluencyTurnResponse(APIModel):
    observation: FluencyObservationResult
    session: FluencySessionResult


@router.post(
    "/v1/fluency/sessions/{session_id}/turns",
    response_model=FluencyTurnResponse,
)
def submit_fluency_turn(
    session_id: str,
    payload: FluencyObservationRequest,
    request: Request,
) -> FluencyTurnResponse:
    if payload.session_id != session_id:
        raise HTTPException(status_code=422, detail="Path and payload session_id must match")
    repository = request.app.state.repository
    existing = repository.get_fluency_observation(session_id, payload.turn_id)
    session_observations = repository.list_fluency_observations(session_id)
    if session_observations and any(item.mode != payload.mode for item in session_observations):
        raise HTTPException(status_code=409, detail="The supplied mode does not match this session")
    observation = existing or repository.save_fluency_observation(
        score_observation(payload)
    )
    observations = repository.list_fluency_observations(session_id)
    session = aggregate_session(session_id, payload.mode, observations)
    repository.audit(
        "fluency.turn_observed",
        {
            "session_id": session_id,
            "turn_id": payload.turn_id,
            "mode": payload.mode.value,
            "status": observation.status.value,
            "eligible": observation.eligible,
            "scorer_version": observation.scorer_version,
        },
        correlation_id=request.state.correlation_id,
    )
    return FluencyTurnResponse(observation=observation, session=session)


@router.get(
    "/v1/fluency/sessions/{session_id}",
    response_model=FluencySessionResult,
)
def get_fluency_session(
    session_id: str,
    mode: FluencyMode,
    request: Request,
) -> FluencySessionResult:
    observations = request.app.state.repository.list_fluency_observations(session_id)
    if observations and any(item.mode != mode for item in observations):
        raise HTTPException(status_code=409, detail="The requested mode does not match this session")
    return aggregate_session(session_id, mode, observations)
