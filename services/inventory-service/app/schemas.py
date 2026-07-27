import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReserveRequest(BaseModel):
    order_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    node_id: uuid.UUID
    qty: int = Field(gt=0)
    correlation_id: uuid.UUID


class ReservationResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    sku: str
    node_id: uuid.UUID
    qty: int
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ReleaseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class StockResponse(BaseModel):
    sku: str
    node_id: uuid.UUID
    available_qty: int
    reserved_qty: int
    committed_qty: int
    reorder_threshold: int
    version: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class SeedStockRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    node_id: uuid.UUID
    available_qty: int = Field(ge=0)
    reorder_threshold: int = Field(ge=0, default=10)


class CreateNodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    latitude: float
    longitude: float
    capacity_per_day: int = Field(gt=0)


class NodeResponse(BaseModel):
    id: uuid.UUID
    name: str
    latitude: float
    longitude: float
    capacity_per_day: int
    current_backlog: int
    active: bool

    model_config = {"from_attributes": True}


class StockCheckItem(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0)


class StockCheckRequest(BaseModel):
    node_id: uuid.UUID
    items: list[StockCheckItem] = Field(min_length=1)


class StockCheckShortfall(BaseModel):
    sku: str
    requested_qty: int
    available_qty: int


class StockCheckResponse(BaseModel):
    node_id: uuid.UUID
    sufficient: bool
    shortfalls: list[StockCheckShortfall]


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None


class EnableOutageRequest(BaseModel):
    """Phase 8 (failure lab) downstream-outage scenario input. `float`
    (not `int`) so tests can request sub-second durations without waiting
    a full second for the self-clear to prove itself."""

    duration_seconds: float = Field(gt=0, le=300, default=20.0)


class OutageStatus(BaseModel):
    active: bool
    until: datetime | None
