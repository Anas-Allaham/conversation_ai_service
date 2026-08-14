from __future__ import annotations

import contextlib
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import API_VERSION, SERVICE_NAME, Settings, get_settings
from ..log_config import configure_logging
from ..orchestration import LiveKitConversationGateway
from ..persistence import Database
from .envelopes import REQUEST_ID_HEADER, error, success
from .errors import ServiceError
from .routes import router

logger = logging.getLogger("conversation-ai.api")


def create_app(
    *,
    settings_override: Settings | None = None,
    database_override: Database | None = None,
    livekit_gateway_override: LiveKitConversationGateway | None = None,
) -> FastAPI:
    runtime_settings = settings_override or get_settings()
    configure_logging(runtime_settings.log_level)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        owned_database = False
        database = database_override
        if database is None and runtime_settings.database_url.get_secret_value():
            database = Database(runtime_settings.database_url.get_secret_value())
            owned_database = True
        app.state.database = database
        try:
            yield
        finally:
            if owned_database and database is not None:
                await database.dispose()

    app = FastAPI(
        title="Conversation AI Service",
        version=API_VERSION,
        description=(
            "Internal, subject-scoped access to persisted realtime English-tutor sessions. "
            "The API owns LiveKit room creation, agent dispatch, and session queries."
        ),
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.database = database_override
    app.state.livekit_gateway = livekit_gateway_override

    @app.middleware("http")
    async def request_identifier(request: Request, call_next):
        request.state.request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        return response

    register_error_handlers(app)

    @app.get("/")
    async def root(request: Request):
        return success(
            request,
            {"service": SERVICE_NAME, "api_version": API_VERSION, "docs": "/docs"},
        )

    @app.get("/health/live")
    async def health_live(request: Request):
        return success(request, {"status": "live"})

    @app.get("/health/ready")
    async def health_ready(request: Request):
        database = request.app.state.database
        if (
            database is None
            or not runtime_settings.api_auth_configured
            or not runtime_settings.conversation_start_configured
        ):
            return JSONResponse(
                status_code=503,
                content=error(
                    request,
                    code="not_ready",
                    message=(
                        "Database, service authentication, or LiveKit orchestration "
                        "is not configured."
                    ),
                ),
            )
        try:
            await database.ping()
        except Exception:
            logger.exception("readiness_database_failure")
            return JSONResponse(
                status_code=503,
                content=error(
                    request,
                    code="not_ready",
                    message="The session database is unavailable.",
                ),
            )
        return success(request, {"status": "ready"})

    app.include_router(router)
    return app


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error(
                request,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {
                "location": [str(part) for part in item.get("loc", [])],
                "message": item.get("msg", ""),
                "type": item.get("type", ""),
            }
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error(
                request,
                code="validation_error",
                message="Request validation failed.",
                details={"errors": details},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error(request, code="http_error", message=message),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("unhandled_api_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content=error(
                request,
                code="internal_error",
                message="An unexpected error occurred.",
            ),
        )


app = create_app()
