from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request

from ..config import API_VERSION, SERVICE_NAME

REQUEST_ID_HEADER = "X-Request-ID"


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex


def meta(request: Request) -> dict[str, str]:
    return {
        "service": SERVICE_NAME,
        "api_version": API_VERSION,
        "request_id": request_id(request),
    }


def success(request: Request, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": meta(request)}


def error(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": meta(request),
    }

