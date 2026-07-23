import uuid
from datetime import datetime

from pydantic import BaseModel


class SagaInstanceResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    correlation_id: uuid.UUID
    current_step: str
    status: str
    attempt_count: int
    last_error: str | None
    context: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeadLetterEventResponse(BaseModel):
    id: uuid.UUID
    original_event_id: uuid.UUID
    event_type: str
    failed_consumer: str
    error_type: str
    error_message: str
    attempt_count: int
    payload: dict
    first_failed_at: datetime
    last_failed_at: datetime
    replayed_at: datetime | None

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None
