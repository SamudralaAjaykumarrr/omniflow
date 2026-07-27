"""initial failure-lab schema

Revision ID: 0001
Revises:
Create Date: 2026-07-26

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("resources", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scenario_runs_scenario_id", "scenario_runs", ["scenario_id"])

    op.create_table(
        "scenario_resets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(2000), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scenario_resets_scenario_id", "scenario_resets", ["scenario_id"])

    op.create_table(
        "failure_lab_dead_letters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_type", sa.String(200), nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_failure_lab_dead_letters_original_event_id",
        "failure_lab_dead_letters",
        ["original_event_id"],
    )


def downgrade() -> None:
    op.drop_table("failure_lab_dead_letters")
    op.drop_table("scenario_resets")
    op.drop_table("scenario_runs")
