from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ..orchestration import (
    ConversationCannotRestartError,
    ConversationOrchestrator,
    ConversationStartConflictError,
    LiveKitConversationGateway,
)
from ..persistence.cursor import InvalidCursor, datetime_cursor, decode_cursor, encode_cursor
from ..persistence.repository import SessionRepository
from ..persistence.serialization import safe_error_text
from .dependencies import livekit_gateway, repository
from .envelopes import success
from .errors import ConflictError, InvalidCursorError, NotFoundError, UpstreamServiceError
from .schemas import StartConversationRequest
from .security import require_service_auth
from .serializers import event_data, session_data, session_summary, turn_data

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_service_auth)])
logger = logging.getLogger("conversation-ai.api.routes")
RepositoryDependency = Annotated[SessionRepository, Depends(repository)]
LiveKitGatewayDependency = Annotated[LiveKitConversationGateway, Depends(livekit_gateway)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def sequence_from_cursor(cursor: str | None) -> int:
    try:
        payload = decode_cursor(cursor)
        return int(payload["sequence"]) if payload else 0
    except (InvalidCursor, KeyError, TypeError, ValueError) as exc:
        raise InvalidCursorError("Cursor is malformed.") from exc


@router.get("/capabilities")
async def capabilities(request: Request):
    return success(
        request,
        {
            "agent_name": request.app.state.settings.livekit_agent_name,
            "transport": "livekit",
            "pipeline": ["deepgram-flux-stt", "livekit-inference-llm", "deepgram-tts"],
            "persistence": {
                "transcripts": True,
                "metrics": True,
                "events": True,
                "raw_audio": False,
                "retention": "until-deleted",
            },
            "job_metadata_schema_version": 1,
        },
    )


@router.post("/sessions/start")
async def start_session(
    request: Request,
    payload: StartConversationRequest,
    repo: RepositoryDependency,
    gateway: LiveKitGatewayDependency,
):
    metadata = payload.job_metadata()
    try:
        connection = await ConversationOrchestrator(repo, gateway).start(metadata)
    except (ConversationStartConflictError, ConversationCannotRestartError) as exc:
        raise ConflictError(str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "conversation_start_failed",
            extra={
                "session_id": str(payload.session_id),
                "error_type": type(exc).__name__,
                "error_detail": safe_error_text(exc),
            },
        )
        raise UpstreamServiceError("LiveKit could not start the conversation.") from exc

    return success(
        request,
        {
            "session_id": str(payload.session_id),
            "token": connection.token,
            "room_name": connection.room_name,
            "ws_url": connection.ws_url,
        },
    )


@router.get("/sessions/{session_id}")
async def get_session(
    request: Request,
    session_id: uuid.UUID,
    repo: RepositoryDependency,
):
    row = await repo.get_session(session_id)
    if row is None:
        raise NotFoundError("Conversation session was not found.")
    return success(request, session_data(row))


@router.get("/sessions/{session_id}/turns")
async def get_turns(
    request: Request,
    session_id: uuid.UUID,
    repo: RepositoryDependency,
    cursor: str | None = None,
    limit: PageLimit = 20,
):
    if await repo.get_session(session_id) is None:
        raise NotFoundError("Conversation session was not found.")
    after = sequence_from_cursor(cursor)
    rows = await repo.list_turns(session_id, after=after, limit=limit + 1)
    page = rows[:limit]
    next_cursor = (
        encode_cursor({"sequence": page[-1].sequence}) if len(rows) > limit and page else None
    )
    return success(
        request,
        {"items": [turn_data(row) for row in page], "next_cursor": next_cursor},
    )


@router.get("/sessions/{session_id}/events")
async def get_events(
    request: Request,
    session_id: uuid.UUID,
    repo: RepositoryDependency,
    cursor: str | None = None,
    limit: PageLimit = 20,
):
    if await repo.get_session(session_id) is None:
        raise NotFoundError("Conversation session was not found.")
    after = sequence_from_cursor(cursor)
    rows = await repo.list_events(session_id, after=after, limit=limit + 1)
    page = rows[:limit]
    next_cursor = (
        encode_cursor({"sequence": page[-1].sequence}) if len(rows) > limit and page else None
    )
    return success(
        request,
        {"items": [event_data(row) for row in page], "next_cursor": next_cursor},
    )


@router.get("/subjects/{subject_id}/sessions")
async def get_subject_sessions(
    request: Request,
    subject_id: uuid.UUID,
    repo: RepositoryDependency,
    cursor: str | None = None,
    limit: PageLimit = 20,
):
    before_at: datetime | None = None
    before_id: uuid.UUID | None = None
    if cursor:
        try:
            payload = decode_cursor(cursor) or {}
            before_at = datetime.fromisoformat(str(payload["at"]))
            before_id = uuid.UUID(str(payload["id"]))
        except (InvalidCursor, KeyError, TypeError, ValueError) as exc:
            raise InvalidCursorError("Cursor is malformed.") from exc

    rows = await repo.list_subject_sessions(
        subject_id,
        before_at=before_at,
        before_id=before_id,
        limit=limit + 1,
    )
    page = rows[:limit]
    next_cursor = (
        datetime_cursor(page[-1].started_at, page[-1].session_id)
        if len(rows) > limit and page
        else None
    )
    return success(
        request,
        {"items": [session_summary(row) for row in page], "next_cursor": next_cursor},
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    request: Request,
    session_id: uuid.UUID,
    repo: RepositoryDependency,
):
    deleted = await repo.delete_session(session_id)
    if not deleted:
        raise NotFoundError("Conversation session was not found.")
    return success(request, {"session_id": str(session_id), "deleted": True})


@router.delete("/subjects/{subject_id}")
async def delete_subject(
    request: Request,
    subject_id: uuid.UUID,
    repo: RepositoryDependency,
):
    deleted_sessions = await repo.delete_subject(subject_id)
    return success(
        request,
        {"subject_id": str(subject_id), "deleted_sessions": deleted_sessions},
    )
