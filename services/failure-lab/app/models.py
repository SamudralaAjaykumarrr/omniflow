import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Run status vocabulary. RUNNING is transient; every other value is terminal.
# RECOVERED is used (instead of the generic PASSED) for scenarios whose
# whole point is demonstrating recovery from an injected failure
# (payment-timeout, downstream-outage, saga-crash-resume) — see
# docs/phase-8-failure-laboratory.md "Run status vocabulary".
STATUS_RUNNING = "RUNNING"
STATUS_PASSED = "PASSED"
STATUS_RECOVERED = "RECOVERED"
STATUS_FAILED = "FAILED"
STATUS_ERROR = "ERROR"

TERMINAL_STATUSES = {STATUS_PASSED, STATUS_RECOVERED, STATUS_FAILED, STATUS_ERROR}


class ScenarioRun(Base):
    """One row per scenario execution. `diagnostics`/`resources` are JSON
    scratchpads: `diagnostics` holds whatever the scenario wants to show an
    operator (intermediate observations, assertion results); `resources`
    holds the ids of anything the run created in another service (order_id,
    dead_letter_id, ...) so `reset()` and future debugging can find them.
    """

    __tablename__ = "scenario_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_RUNNING)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScenarioReset(Base):
    """One row per reset() invocation — surfaced on the catalog so the
    dashboard can show "last reset" alongside "last run"."""

    __tablename__ = "scenario_resets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FailureLabDeadLetter(Base):
    """Dead letters produced by the failure lab's own poison-message
    consumer (app.poison_consumer) — deliberately separate from
    fulfillment-orchestrator's `dead_letter_events` table: this consumer
    exists only to demonstrate the generic retry/backoff/DLQ mechanism in
    isolation, on a dedicated topic no real business consumer subscribes
    to, and must never be confused with a real production dead letter."""

    __tablename__ = "failure_lab_dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    error_type: Mapped[str] = mapped_column(String(200), nullable=False)
    error_message: Mapped[str] = mapped_column(String(2000), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
