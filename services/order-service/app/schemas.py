import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrderItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class CreateOrderRequest(BaseModel):
    customer_id: uuid.UUID
    customer_email: str
    customer_display_name: str
    items: list[OrderItemIn] = Field(min_length=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: list[OrderItemIn]) -> list[OrderItemIn]:
        if not v:
            raise ValueError("order must contain at least one item")
        return v


class OrderItemOut(BaseModel):
    sku: str
    qty: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    status: str
    version: int
    correlation_id: uuid.UUID
    assigned_node_id: uuid.UUID | None
    order_total: float
    currency: str
    items: list[OrderItemOut]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderStatusHistoryOut(BaseModel):
    from_status: str | None
    to_status: str
    reason: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class CancelOrderRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(gt=0)


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None
