"""Create persisted conversation session tables.

Revision ID: 0001_initial
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.String(length=128), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("livekit_job_id", sa.String(length=128), nullable=True),
        sa.Column("livekit_room_sid", sa.String(length=128), nullable=True),
        sa.Column("room_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("dispatch_metadata", JSON_DOCUMENT, nullable=False),
        sa.Column("model_usage", JSON_DOCUMENT, nullable=True),
        sa.Column("final_report", JSON_DOCUMENT, nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('starting', 'active', 'completed', 'failed')",
            name="ck_conversation_sessions_status",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("livekit_job_id"),
    )
    op.create_index(
        "ix_conversation_sessions_subject_started",
        "conversation_sessions",
        ["subject_id", "started_at"],
    )

    op.create_table(
        "conversation_session_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", JSON_DOCUMENT, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
    )
    op.create_index(
        "ix_session_events_session_sequence",
        "conversation_session_events",
        ["session_id", "sequence"],
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("metrics", JSON_DOCUMENT, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'developer', 'tool')",
            name="ck_conversation_turns_role",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "item_id", name="uq_conversation_turn_item"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_conversation_turn_sequence"),
    )
    op.create_index(
        "ix_conversation_turns_session_sequence",
        "conversation_turns",
        ["session_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_session_sequence", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_session_events_session_sequence", table_name="conversation_session_events")
    op.drop_table("conversation_session_events")
    op.drop_index("ix_conversation_sessions_subject_started", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
