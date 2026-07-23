import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import ConcurrentUpdateError, IdempotencyKeyConflictError, OrderNotFoundError
from app.models import Customer, IdempotencyKey, Order, OrderItem, OrderStatusHistory
from app.outbox import stage_event
from app.schemas import CancelOrderRequest, CreateOrderRequest, OrderResponse
from app.state_machine import CANCELLABLE_STATES, OrderStatus, assert_valid_transition
from event_contracts import EventType


def hash_request(request: CreateOrderRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_order(
    db: Session, request: CreateOrderRequest, idempotency_key: str
) -> tuple[OrderResponse, int, bool]:
    """Create an order, honoring the idempotency key.

    Returns (response, http_status, was_cached). Raises IdempotencyKeyConflictError
    if the same key was used before with a different request payload.
    """
    request_hash = hash_request(request)

    existing = db.get(IdempotencyKey, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyKeyConflictError(idempotency_key)
        return OrderResponse.model_validate(existing.response_body), existing.response_status, True

    customer = db.get(Customer, request.customer_id)
    if customer is None:
        customer = Customer(
            id=request.customer_id,
            email=request.customer_email,
            display_name=request.customer_display_name,
        )
        db.add(customer)

    order_total = sum(item.qty * item.unit_price for item in request.items)
    correlation_id = uuid.uuid4()
    order = Order(
        customer_id=request.customer_id,
        status=OrderStatus.CREATED.value,
        version=1,
        correlation_id=correlation_id,
        order_total=order_total,
        currency=request.currency,
    )
    order.items = [
        OrderItem(sku=item.sku, qty=item.qty, unit_price=item.unit_price) for item in request.items
    ]
    db.add(order)
    db.flush()  # assign order.id, order.created_at before building the response/event

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=None,
            to_status=OrderStatus.CREATED.value,
            reason="order created",
        )
    )

    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=order.id,
        event_type=EventType.ORDER_CREATED,
        correlation_id=correlation_id,
        causation_id=None,
        data={
            "order_id": str(order.id),
            "customer_id": str(order.customer_id),
            "items": [item.model_dump(mode="json") for item in request.items],
            "order_total": float(order_total),
            "currency": order.currency,
            "idempotency_key": idempotency_key,
        },
    )

    response = OrderResponse.model_validate(order)
    settings = get_settings()
    db.add(
        IdempotencyKey(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_body=json.loads(response.model_dump_json()),
            response_status=201,
            order_id=order.id,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.idempotency_key_ttl_hours),
        )
    )

    db.commit()
    db.refresh(order)
    return OrderResponse.model_validate(order), 201, False


def get_order(db: Session, order_id: uuid.UUID) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(str(order_id))
    return order


def cancel_order(db: Session, order_id: uuid.UUID, request: CancelOrderRequest) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(str(order_id))

    current_status = OrderStatus(order.status)
    if current_status not in CANCELLABLE_STATES:
        assert_valid_transition(current_status, OrderStatus.CANCELLED)

    result = db.execute(
        update(Order)
        .where(Order.id == order_id, Order.version == request.expected_version)
        .values(status=OrderStatus.CANCELLED.value, version=Order.version + 1)
    )
    if result.rowcount == 0:
        db.rollback()
        raise ConcurrentUpdateError(str(order_id), request.expected_version)

    db.add(
        OrderStatusHistory(
            order_id=order_id,
            from_status=current_status.value,
            to_status=OrderStatus.CANCELLED.value,
            reason=request.reason,
        )
    )
    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=order_id,
        event_type=EventType.ORDER_CANCELLED,
        correlation_id=order.correlation_id,
        causation_id=None,
        data={
            "order_id": str(order_id),
            "cancelled_by": "api",
            "reason": request.reason,
            "previous_state": current_status.value,
        },
    )
    db.commit()
    db.refresh(order)
    return order


def list_status_history(db: Session, order_id: uuid.UUID) -> list[OrderStatusHistory]:
    stmt = (
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.changed_at)
    )
    return list(db.scalars(stmt))
