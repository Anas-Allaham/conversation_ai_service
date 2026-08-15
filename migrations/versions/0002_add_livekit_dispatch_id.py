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
    with op.batch_alter_table("conversation_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("livekit_dispatch_id", sa.String(length=128), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_conversation_sessions_livekit_dispatch_id",
            ["livekit_dispatch_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_sessions") as batch_op:
        batch_op.drop_constraint(
            "uq_conversation_sessions_livekit_dispatch_id",
            type_="unique",
        )
        batch_op.drop_column("livekit_dispatch_id")
