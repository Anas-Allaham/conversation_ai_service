from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from services.oral_assessment.models import AssessmentCreateRequest
from services.practice_sessions.tokens import LiveKitConfigurationError

from .models import AssessmentSessionCreateRequest, AssessmentSessionCreateResponse

router = APIRouter(prefix="/v1/assessment-sessions", tags=["assessment-sessions"])


@router.post(
    "",
    response_model=AssessmentSessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_assessment_session(
    payload: AssessmentSessionCreateRequest,
    request: Request,
) -> AssessmentSessionCreateResponse:
    issuer = request.app.state.livekit_token_issuer
    try:
        issuer.validate_configuration()
    except LiveKitConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    assessment = request.app.state.assessment_service.create_assessment(
        AssessmentCreateRequest(
            user_id=payload.user_id,
            interface_language=payload.interface_language,
        ),
        request.state.correlation_id,
    )
    room_name = assessment.assessment_id
    participant_identity = f"{payload.user_id}-{uuid.uuid4().hex[:10]}"
    dispatch_metadata: dict[str, object] = {
        "assessment_id": assessment.assessment_id,
        "user_id": payload.user_id,
        "interface_language": payload.interface_language,
    }
    try:
        issued = issuer.issue(
            room_name=room_name,
            participant_identity=participant_identity,
            participant_name=payload.participant_name or payload.user_id,
            dispatch_metadata=dispatch_metadata,
            agent_name="english-level-assessor",
        )
    except LiveKitConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    request.app.state.repository.audit(
        "assessment.session_created",
        {
            "room_name": room_name,
            "agent_name": "english-level-assessor",
        },
        assessment.assessment_id,
        request.state.correlation_id,
    )
    return AssessmentSessionCreateResponse(
        assessment_id=assessment.assessment_id,
        room_name=room_name,
        server_url=issuer.server_url,
        participant_token=issued.token,
        participant_identity=participant_identity,
        token_expires_at=issued.expires_at,
        result_url=f"/v1/assessments/{assessment.assessment_id}/result",
        assessment=assessment,
    )
