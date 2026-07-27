"""Shared scenario contract + helpers. Each of the 10 scenarios in
app/scenarios/ implements `Scenario`: static catalog metadata (id, name,
description, ...) plus `run`/`reset`.

`run` always returns a `ScenarioOutcome` — it never raises for an expected,
in-scenario failure (a decline, a rejected reservation, a dead letter). An
*unexpected* problem (a service unreachable, a timeout waiting for an async
effect) is also caught by the runner (app.runner) and turned into an ERROR
outcome, never an unhandled 500 — see app.runner.execute.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.clients import (
    GatewayClient,
    InventoryServiceClient,
    OrchestratorClient,
    OrderServiceClient,
)
from app.config import Settings


@dataclass
class ScenarioContext:
    settings: Settings
    gateway: GatewayClient
    order_service: OrderServiceClient
    inventory: InventoryServiceClient
    orchestrator: OrchestratorClient
    correlation_id: str
    db: Session
    # Builds a confluent_kafka.Producer (real, against settings.
    # kafka_bootstrap_servers) — injected rather than imported directly by
    # the 4 scenarios that publish onto Kafka, so their unit tests can pass
    # a fake producer instead of needing a live broker. See tests/fakes.py's
    # FakeKafkaProducer and app.runner._build_context for the real default.
    producer_factory: Callable[[], Any]


@dataclass
class ScenarioOutcome:
    status: str
    summary: str
    diagnostics: dict = field(default_factory=dict)
    resources: dict = field(default_factory=dict)


class PollTimeoutError(Exception):
    """A scenario's expected async effect (saga terminal state, a DLQ row
    appearing, ...) never showed up within the configured poll budget."""


T = TypeVar("T")


def poll_until(
    fn: Callable[[], T | None],
    *,
    timeout_seconds: float,
    interval_seconds: float,
    description: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call `fn()` every `interval_seconds` until it returns a truthy value
    or `timeout_seconds` elapses. Bounded, deterministic in outcome (the
    system either reaches the expected state or it doesn't) even though the
    wait itself is real wall-clock time — there is no randomness in whether
    a given run passes, only in how many polls it took."""
    deadline = clock() + timeout_seconds
    while True:
        result = fn()
        if result:
            return result
        if clock() >= deadline:
            raise PollTimeoutError(f"timed out waiting for: {description}")
        sleep(interval_seconds)


@dataclass
class ScenarioEntry:
    """A scenario module's metadata plus its `run`/`reset` callables,
    collected explicitly by app.scenarios.registry — simpler and more
    mypy-friendly than treating a module object as a structural Protocol
    instance."""

    id: str
    name: str
    description: str
    category: str
    mechanism_reference: str
    expected_failure_behavior: str
    expected_recovery_behavior: str
    run: Callable[[ScenarioContext], ScenarioOutcome]
    reset: Callable[[ScenarioContext], str]
    safe_to_rerun: bool = True
