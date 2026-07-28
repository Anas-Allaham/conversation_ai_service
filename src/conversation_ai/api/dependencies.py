from __future__ import annotations

from fastapi import Request

from ..persistence import SessionRepository
from .errors import NotReadyError


def repository(request: Request) -> SessionRepository:
    database = request.app.state.database
    if database is None:
        raise NotReadyError("The session database is not configured.")
    return SessionRepository(database.session_factory)

