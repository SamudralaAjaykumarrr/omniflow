import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.exceptions import ConcurrentUpdateError, IdempotencyKeyConflictError, OrderNotFoundError
from app.models import ProcessedEvent
from app.schemas import (
    CancelOrderRequest,
    CreateOrderRequest,
    OrderResponse,
    OrderStatusHistoryOut,
    ProcessedEventStatus,
    TransitionOrderRequest,
)
from app.service import (
    cancel_order,
    create_order,
    get_order,
    list_status_history,
    transition_order_status,
)
from app.state_machine import InvalidTransitionError

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/orders", response_model=OrderResponse, status_code=201)
def post_order(
    request: CreateOrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    try:
        response, status_code, _was_cached = create_order(db, request, idempotency_key)
    except IdempotencyKeyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_route(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        order = get_order(db, order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OrderResponse.model_validate(order)


@router.get("/orders/{order_id}/history", response_model=list[OrderStatusHistoryOut])
def get_order_history_route(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        get_order(db, order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [OrderStatusHistoryOut.model_validate(h) for h in list_status_history(db, order_id)]


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order_route(
    order_id: uuid.UUID, request: CancelOrderRequest, db: Session = Depends(get_db)
):
    try:
        order = cancel_order(db, order_id, request)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrderResponse.model_validate(order)


@router.post("/orders/{order_id}/transition", response_model=OrderResponse)
def transition_order_route(
    order_id: uuid.UUID, request: TransitionOrderRequest, db: Session = Depends(get_db)
):
    """Internal endpoint for the Fulfillment Orchestrator — not proxied by
    the API Gateway to customers."""
    try:
        order = transition_order_status(db, order_id, request)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConcurrentUpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OrderResponse.model_validate(order)


@router.get(
    "/internal/failure-lab/processed-events/{event_id}",
    response_model=ProcessedEventStatus,
)
def processed_event_status_route(
    event_id: uuid.UUID,
    consumer_name: str = "order-service-validator",
    db: Session = Depends(get_db),
):
    """Read-only introspection into the idempotent-consumer ledger
    (`processed_events`), added for Phase 8's duplicate-event-delivery
    scenario: it needs to observe that a redelivered event_id was a true
    no-op (processed_at unchanged), not just infer it from the order's
    unaffected state. Internal/diagnostic only — not proxied by the API
    Gateway to customers, same convention as /orders/{id}/transition."""
    row = db.get(ProcessedEvent, (consumer_name, event_id))
    if row is None:
        return ProcessedEventStatus(
            event_id=event_id, consumer_name=consumer_name, processed=False, processed_at=None
        )
    return ProcessedEventStatus(
        event_id=event_id,
        consumer_name=consumer_name,
        processed=True,
        processed_at=row.processed_at,
    )
