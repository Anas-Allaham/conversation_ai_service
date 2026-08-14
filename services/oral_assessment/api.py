from __future__ import annotations

from fastapi import APIRouter, File, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AssessmentCreateRequest,
    AssessmentCreateResponse,
    AssessmentProgress,
    AssessmentRecord,
    AssessmentResult,
    PronunciationResultEvent,
    ResponseResult,
    ResponseSubmission,
)
from .service import AssessmentService

router = APIRouter()


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentStateResponse(APIModel):
    record: AssessmentRecord
    current_prompt: dict | None
    progress: AssessmentProgress


class AudioUploadResponse(APIModel):
    assessment_id: str
    response_id: str
    audio_uri: str
    encrypted: bool = True


class VersionActivationRequest(APIModel):
    item_bank_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class VersionActivationResponse(APIModel):
    active_item_bank_version: str
    restart_required: bool
    message: str


class RetentionResponse(APIModel):
    deleted_audio_objects: int
    retention_days: int


class AssessmentEvidenceResponse(APIModel):
    assessment_id: str
    versions: dict[str, str]
    responses: list[dict]


def _service(request: Request) -> AssessmentService:
    return request.app.state.assessment_service


@router.get("/health/live")
def health_live() -> dict:
    return {"status": "alive"}


@router.get("/health/ready")
def health_ready(request: Request, response: Response) -> dict:
    errors = list(request.app.state.readiness_errors)
    try:
        request.app.state.repository.get_runtime_setting("active_item_bank_version")
    except Exception as exc:  # noqa: BLE001 - readiness must report any database driver failure
        errors.append(f"database: {type(exc).__name__}")
    if errors:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "errors": errors}
    return {"status": "ready", "versions": request.app.state.versions}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> str:
    return request.app.state.metrics.render_prometheus()


@router.post(
    "/v1/assessments",
    response_model=AssessmentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_assessment(payload: AssessmentCreateRequest, request: Request) -> AssessmentCreateResponse:
    return _service(request).create_assessment(payload, request.state.correlation_id)


@router.get("/v1/assessments/{assessment_id}", response_model=AssessmentStateResponse)
def get_assessment_state(assessment_id: str, request: Request) -> AssessmentStateResponse:
    service = _service(request)
    record = service._record(assessment_id)
    prompt = None
    if record.status.value == "in_progress":
        prompt = service.current_prompt(record).model_dump(mode="json")
    return AssessmentStateResponse(
        record=record,
        current_prompt=prompt,
        progress=service.progress(record),
    )


@router.post(
    "/v1/assessments/{assessment_id}/responses",
    response_model=ResponseResult,
)
def submit_response(
    assessment_id: str,
    payload: ResponseSubmission,
    request: Request,
) -> ResponseResult:
    result = _service(request).submit_response(
        assessment_id, payload, request.state.correlation_id
    )
    request.app.state.metrics.observe_response(result)
    return result


@router.post(
    "/v1/assessments/{assessment_id}/audio/{response_id}",
    response_model=AudioUploadResponse,
)
async def upload_original_audio(
    assessment_id: str,
    response_id: str,
    request: Request,
    audio: UploadFile = File(...),  # noqa: B008 - FastAPI dependency declaration
) -> AudioUploadResponse:
    if request.app.state.audio_storage is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Encrypted audio storage is not configured")
    if request.app.state.repository.get_assessment(assessment_id) is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Assessment not found")
    payload = await audio.read(request.app.state.settings.max_body_bytes + 1)
    if len(payload) > request.app.state.settings.max_body_bytes:
        from fastapi import HTTPException

        raise HTTPException(status_code=413, detail="Audio payload is too large")
    uri = request.app.state.audio_storage.put(
        assessment_id,
        response_id,
        payload,
        audio.content_type or "application/octet-stream",
    )
    request.app.state.repository.audit(
        "audio.stored",
        {"response_id": response_id, "encrypted": True, "size_bytes": len(payload)},
        assessment_id,
        request.state.correlation_id,
    )
    return AudioUploadResponse(
        assessment_id=assessment_id,
        response_id=response_id,
        audio_uri=uri,
    )


@router.get("/v1/assessments/{assessment_id}/result", response_model=AssessmentResult)
def get_result(assessment_id: str, request: Request) -> AssessmentResult:
    result = _service(request).get_result(assessment_id)
    if assessment_id not in request.app.state.observed_completions:
        record = request.app.state.repository.get_assessment(assessment_id)
        duration = 0.0
        if record and record.completed_at:
            duration = (record.completed_at - record.created_at).total_seconds()
        request.app.state.metrics.observe_completion(result, duration)
        request.app.state.observed_completions.add(assessment_id)
    return result


@router.get(
    "/v1/assessments/{assessment_id}/evidence",
    response_model=AssessmentEvidenceResponse,
)
def get_assessment_evidence(
    assessment_id: str,
    request: Request,
) -> AssessmentEvidenceResponse:
    """Return auditable scoring evidence for the application/backend team."""
    service = _service(request)
    record = service._record(assessment_id)
    rows: list[dict] = []
    for stored in request.app.state.repository.list_responses(assessment_id):
        if stored.submission.prompt_kind.value == "calibration":
            prompt_text = service.item_bank.calibration_prompt().prompt
        else:
            item = service.item_bank.get(stored.submission.item_id)
            prompt_text = service.item_bank.prompt_for(
                item, stored.submission.prompt_kind
            ).prompt
        rows.append(
            {
                "response_id": stored.submission.response_id,
                "prompt_id": stored.submission.prompt_id,
                "item_id": stored.submission.item_id,
                "prompt_kind": stored.submission.prompt_kind.value,
                "prompt_text": prompt_text,
                "transcript": stored.submission.transcript,
                "support": {
                    "prompt_repetitions": stored.submission.prompt_repetitions,
                    "clarification_requests": stored.submission.clarification_requests,
                },
                "metrics": stored.metrics.model_dump(mode="json"),
                "scored": (
                    stored.scored.model_dump(mode="json") if stored.scored else None
                ),
                "created_at": stored.created_at.isoformat(),
            }
        )
    return AssessmentEvidenceResponse(
        assessment_id=assessment_id,
        versions={key: str(value) for key, value in record.versions.model_dump().items()},
        responses=rows,
    )


@router.post("/v1/assessments/{assessment_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_assessment(assessment_id: str, request: Request) -> Response:
    _service(request).cancel(assessment_id, request.state.correlation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/pronunciation/callback", status_code=status.HTTP_204_NO_CONTENT)
def pronunciation_callback(payload: PronunciationResultEvent, request: Request) -> Response:
    if request.app.state.repository.get_assessment(payload.assessment_id) is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Assessment not found")
    request.app.state.repository.save_pronunciation(payload.assessment_id, payload.diagnostic)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/admin/versions/activate", response_model=VersionActivationResponse)
def activate_version(payload: VersionActivationRequest, request: Request) -> VersionActivationResponse:
    target = (
        request.app.state.settings.project_root
        / "services"
        / "oral_assessment"
        / "data"
        / f"item_bank_v{payload.item_bank_version}.json"
    )
    if not target.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Version artifact is not installed: {target.name}")
    request.app.state.repository.set_runtime_setting(
        "active_item_bank_version", payload.item_bank_version
    )
    request.app.state.repository.audit(
        "version.activation_requested",
        {"item_bank_version": payload.item_bank_version, "restart_required": True},
        correlation_id=request.state.correlation_id,
    )
    return VersionActivationResponse(
        active_item_bank_version=payload.item_bank_version,
        restart_required=True,
        message="Restart the service with ITEM_BANK_VERSION set to the activated version. Existing assessments retain their stored version.",
    )


@router.post("/v1/admin/retention/cleanup", response_model=RetentionResponse)
def retention_cleanup(request: Request) -> RetentionResponse:
    storage = request.app.state.audio_storage
    deleted = 0 if storage is None else storage.delete_expired(
        request.app.state.settings.audio_retention_days
    )
    request.app.state.repository.audit(
        "retention.cleanup",
        {"deleted_audio_objects": deleted},
        correlation_id=request.state.correlation_id,
    )
    return RetentionResponse(
        deleted_audio_objects=deleted,
        retention_days=request.app.state.settings.audio_retention_days,
    )
