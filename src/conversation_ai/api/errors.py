from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class UnauthorizedError(ServiceError):
    status_code = 401
    code = "unauthorized"


class NotConfiguredError(ServiceError):
    status_code = 503
    code = "service_not_configured"


class NotReadyError(ServiceError):
    status_code = 503
    code = "service_not_ready"


class NotFoundError(ServiceError):
    status_code = 404
    code = "not_found"


class InvalidCursorError(ServiceError):
    status_code = 422
    code = "invalid_cursor"


class ConflictError(ServiceError):
    status_code = 409
    code = "conflict"


class UpstreamServiceError(ServiceError):
    status_code = 503
    code = "upstream_service_error"
