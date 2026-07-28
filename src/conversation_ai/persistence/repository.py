from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..metadata import SessionJobMetadata
from .models import ConversationSession, ConversationTurn, SessionEvent


class SessionAlreadyExistsError(RuntimeError):
    pass


class SessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(
        self,
        metadata: SessionJobMetadata,
        *,
        job_id: str | None,
        room_name: str,
        room_sid: str | None,
        started_at: datetime | None = None,
    ) -> ConversationSession:
        row = ConversationSession(
            session_id=metadata.session_id,
            subject_id=metadata.subject_id,
            schema_version=metadata.schema_version,
            lesson_id=metadata.lesson_id,
            locale=metadata.locale,
            livekit_job_id=job_id,
            livekit_room_sid=room_sid,
            room_name=room_name,
            status="active",
            dispatch_metadata=metadata.model_dump(mode="json", exclude_none=True),
            started_at=started_at or datetime.now(UTC),
        )
        async with self._session_factory() as session:
            if await session.get(ConversationSession, metadata.session_id):
                raise SessionAlreadyExistsError(f"Session {metadata.session_id} already exists")
            session.add(row)
            await session.commit()
            return row

    async def upsert_turn(
        self,
        *,
        session_id: uuid.UUID,
        item_id: str,
        sequence: int,
        role: str,
        text: str,
        interrupted: bool,
        metrics: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationTurn).where(
                    ConversationTurn.session_id == session_id,
                    ConversationTurn.item_id == item_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = ConversationTurn(
                    session_id=session_id,
                    item_id=item_id,
                    sequence=sequence,
                    role=role,
                    text=text,
                    interrupted=interrupted,
                    metrics=metrics,
                    occurred_at=occurred_at,
                )
                session.add(row)
            else:
                row.role = role
                row.text = text
                row.interrupted = interrupted
                row.metrics = metrics
                row.occurred_at = occurred_at
            await session.commit()

    async def append_event(
        self,
        *,
        session_id: uuid.UUID,
        sequence: int,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SessionEvent).where(
                    SessionEvent.session_id == session_id,
                    SessionEvent.sequence == sequence,
                )
            )
            if result.scalar_one_or_none() is None:
                session.add(
                    SessionEvent(
                        session_id=session_id,
                        sequence=sequence,
                        event_type=event_type,
                        payload=payload,
                        occurred_at=occurred_at,
                    )
                )
                await session.commit()

    async def finalize_session(
        self,
        session_id: uuid.UUID,
        *,
        status: str,
        ended_at: datetime,
        final_report: dict[str, Any],
        model_usage: list[dict[str, Any]] | None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(ConversationSession, session_id)
            if row is None:
                return
            row.status = status
            row.ended_at = ended_at
            row.final_report = final_report
            row.model_usage = model_usage
            row.error_type = error_type
            row.error_message = error_message
            await session.commit()

    async def mark_failed(
        self,
        session_id: uuid.UUID,
        *,
        error_type: str,
        error_message: str,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(ConversationSession, session_id)
            if row is None:
                return
            row.status = "failed"
            row.error_type = error_type
            row.error_message = error_message
            await session.commit()

    async def get_session(self, session_id: uuid.UUID) -> ConversationSession | None:
        async with self._session_factory() as session:
            return await session.get(ConversationSession, session_id)

    async def list_turns(
        self, session_id: uuid.UUID, *, after: int = 0, limit: int = 20
    ) -> list[ConversationTurn]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationTurn)
                .where(
                    ConversationTurn.session_id == session_id,
                    ConversationTurn.sequence > after,
                )
                .order_by(ConversationTurn.sequence.asc())
                .limit(limit)
            )
            return list(result.scalars())

    async def list_events(
        self, session_id: uuid.UUID, *, after: int = 0, limit: int = 20
    ) -> list[SessionEvent]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SessionEvent)
                .where(
                    SessionEvent.session_id == session_id,
                    SessionEvent.sequence > after,
                )
                .order_by(SessionEvent.sequence.asc())
                .limit(limit)
            )
            return list(result.scalars())

    async def list_subject_sessions(
        self,
        subject_id: uuid.UUID,
        *,
        before_at: datetime | None,
        before_id: uuid.UUID | None,
        limit: int = 20,
    ) -> list[ConversationSession]:
        filters = [ConversationSession.subject_id == subject_id]
        if before_at is not None and before_id is not None:
            filters.append(
                or_(
                    ConversationSession.started_at < before_at,
                    and_(
                        ConversationSession.started_at == before_at,
                        ConversationSession.session_id < before_id,
                    ),
                )
            )
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationSession)
                .where(*filters)
                .order_by(
                    ConversationSession.started_at.desc(),
                    ConversationSession.session_id.desc(),
                )
                .limit(limit)
            )
            return list(result.scalars())

    async def delete_session(self, session_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ConversationSession).where(ConversationSession.session_id == session_id)
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_subject(self, subject_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ConversationSession).where(ConversationSession.subject_id == subject_id)
            )
            await session.commit()
            return int(result.rowcount or 0)

