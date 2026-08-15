from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import NotConfiguredError, UnauthorizedError

bearer = HTTPBearer(
    scheme_name="ServiceApiKey",
    description="Internal core-service Bearer credential.",
    auto_error=False,
)


def require_service_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> None:
    settings = request.app.state.settings
    expected = settings.service_api_key.get_secret_value()
    if not expected:
        raise NotConfiguredError("SERVICE_API_KEY is not configured.")
    presented = credentials.credentials.strip() if credentials else ""
    if not presented or not hmac.compare_digest(presented, expected):
        raise UnauthorizedError("Invalid or missing service credentials.")
