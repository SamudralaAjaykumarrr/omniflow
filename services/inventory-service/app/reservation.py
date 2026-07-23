"""Inventory reservation — the row-level-locking critical section.

See docs/adrs/0002-inventory-concurrency-control.md. The `SELECT ... FOR
UPDATE` below is what serializes concurrent reservation attempts against the
same (sku, node_id) row: the second concurrent transaction blocks on the lock
until the first commits, then sees the already-decremented quantity and is
correctly rejected if stock is now insufficient. No optimistic retry loop is
needed here — the lock IS the concurrency control for this table.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import (
    InsufficientStockError,
    ReservationNotActiveError,
    ReservationNotFoundError,
    UnknownStockError,
)
from app.models import InventoryReservation, InventoryStock, ReservationStatus
from app.outbox import stage_event
from app.schemas import ReserveRequest
from event_contracts import EventType


def reserve_stock(db: Session, request: ReserveRequest) -> InventoryReservation:
    stmt = (
        select(InventoryStock)
        .where(InventoryStock.sku == request.sku, InventoryStock.node_id == request.node_id)
        .with_for_update()
    )
    stock = db.execute(stmt).scalar_one_or_none()
    if stock is None:
        db.rollback()
        raise UnknownStockError(request.sku, str(request.node_id))

    if stock.available_qty < request.qty:
        stage_event(
            db,
            aggregate_type="inventory_stock",
            aggregate_id=request.node_id,
            event_type=EventType.INVENTORY_REJECTED,
            correlation_id=request.correlation_id,
            causation_id=None,
            data={
                "order_id": str(request.order_id),
                "reasons": [
                    {
                        "sku": request.sku,
                        "requested_qty": request.qty,
                        "available_qty": stock.available_qty,
                    }
                ],
            },
        )
        db.commit()
        raise InsufficientStockError(
            request.sku, str(request.node_id), request.qty, stock.available_qty
        )

    stock.available_qty -= request.qty
    stock.reserved_qty += request.qty
    stock.version += 1

    settings = get_settings()
    reservation = InventoryReservation(
        order_id=request.order_id,
        sku=request.sku,
        node_id=request.node_id,
        qty=request.qty,
        status=ReservationStatus.ACTIVE.value,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.reservation_ttl_minutes),
    )
    db.add(reservation)
    db.flush()

    stage_event(
        db,
        aggregate_type="inventory_reservation",
        aggregate_id=reservation.id,
        event_type=EventType.INVENTORY_RESERVED,
        correlation_id=request.correlation_id,
        causation_id=None,
        data={
            "order_id": str(request.order_id),
            "reservations": [
                {
                    "sku": request.sku,
                    "node_id": str(request.node_id),
                    "qty": request.qty,
                    "reservation_id": str(reservation.id),
                    "expires_at": reservation.expires_at.isoformat(),
                }
            ],
        },
    )

    if stock.available_qty <= stock.reorder_threshold:
        stage_event(
            db,
            aggregate_type="inventory_stock",
            aggregate_id=request.node_id,
            event_type=EventType.INVENTORY_LOW,
            correlation_id=request.correlation_id,
            causation_id=None,
            data={
                "sku": request.sku,
                "node_id": str(request.node_id),
                "available_qty": stock.available_qty,
                "threshold": stock.reorder_threshold,
            },
        )

    db.commit()
    db.refresh(reservation)
    return reservation


def release_reservation(
    db: Session, reservation_id: uuid.UUID, reason: str
) -> InventoryReservation:
    reservation = db.get(InventoryReservation, reservation_id)
    if reservation is None:
        raise ReservationNotFoundError(str(reservation_id))
    if reservation.status != ReservationStatus.ACTIVE.value:
        raise ReservationNotActiveError(str(reservation_id), reservation.status)

    stmt = (
        select(InventoryStock)
        .where(InventoryStock.sku == reservation.sku, InventoryStock.node_id == reservation.node_id)
        .with_for_update()
    )
    stock = db.execute(stmt).scalar_one()
    stock.available_qty += reservation.qty
    stock.reserved_qty -= reservation.qty
    stock.version += 1

    reservation.status = ReservationStatus.RELEASED.value

    db.commit()
    db.refresh(reservation)
    return reservation


def expire_stale_reservations(db: Session) -> list[InventoryReservation]:
    """Release every ACTIVE reservation whose TTL has passed.

    Run periodically (Phase 2 will wire this to a scheduled worker); exposed
    here as a plain function + admin endpoint so it is independently testable
    and triggerable on demand for the failure-lab / demo.
    """
    now = datetime.now(UTC)
    stale = (
        db.execute(
            select(InventoryReservation).where(
                InventoryReservation.status == ReservationStatus.ACTIVE.value,
                InventoryReservation.expires_at < now,
            )
        )
        .scalars()
        .all()
    )

    released: list[InventoryReservation] = []
    for reservation in stale:
        stmt = (
            select(InventoryStock)
            .where(
                InventoryStock.sku == reservation.sku,
                InventoryStock.node_id == reservation.node_id,
            )
            .with_for_update()
        )
        stock = db.execute(stmt).scalar_one()
        stock.available_qty += reservation.qty
        stock.reserved_qty -= reservation.qty
        stock.version += 1
        reservation.status = ReservationStatus.EXPIRED.value
        released.append(reservation)

    db.commit()
    for reservation in released:
        db.refresh(reservation)
    return released
