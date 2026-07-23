"""Common event envelope shared by every OmniFlow domain event.

See docs/event-catalog.md for the authoritative contract this mirrors.
Delivery is at-least-once; consumers must dedupe on `event_id`, not assume
exactly-once semantics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def new_event_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class TraceContext(BaseModel):
    traceparent: str | None = None


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=new_event_id)
    event_type: str
    schema_version: str = "1.0.0"
    occurred_at: datetime = Field(default_factory=utc_now)
    producer: str
    correlation_id: str
    causation_id: str | None = None
    trace_context: TraceContext = Field(default_factory=TraceContext)
    data: dict[str, Any]
