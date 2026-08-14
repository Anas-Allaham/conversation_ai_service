from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from livekit.agents.llm import ChatMessage

from ..metadata import SessionJobMetadata
from ..persistence import Database, SessionRepository
from ..persistence.serialization import safe_error_text, sanitize_json

logger = logging.getLogger("conversation-ai.persistence")


def timestamp(value: float | int | None = None) -> datetime:
    return datetime.fromtimestamp(float(value or time.time()), tz=timezone.utc)


class JobPersistence:
    """Non-blocking turn/event writes plus final idempotent report reconciliation."""

    def __init__(self, database_url: str, metadata: SessionJobMetadata) -> None:
        self.database = Database(database_url)
        self.repository = SessionRepository(self.database.session_factory)
        self.metadata = metadata
        self._pending: set[asyncio.Task[None]] = set()
        self._turn_sequence = 0
        self._event_sequence = 0
        self._unrecoverable_error: tuple[str, str] | None = None

    async def start(
        self, *, job_id: str | None, room_name: str, room_sid: str | None
    ) -> None:
        await self.database.ping()
        await self.repository.create_session(
            self.metadata,
            job_id=job_id,
            room_name=room_name,
            room_sid=room_sid,
        )
        self.record_event("session_started", {"room_name": room_name})

    def _schedule(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._pending.add(task)

        def done(completed: asyncio.Task[None]) -> None:
            self._pending.discard(completed)
            try:
                completed.result()
            except Exception as exc:
                logger.error(
                    "incremental_persistence_failed",
                    extra={
                        "session_id": str(self.metadata.session_id),
                        "error_type": type(exc).__name__,
                    },
                )

        task.add_done_callback(done)

    def record_turn(self, item: ChatMessage, *, occurred_at: float | None = None) -> None:
        role = getattr(item.role, "value", str(item.role))
        if role not in {"user", "assistant"}:
            return
        self._turn_sequence += 1
        metrics = sanitize_json(getattr(item, "metrics", {}) or {}) or {}
        self._schedule(
            self.repository.upsert_turn(
                session_id=self.metadata.session_id,
                item_id=item.id,
                sequence=self._turn_sequence,
                role=role,
                text=item.text_content or "",
                interrupted=bool(item.interrupted),
                metrics=metrics,
                occurred_at=timestamp(occurred_at or item.created_at),
            )
        )

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        occurred_at: float | None = None,
    ) -> None:
        self._event_sequence += 1
        self._schedule(
            self.repository.append_event(
                session_id=self.metadata.session_id,
                sequence=self._event_sequence,
                event_type=event_type,
                payload=sanitize_json(payload) or {},
                occurred_at=timestamp(occurred_at),
            )
        )

    def record_error(
        self,
        *,
        error: object,
        source: object,
        recoverable: bool,
        occurred_at: float | None,
    ) -> None:
        error_type = type(error).__name__
        message = safe_error_text(error)
        self.record_event(
            "error",
            {
                "error_type": error_type,
                "message": message,
                "source": type(source).__name__,
                "recoverable": recoverable,
            },
            occurred_at=occurred_at,
        )
        if not recoverable:
            self._unrecoverable_error = (error_type, message)

    async def flush(self) -> None:
        while self._pending:
            pending = list(self._pending)
            await asyncio.gather(*pending, return_exceptions=True)

    async def reconcile_history(self, items: list[Any]) -> None:
        sequence = 0
        for item in items:
            if not isinstance(item, ChatMessage):
                continue
            role = getattr(item.role, "value", str(item.role))
            if role not in {"user", "assistant"}:
                continue
            sequence += 1
            await self.repository.upsert_turn(
                session_id=self.metadata.session_id,
                item_id=item.id,
                sequence=sequence,
                role=role,
                text=item.text_content or "",
                interrupted=bool(item.interrupted),
                metrics=sanitize_json(getattr(item, "metrics", {}) or {}) or {},
                occurred_at=timestamp(item.created_at),
            )

    async def finalize(self, *, report: object, history_items: list[Any]) -> None:
        await self.flush()
        await self.reconcile_history(history_items)

        raw_report = report.to_dict() if hasattr(report, "to_dict") else report
        final_report = sanitize_json(raw_report) or {}
        raw_usage = getattr(report, "model_usage", None)
        model_usage = sanitize_json(raw_usage) if raw_usage is not None else None
        error_type = self._unrecoverable_error[0] if self._unrecoverable_error else None
        error_message = self._unrecoverable_error[1] if self._unrecoverable_error else None

        await self.repository.finalize_session(
            self.metadata.session_id,
            status="failed" if self._unrecoverable_error else "completed",
            ended_at=datetime.now(timezone.utc),
            final_report=final_report,
            model_usage=model_usage,
            error_type=error_type,
            error_message=error_message,
        )

    async def fail_before_session_end(self, error: Exception) -> None:
        self._unrecoverable_error = (type(error).__name__, safe_error_text(error))
        await self.repository.mark_failed(
            self.metadata.session_id,
            error_type=self._unrecoverable_error[0],
            error_message=self._unrecoverable_error[1],
        )

    async def close(self) -> None:
        await self.database.dispose()
