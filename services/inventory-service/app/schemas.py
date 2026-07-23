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


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None
