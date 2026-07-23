"""add outbox_events.next_attempt_at (outbox relay backoff)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "next_attempt_at")
