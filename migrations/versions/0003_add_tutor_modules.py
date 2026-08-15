"""Add placement, fluency, and deterministic guided-practice tables.

Revision ID: 0003_tutor_modules
Revises: 0002_dispatch_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tutor_modules"
down_revision: str | None = "0002_dispatch_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assessments",
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "responses",
        sa.Column("assessment_id", sa.Text(), nullable=False),
        sa.Column("response_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("prompt_kind", sa.Text(), nullable=False),
        sa.Column("stored_response_json", sa.Text(), nullable=False),
        sa.Column("api_result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.assessment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("assessment_id", "response_id"),
        sa.UniqueConstraint(
            "assessment_id", "idempotency_key", name="uq_responses_assessment_idempotency"
        ),
    )
    op.create_index(
        "idx_responses_assessment_prompt",
        "responses",
        ["assessment_id", "prompt_kind", "item_id"],
    )
    op.create_table(
        "pronunciation_diagnostics",
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessments.assessment_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", sa.Text(), primary_key=True),
        sa.Column("assessment_id", sa.Text()),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_audit_assessment_created", "audit_logs", ["assessment_id", "created_at"]
    )
    op.create_table(
        "runtime_settings",
        sa.Column("setting_key", sa.Text(), primary_key=True),
        sa.Column("setting_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "fluency_observations",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "turn_id"),
    )
    op.create_index(
        "idx_fluency_observations_session_created",
        "fluency_observations",
        ["session_id", "created_at"],
    )
    op.create_table(
        "guided_sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("scenario_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_guided_sessions_user_updated", "guided_sessions", ["user_id", "updated_at"]
    )
    op.create_table(
        "guided_attempt_replays",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("api_result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["guided_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id", "attempt_id"),
        sa.UniqueConstraint(
            "session_id", "idempotency_key", name="uq_guided_attempt_idempotency"
        ),
    )
    op.create_table(
        "guided_audio_assets",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("audio_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["guided_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id", "attempt_id"),
    )


def downgrade() -> None:
    op.drop_table("guided_audio_assets")
    op.drop_table("guided_attempt_replays")
    op.drop_index("idx_guided_sessions_user_updated", table_name="guided_sessions")
    op.drop_table("guided_sessions")
    op.drop_index(
        "idx_fluency_observations_session_created", table_name="fluency_observations"
    )
    op.drop_table("fluency_observations")
    op.drop_table("runtime_settings")
    op.drop_index("idx_audit_assessment_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("pronunciation_diagnostics")
    op.drop_index("idx_responses_assessment_prompt", table_name="responses")
    op.drop_table("responses")
    op.drop_table("assessments")
