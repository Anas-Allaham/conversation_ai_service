from __future__ import annotations

from fastapi import Request

from ..orchestration import LiveKitConversationGateway
from ..persistence import SessionRepository
from .errors import NotConfiguredError, NotReadyError


def repository(request: Request) -> SessionRepository:
    database = request.app.state.database
    if database is None:
        raise NotReadyError("The session database is not configured.")
    return SessionRepository(database.session_factory)


def livekit_gateway(request: Request) -> LiveKitConversationGateway:
    override = request.app.state.livekit_gateway
    if override is not None:
        return override
    try:
        return LiveKitConversationGateway(request.app.state.settings)
    except RuntimeError as exc:
        raise NotConfiguredError("LiveKit conversation start is not configured.") from exc
