from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lesson_id: Mapped[str | None] = mapped_column(String(128))
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")

    livekit_job_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    livekit_room_sid: Mapped[str | None] = mapped_column(String(128))
    room_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="starting")

    dispatch_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    model_usage: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_DOCUMENT)
    final_report: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[SessionEvent]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('starting', 'active', 'completed', 'failed')",
            name="ck_conversation_sessions_status",
        ),
        Index("ix_conversation_sessions_subject_started", "subject_id", "started_at"),
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversation_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    interrupted: Mapped[bool] = mapped_column(nullable=False, default=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ConversationSession] = relationship(back_populates="turns")

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'developer', 'tool')",
            name="ck_conversation_turns_role",
        ),
        UniqueConstraint("session_id", "item_id", name="uq_conversation_turn_item"),
        UniqueConstraint("session_id", "sequence", name="uq_conversation_turn_sequence"),
        Index("ix_conversation_turns_session_sequence", "session_id", "sequence"),
    )


class SessionEvent(Base):
    __tablename__ = "conversation_session_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversation_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[ConversationSession] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
        Index("ix_session_events_session_sequence", "session_id", "sequence"),
    )

