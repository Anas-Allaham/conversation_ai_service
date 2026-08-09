from __future__ import annotations

import hmac
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import ClassVar

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Settings
from .metrics import ServiceMetrics

CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class SlidingWindowRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


class SecurityAndObservabilityMiddleware(BaseHTTPMiddleware):
    PUBLIC_PATHS: ClassVar[set[str]] = {
        "/health/live",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    def __init__(self, app, settings: Settings, metrics: ServiceMetrics) -> None:
        super().__init__(app)
        self.settings = settings
        self.metrics = metrics
        self.rate_limiter = SlidingWindowRateLimiter(settings.rate_limit_per_minute)

    @staticmethod
    def _bearer(request: Request) -> str:
        value = request.headers.get("authorization", "")
        if not value.lower().startswith("bearer "):
            return ""
        return value[7:].strip()

    def _expected_token(self, path: str) -> str:
        if path.startswith("/v1/admin"):
            return self.settings.admin_token
        if path == "/v1/pronunciation/callback":
            return self.settings.pronunciation_service_token
        return self.settings.service_token

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        supplied_correlation = request.headers.get("x-correlation-id", "")
        correlation_id = (
            supplied_correlation if CORRELATION_RE.fullmatch(supplied_correlation) else str(uuid.uuid4())
        )
        request.state.correlation_id = correlation_id
        path = request.url.path
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > self.settings.max_body_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "Request body is too large"})
                    response.headers["X-Correlation-ID"] = correlation_id
                    return response
            except ValueError:
                pass

        if path not in self.PUBLIC_PATHS and not path.startswith("/docs"):
            token = self._bearer(request)
            expected = self._expected_token(path)
            if not expected or not hmac.compare_digest(token, expected):
                response = JSONResponse(status_code=401, content={"detail": "Invalid service credential"})
                response.headers["X-Correlation-ID"] = correlation_id
                return response
            remote = request.client.host if request.client else "unknown"
            if not self.rate_limiter.allow(f"{remote}:{token[:12]}"):
                response = JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
                response.headers["Retry-After"] = "60"
                response.headers["X-Correlation-ID"] = correlation_id
                return response

        try:
            response = await call_next(request)
        except Exception:
            latency = time.perf_counter() - started
            self.metrics.observe_request(request.method, path, 500, latency)
            raise
        latency = time.perf_counter() - started
        self.metrics.observe_request(request.method, path, response.status_code, latency)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response
