"""Executes scenarios out-of-request (a scenario can take several seconds —
saga completion, retry backoff, a DLQ row appearing — polling for those is
not something an HTTP request should block on) and persists their outcome.

`trigger()` creates a RUNNING `scenario_runs` row synchronously (so the
caller gets an id to poll immediately), then hands the actual execution to a
background thread. `reset()` runs synchronously — every scenario's reset is
a fast, local cleanup operation (re-seed a stock row, clear a table), never
worth the same async treatment.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.clients import (
    GatewayClient,
    InventoryServiceClient,
    OrchestratorClient,
    OrderServiceClient,
)
from app.config import Settings, get_settings
from app.kafka import build_producer
from app.metrics import (
    FAILURE_LAB_SCENARIO_DURATION_SECONDS,
    FAILURE_LAB_SCENARIO_RESETS_TOTAL,
    FAILURE_LAB_SCENARIO_RUNS_TOTAL,
)
from app.models import STATUS_ERROR, STATUS_RUNNING, ScenarioReset, ScenarioRun
from app.scenarios.base import ScenarioContext
from app.scenarios.registry import REGISTRY

logger = logging.getLogger("failure_lab.runner")


class UnknownScenarioError(Exception):
    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        super().__init__(f"no such scenario: {scenario_id!r}")


def _require_entry(scenario_id: str):
    entry = REGISTRY.get(scenario_id)
    if entry is None:
        raise UnknownScenarioError(scenario_id)
    return entry


def _build_context(settings: Settings, db: Session, correlation_id: str) -> ScenarioContext:
    return ScenarioContext(
        settings=settings,
        gateway=GatewayClient(
            settings.api_gateway_url,
            service_email=settings.gateway_service_email,
            service_password=settings.gateway_service_password,
        ),
        order_service=OrderServiceClient(settings.order_service_url),
        inventory=InventoryServiceClient(settings.inventory_service_url),
        orchestrator=OrchestratorClient(settings.orchestrator_service_url),
        correlation_id=correlation_id,
        db=db,
        producer_factory=lambda: build_producer(settings.kafka_bootstrap_servers),
    )


def _next_run_number(db: Session, scenario_id: str) -> int:
    count = db.execute(
        select(func.count()).select_from(ScenarioRun).where(ScenarioRun.scenario_id == scenario_id)
    ).scalar_one()
    return count + 1


def _execute(session_factory: sessionmaker, scenario_id: str, run_id: uuid.UUID) -> None:
    entry = _require_entry(scenario_id)
    settings = get_settings()
    start = time.monotonic()
    final_status = STATUS_ERROR
    with session_factory() as db:
        run_row = db.get(ScenarioRun, run_id)
        assert run_row is not None
        ctx = _build_context(settings, db, str(run_row.correlation_id))
        try:
            outcome = entry.run(ctx)
        except Exception as exc:  # noqa: BLE001 - a run must never stay stuck RUNNING
            logger.exception("scenario %s run %s crashed", scenario_id, run_id)
            run_row.status = STATUS_ERROR
            run_row.summary = f"Unhandled error: {exc}"
            run_row.error_message = str(exc)
        else:
            run_row.status = outcome.status
            run_row.summary = outcome.summary
            run_row.diagnostics = outcome.diagnostics
            run_row.resources = outcome.resources
        run_row.completed_at = datetime.now(UTC)
        final_status = run_row.status
        db.commit()

    duration = time.monotonic() - start
    FAILURE_LAB_SCENARIO_DURATION_SECONDS.labels(scenario_id).observe(duration)
    FAILURE_LAB_SCENARIO_RUNS_TOTAL.labels(scenario_id, final_status).inc()
    logger.info(
        "scenario %s run %s finished: %s (%.2fs)", scenario_id, run_id, final_status, duration
    )


def trigger(db: Session, session_factory: sessionmaker, scenario_id: str) -> ScenarioRun:
    _require_entry(scenario_id)  # raises UnknownScenarioError before creating any row
    run = ScenarioRun(
        scenario_id=scenario_id,
        run_number=_next_run_number(db, scenario_id),
        status=STATUS_RUNNING,
        correlation_id=uuid.uuid4(),
        diagnostics={},
        resources={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    thread = threading.Thread(
        target=_execute, args=(session_factory, scenario_id, run.id), daemon=True
    )
    thread.start()
    return run


def reset(db: Session, scenario_id: str) -> ScenarioReset:
    entry = _require_entry(scenario_id)
    settings = get_settings()
    ctx = _build_context(settings, db, correlation_id=str(uuid.uuid4()))
    summary = entry.reset(ctx)
    row = ScenarioReset(scenario_id=scenario_id, summary=summary)
    db.add(row)
    db.commit()
    db.refresh(row)
    FAILURE_LAB_SCENARIO_RESETS_TOTAL.labels(scenario_id).inc()
    return row


def latest_run(db: Session, scenario_id: str) -> ScenarioRun | None:
    return db.execute(
        select(ScenarioRun)
        .where(ScenarioRun.scenario_id == scenario_id)
        .order_by(ScenarioRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_reset(db: Session, scenario_id: str) -> ScenarioReset | None:
    return db.execute(
        select(ScenarioReset)
        .where(ScenarioReset.scenario_id == scenario_id)
        .order_by(ScenarioReset.reset_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def run_count(db: Session, scenario_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(ScenarioRun).where(ScenarioRun.scenario_id == scenario_id)
    ).scalar_one()


def run_history(db: Session, scenario_id: str, limit: int = 20) -> list[ScenarioRun]:
    return list(
        db.execute(
            select(ScenarioRun)
            .where(ScenarioRun.scenario_id == scenario_id)
            .order_by(ScenarioRun.started_at.desc())
            .limit(limit)
        ).scalars()
    )
