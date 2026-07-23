import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import OutboxEvent
from event_contracts import EventEnvelope

PRODUCER_NAME = "inventory-service"


def stage_event(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID | None,
    data: dict[str, Any],
) -> OutboxEvent:
    envelope = EventEnvelope(
        event_type=event_type,
        producer=PRODUCER_NAME,
        correlation_id=str(correlation_id),
        causation_id=str(causation_id) if causation_id else None,
        data=data,
    )
    row = OutboxEvent(
        id=uuid.UUID(envelope.event_id),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=envelope.model_dump(mode="json"),
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    db.add(row)
    return row
