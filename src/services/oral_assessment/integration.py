from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from services.assessment_sessions.api import router as assessment_sessions_router
from services.fluency.api import router as fluency_router
from services.guided_conversation.api import admin_router as guided_admin_router
from services.guided_conversation.api import (
    install_exception_handlers as install_guided_exception_handlers,
)
from services.guided_conversation.api import router as guided_router
from services.guided_conversation.catalog import ScenarioCatalogRepository
from services.guided_conversation.pronunciation import GuidedPronunciationPublisher
from services.guided_conversation.service import GuidedConversationService
from services.local_tts import PiperConfigurationError, PiperSynthesizer
from services.practice_sessions.api import router as practice_sessions_router
from services.practice_sessions.tokens import LiveKitTokenIssuer

from .api import router as assessment_router
from .config import Settings
from .item_bank import ItemBankRepository
from .metrics import ServiceMetrics
from .middleware import SecurityAndObservabilityMiddleware
from .repository import SQLRepository
from .rubric_evaluator import (
    EvaluationUnavailable,
    UnavailableEvaluator,
    build_evaluator,
)
from .service import (
    AssessmentNotFound,
    AssessmentService,
    InvalidAssessmentState,
    SubmissionConflict,
)
from .storage import AudioStorageError, build_audio_storage

logger = logging.getLogger("conversation-ai.tutor")

SWAGGER_REQUEST_EXAMPLES: dict[tuple[str, str], dict[str, object]] = {
    ("/v1/assessments", "post"): {
        "user_id": "learner-001",
        "interface_language": "en",
    },
    ("/v1/assessment-sessions", "post"): {
        "user_id": "learner-001",
        "participant_name": "Test Learner",
        "interface_language": "en",
    },
    ("/v1/practice-sessions", "post"): {
        "user_id": "learner-001",
        "participant_name": "Test Learner",
        "mode": "free",
        "interface_language": "en",
        "placement_completed": False,
        "recording_consent": False,
    },
    ("/v1/guided-conversations/sessions", "post"): {
        "user_id": "learner-001",
        "scenario_id": "restaurant.order_meal.a1",
        "placement_completed": True,
        "placement_level": "A1",
        "interface_language": "en",
        "recording_consent": False,
    },
    ("/v1/guided-conversations/sessions/{session_id}/attempts", "post"): {
        "attempt_id": "attempt-001",
        "idempotency_key": "attempt-001-idempotency",
        "turn_id": "turn_01",
        "transcript": "I would like a sandwich, please.",
        "words": [],
        "completed": True,
        "explicit_audio_issue": False,
    },
    ("/v1/guided-conversations/sessions/{session_id}/confidence", "post"): {
        "confidence_after": 75,
    },
    ("/v1/assessments/{assessment_id}/responses", "post"): {
        "response_id": "response-001",
        "idempotency_key": "response-001-idempotency",
        "prompt_id": "copy-from-current-prompt",
        "item_id": "copy-from-current-prompt",
        "prompt_kind": "main",
        "transcript": "I usually wake up early, prepare breakfast, and then go to university.",
        "words": [],
        "prompt_repetitions": 0,
        "clarification_requests": 0,
        "explicit_audio_issue": False,
        "session_interrupted": False,
    },
    ("/v1/fluency/sessions/{session_id}/turns", "post"): {
        "session_id": "free-test-session",
        "turn_id": "turn-001",
        "mode": "free",
        "transcript": "I enjoy reading and practicing English in my free time.",
        "words": [],
        "completed": True,
        "assistance_count": 0,
        "explicit_audio_issue": False,
    },
    ("/v1/admin/versions/activate", "post"): {
        "item_bank_version": "0.2.0",
    },
}


def install_tutor_openapi_security(app: FastAPI) -> None:
    """Document the Bearer credentials already enforced by tutor middleware.

    Without these operation-level declarations Swagger UI remembers the key,
    but does not attach it to requests for the integrated ``/v1`` routes.
    """

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        # ServiceApiKey is also used by the team's /api/v1 routes. Reusing it
        # makes one Swagger authorization apply to all ordinary service calls.
        schemes.setdefault(
            "ServiceApiKey",
            {
                "type": "http",
                "scheme": "bearer",
                "description": "Internal service Bearer credential.",
            },
        )
        schemes.setdefault(
            "TutorAdminToken",
            {
                "type": "http",
                "scheme": "bearer",
                "description": "ASSESSMENT_ADMIN_TOKEN for tutor administration routes.",
            },
        )
        schemes.setdefault(
            "PronunciationCallbackToken",
            {
                "type": "http",
                "scheme": "bearer",
                "description": "PRONUNCIATION_SERVICE_TOKEN for provider callbacks.",
            },
        )

        callback_paths = {
            "/v1/pronunciation/callback",
            "/v1/guided-conversations/pronunciation/callback",
        }
        for path, path_item in schema.get("paths", {}).items():
            if path == "/metrics":
                scheme_name = "ServiceApiKey"
            elif not path.startswith("/v1/"):
                continue
            elif path.startswith("/v1/admin/"):
                scheme_name = "TutorAdminToken"
            elif path in callback_paths:
                scheme_name = "PronunciationCallbackToken"
            else:
                scheme_name = "ServiceApiKey"
            for method, operation in path_item.items():
                if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                    operation["security"] = [{scheme_name: []}]
                example = SWAGGER_REQUEST_EXAMPLES.get((path, method.lower()))
                if example is not None:
                    request_body = operation.get("requestBody", {})
                    json_content = request_body.get("content", {}).get("application/json")
                    if json_content is not None:
                        json_content["example"] = example

        app.openapi_schema = schema
        return schema

    app.openapi_schema = None
    app.openapi = custom_openapi


def install_tutor_modules(
    app: FastAPI,
    *,
    project_root: Path,
    expose_settings_as_primary: bool = False,
) -> Settings:
    """Attach tutor modules to one existing API instead of creating a second service."""

    root = project_root.resolve()
    settings = Settings.from_env(root)
    repository = SQLRepository(settings.database_url)
    item_bank = ItemBankRepository(settings.item_bank_path)
    readiness_errors = settings.readiness_errors()

    try:
        evaluator = build_evaluator(settings)
        evaluator.validate()
    except EvaluationUnavailable as exc:
        evaluator = UnavailableEvaluator(str(exc))
        if str(exc) not in readiness_errors:
            readiness_errors.append(str(exc))

    try:
        audio_storage = build_audio_storage(settings)
    except AudioStorageError as exc:
        audio_storage = None
        if settings.store_all_assessment_audio:
            detail = str(exc)
            duplicate_key_error = "AUDIO_ENCRYPTION_KEY" in detail and any(
                "AUDIO_ENCRYPTION_KEY" in error for error in readiness_errors
            )
            if not duplicate_key_error and detail not in readiness_errors:
                readiness_errors.append(detail)

    metrics = ServiceMetrics()
    assessment_service = AssessmentService(settings, repository, item_bank, evaluator)
    scenario_catalog = ScenarioCatalogRepository(settings.guided_scenario_path)
    pronunciation_publisher = GuidedPronunciationPublisher(
        settings.pronunciation_service_url,
        settings.pronunciation_service_token,
        settings.evaluator_timeout_seconds,
    )
    guided_service = GuidedConversationService(
        repository,
        scenario_catalog,
        pronunciation_configured=pronunciation_publisher.configured,
        public_service_url=settings.guided_service_public_url,
    )

    piper_synthesizer = None
    try:
        piper_synthesizer = PiperSynthesizer(root)
    except PiperConfigurationError as exc:
        if settings.piper_required:
            readiness_errors.append(str(exc))
        logger.warning("Piper unavailable: %s", exc)

    app.state.tutor_settings = settings
    if expose_settings_as_primary:
        app.state.settings = settings
    app.state.repository = repository
    app.state.item_bank = item_bank
    app.state.assessment_service = assessment_service
    app.state.guided_service = guided_service
    app.state.guided_pronunciation_publisher = pronunciation_publisher
    app.state.piper_synthesizer = piper_synthesizer
    app.state.livekit_token_issuer = LiveKitTokenIssuer(
        settings.livekit_url,
        settings.livekit_api_key,
        settings.livekit_api_secret,
    )
    app.state.audio_storage = audio_storage
    app.state.metrics = metrics
    app.state.tutor_readiness_errors = readiness_errors
    app.state.readiness_errors = readiness_errors
    app.state.observed_completions = set()
    app.state.versions = {
        "assessment": settings.assessment_version,
        "item_bank": item_bank.bank.version,
        "rubric": settings.rubric_version,
        "scorer": settings.scorer_version,
        "fluency": settings.fluency_version,
        "guided_scenarios": scenario_catalog.content_version,
        "guided_engine": "guided-engine-v0.2",
        "guided_tts": "piper-1.6.0",
    }

    def initialize() -> None:
        repository.initialize()
        repository.set_runtime_setting("active_item_bank_version", item_bank.bank.version)

    app.state.initialize_tutor_modules = initialize
    app.add_middleware(SecurityAndObservabilityMiddleware, settings=settings, metrics=metrics)
    app.include_router(assessment_router)
    app.include_router(fluency_router)
    app.include_router(guided_router)
    app.include_router(guided_admin_router)
    app.include_router(practice_sessions_router)
    app.include_router(assessment_sessions_router)
    install_tutor_openapi_security(app)
    install_guided_exception_handlers(app)
    install_assessment_exception_handlers(app, metrics)
    return settings


def install_assessment_exception_handlers(app: FastAPI, metrics: ServiceMetrics) -> None:
    @app.exception_handler(AssessmentNotFound)
    async def not_found(_request: Request, _exc: AssessmentNotFound):
        return JSONResponse(status_code=404, content={"detail": "Assessment not found"})

    @app.exception_handler(SubmissionConflict)
    async def conflict(_request: Request, exc: SubmissionConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidAssessmentState)
    async def invalid_state(_request: Request, exc: InvalidAssessmentState):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EvaluationUnavailable)
    async def evaluator_unavailable(_request: Request, exc: EvaluationUnavailable):
        metrics.observe_evaluator_failure()
        retry_after_seconds = exc.retry_after_seconds
        if retry_after_seconds is None:
            retry_after_seconds = 5 if exc.retryable else 30
        retry_after = str(max(1, math.ceil(retry_after_seconds)))
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "The scoring evaluator is temporarily unavailable; the same idempotent "
                    "response can be retried without repeating the learner's answer."
                ),
                "error_code": exc.category,
                "provider": exc.provider,
                "provider_status": exc.status_code,
                "retryable": exc.retryable,
            },
            headers={"Retry-After": retry_after},
        )
