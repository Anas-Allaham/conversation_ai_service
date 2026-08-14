"""Track the LiveKit dispatch created by the start API.

Revision ID: 0002_dispatch_id
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_dispatch_id"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_sessions",
        sa.Column("livekit_dispatch_id", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        "uq_conversation_sessions_livekit_dispatch_id",
        "conversation_sessions",
        ["livekit_dispatch_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_conversation_sessions_livekit_dispatch_id",
        "conversation_sessions",
        type_="unique",
    )
    op.drop_column("conversation_sessions", "livekit_dispatch_id")
