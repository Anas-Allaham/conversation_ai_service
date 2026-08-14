from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


class AssessmentClientError(RuntimeError):
    pass


class AssessmentServiceUnavailable(AssessmentClientError):
    pass


class AssessmentHTTPError(AssessmentClientError):
    """The service responded, but rejected or could not complete the request."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        error_code: str | None = None,
        retry_after_seconds: float | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        self.retryable = status_code >= 500 if retryable is None else retryable
        super().__init__(f"Assessment service HTTP {status_code}: {detail}")


class AssessmentPayloadRejected(AssessmentHTTPError):
    """FastAPI rejected the submitted JSON before assessment state changed."""


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    reset_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def before_request(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.reset_seconds:
            self.failures = 0
            self.opened_at = None
            return
        raise AssessmentServiceUnavailable("Assessment service circuit breaker is open")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


class AssessmentClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("ASSESSMENT_SERVICE_URL", "http://127.0.0.1:8080")
        ).rstrip("/")
        self.token = token or os.getenv("ASSESSMENT_SERVICE_TOKEN", "")
        self.timeout = timeout_seconds or float(
            os.getenv("ASSESSMENT_REQUEST_TIMEOUT_SECONDS", "90")
        )
        self.breaker = CircuitBreaker()
        self._lock = threading.Lock()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_idempotently: bool = False,
        raw_body: bytes | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.breaker.before_request()
        body = raw_body
        request_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-Correlation-ID": f"livekit-{uuid.uuid4()}",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        attempts = 2 if retry_idempotently else 1
        last_error: Exception | None = None
        last_http_error: AssessmentHTTPError | None = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=body,
                method=method,
                headers=request_headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    content = response.read()
                    result = json.loads(content) if content else {}
                with self._lock:
                    self.breaker.success()
                return result
            except urllib.error.HTTPError as exc:
                raw_detail = exc.read().decode(errors="replace")
                error_code = None
                retryable = exc.code >= 500
                try:
                    decoded = json.loads(raw_detail)
                    detail = str(decoded.get("detail") or raw_detail)
                    error_code = decoded.get("error_code")
                    retryable = bool(decoded.get("retryable", retryable))
                except (json.JSONDecodeError, AttributeError):
                    detail = raw_detail
                retry_after = exc.headers.get("Retry-After")
                try:
                    retry_after_seconds = float(retry_after) if retry_after else None
                except ValueError:
                    retry_after_seconds = None
                with self._lock:
                    # The service was reached successfully. Provider-side 5xx
                    # errors must not open the transport circuit breaker.
                    self.breaker.success()
                if exc.code == 422:
                    raise AssessmentPayloadRejected(
                        exc.code,
                        detail,
                        error_code=error_code,
                        retry_after_seconds=retry_after_seconds,
                        retryable=False,
                    ) from exc
                # A reached service can tell us exactly when evaluator scoring
                # may be retried. Do not immediately duplicate that expensive
                # request; the LiveKit adapter preserves the idempotent answer
                # and presents the provider's wait time to the learner.
                if (
                    exc.code < 500
                    or not retry_idempotently
                    or not retryable
                    or retry_after_seconds is not None
                ):
                    raise AssessmentHTTPError(
                        exc.code,
                        detail,
                        error_code=error_code,
                        retry_after_seconds=retry_after_seconds,
                        retryable=retryable,
                    ) from exc
                last_http_error = AssessmentHTTPError(
                    exc.code,
                    detail,
                    error_code=error_code,
                    retry_after_seconds=retry_after_seconds,
                    retryable=retryable,
                )
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt + 1 < attempts:
                delay = (
                    last_http_error.retry_after_seconds
                    if last_http_error and last_http_error.retry_after_seconds is not None
                    else 1.0 + random.random() * 0.35
                )
                time.sleep(min(10.0, max(0.0, delay)))
        if last_http_error is not None:
            raise last_http_error from last_error
        with self._lock:
            self.breaker.failure()
        raise AssessmentServiceUnavailable("Assessment service request failed") from last_error

    def create_assessment(self, user_id: str, interface_language: str = "en") -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/assessments",
            payload={
                "user_id": user_id,
                "assessment_type": "conversational-placement",
                "target_range": ["A1", "A2", "B1", "B2"],
                "language": "en",
                "interface_language": interface_language,
            },
        )

    def submit_response(self, assessment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/assessments/{assessment_id}/responses",
            payload=payload,
            headers={"Idempotency-Key": str(payload["idempotency_key"])},
            retry_idempotently=True,
        )

    def get_result(self, assessment_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/v1/assessments/{assessment_id}/result", retry_idempotently=True
        )

    def get_assessment_state(self, assessment_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/assessments/{assessment_id}", retry_idempotently=True)

    def submit_fluency_turn(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/fluency/sessions/{session_id}/turns",
            payload=payload,
            retry_idempotently=True,
        )

    def get_fluency_session(self, session_id: str, mode: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/fluency/sessions/{session_id}?mode={mode}",
            retry_idempotently=True,
        )

    def get_guided_session(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/guided-conversations/sessions/{session_id}",
            retry_idempotently=True,
        )

    def mark_guided_prompt_ready(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guided-conversations/sessions/{session_id}/prompt-ready",
            payload={},
            retry_idempotently=True,
        )

    def submit_guided_attempt(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/guided-conversations/sessions/{session_id}/attempts",
            payload=payload,
            headers={"Idempotency-Key": str(payload["idempotency_key"])},
            retry_idempotently=True,
        )

    def guided_control(self, session_id: str, command: str) -> dict[str, Any]:
        if command not in {"continue", "retry", "pause", "resume", "stop"}:
            raise ValueError("Unsupported guided conversation command")
        return self._request(
            "POST",
            f"/v1/guided-conversations/sessions/{session_id}/{command}",
            payload={},
            retry_idempotently=True,
        )

    def upload_audio(
        self,
        assessment_id: str,
        response_id: str,
        wav_bytes: bytes,
    ) -> str:
        boundary = f"----assessment-{uuid.uuid4().hex}"
        prefix = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="audio"; filename="raw.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        body = prefix + wav_bytes + f"\r\n--{boundary}--\r\n".encode()
        result = self._request(
            "POST",
            f"/v1/assessments/{assessment_id}/audio/{response_id}",
            raw_body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            retry_idempotently=False,
        )
        return str(result["audio_uri"])

    def upload_guided_audio(
        self,
        session_id: str,
        attempt_id: str,
        wav_bytes: bytes,
    ) -> str:
        boundary = f"----guided-{uuid.uuid4().hex}"
        prefix = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="audio"; filename="raw.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode()
        body = prefix + wav_bytes + f"\r\n--{boundary}--\r\n".encode()
        result = self._request(
            "POST",
            f"/v1/guided-conversations/sessions/{session_id}/audio/{attempt_id}",
            raw_body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            retry_idempotently=False,
        )
        return str(result["audio_uri"])

    async def create_assessment_async(
        self, user_id: str, interface_language: str = "en"
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.create_assessment, user_id, interface_language)

    async def submit_response_async(
        self, assessment_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.submit_response, assessment_id, payload)

    async def get_result_async(self, assessment_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_result, assessment_id)

    async def get_assessment_state_async(self, assessment_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_assessment_state, assessment_id)

    async def submit_fluency_turn_async(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.submit_fluency_turn, session_id, payload)

    async def get_fluency_session_async(
        self,
        session_id: str,
        mode: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_fluency_session, session_id, mode)

    async def get_guided_session_async(self, session_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_guided_session, session_id)

    async def mark_guided_prompt_ready_async(self, session_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.mark_guided_prompt_ready, session_id)

    async def submit_guided_attempt_async(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.submit_guided_attempt, session_id, payload)

    async def guided_control_async(
        self,
        session_id: str,
        command: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.guided_control, session_id, command)

    async def upload_audio_async(
        self, assessment_id: str, response_id: str, wav_bytes: bytes
    ) -> str:
        return await asyncio.to_thread(self.upload_audio, assessment_id, response_id, wav_bytes)

    async def upload_guided_audio_async(
        self,
        session_id: str,
        attempt_id: str,
        wav_bytes: bytes,
    ) -> str:
        return await asyncio.to_thread(
            self.upload_guided_audio,
            session_id,
            attempt_id,
            wav_bytes,
        )
