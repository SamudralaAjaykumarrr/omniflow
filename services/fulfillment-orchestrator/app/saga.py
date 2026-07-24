"""The saga engine: `order.validated` triggers a durable, resumable workflow
driving node selection, inventory reservation, simulated payment, and
compensation on failure. See docs/adrs/0004-custom-saga-orchestrator.md and
docs/adrs/0010-node-scoring-and-saga-orchestration.md.

Each step function reads/writes `saga.context` (a JSON scratchpad) and
commits before returning — that is what makes `advance_saga` resumable
after a crash: `resume_incomplete_sagas` (app.consumer) calls it again for
every row still `status == RUNNING`, picking up at `current_step` rather
than restarting the saga from scratch. A narrow resume gap is documented in
RISKS.md: if the process crashes strictly between a successful remote
reservation and this step's local commit, the orchestrator has no local
record of that reservation and fails the saga loudly rather than silently
double-reserving or guessing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import (
    InventoryConflictError,
    InventoryServiceClient,
    OrderServiceClient,
)
from app.config import get_settings
from app.metrics import SAGA_DURATION_SECONDS
from app.models import ProcessedEvent, SagaInstance
from app.outbox import stage_event
from app.payment import PaymentDeclinedError, PaymentGatewayTimeoutError, authorize_payment
from app.retry import RetryExhaustedError, retry_with_backoff
from app.scoring import NodeCandidate, score_candidates
from event_contracts import EventEnvelope, EventType

logger = logging.getLogger("fulfillment_orchestrator.saga")

CONSUMER_NAME = "fulfillment-orchestrator"

STEP_FETCH_ORDER = "FETCH_ORDER"
STEP_SELECT_AND_RESERVE = "SELECT_AND_RESERVE"
STEP_ASSIGN_FULFILLMENT = "ASSIGN_FULFILLMENT"
STEP_AUTHORIZE_PAYMENT = "AUTHORIZE_PAYMENT"
STEP_CONFIRM_SHIPMENT = "CONFIRM_SHIPMENT"
STEP_COMPENSATE_RELEASE_INVENTORY = "COMPENSATE_RELEASE_INVENTORY"
STEP_FAIL_NO_INVENTORY = "FAIL_NO_INVENTORY"
STEP_DONE = "DONE"

STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

_MAX_STEPS_PER_ADVANCE = 20  # safety bound against an accidental infinite loop


def _already_processed(db: Session, event_id: str) -> bool:
    return db.get(ProcessedEvent, (CONSUMER_NAME, uuid.UUID(event_id))) is not None


def _mark_processed(db: Session, event_id: str) -> None:
    db.add(ProcessedEvent(consumer_name=CONSUMER_NAME, event_id=uuid.UUID(event_id)))


def _find_saga(db: Session, order_id: uuid.UUID) -> SagaInstance | None:
    return db.execute(
        select(SagaInstance).where(SagaInstance.order_id == order_id)
    ).scalar_one_or_none()


def _step_fetch_order(db: Session, order_client: OrderServiceClient, saga: SagaInstance) -> None:
    order = order_client.get_order(str(saga.order_id))
    saga.context["customer_id"] = order.customer_id
    saga.context["order_total"] = order.order_total
    saga.context["items"] = order.items
    saga.current_step = STEP_SELECT_AND_RESERVE
    db.commit()


def _step_select_and_reserve(
    db: Session,
    order_client: OrderServiceClient,
    inventory_client: InventoryServiceClient,
    saga: SagaInstance,
) -> None:
    order_id = str(saga.order_id)
    items = saga.context["items"]
    skus_qty = [{"sku": i["sku"], "qty": i["qty"]} for i in items]

    current = order_client.get_order(order_id)

    if current.status == "CANCELLED":
        saga.status = STATUS_FAILED
        saga.current_step = STEP_DONE
        saga.last_error = "order cancelled before reservation"
        db.commit()
        return

    if current.status == "VALIDATED":
        current = order_client.transition(
            order_id,
            "INVENTORY_PENDING",
            current.version,
            "orchestrator: requesting inventory reservation",
        )
    elif current.status != "INVENTORY_PENDING":
        # Resuming after a crash that happened after a reservation succeeded
        # remotely but before this step's local commit — there is no local
        # record of which node/reservations that was. Documented limitation
        # (RISKS.md): fail loud rather than silently double-reserving.
        saga.status = STATUS_FAILED
        saga.current_step = STEP_DONE
        saga.last_error = (
            f"cannot safely resume SELECT_AND_RESERVE: order already at "
            f"{current.status} with no reservation recorded in saga context"
        )
        db.commit()
        return

    nodes = inventory_client.list_nodes()
    candidates = []
    for node in nodes:
        if not node["active"]:
            continue
        check = inventory_client.check_stock(node["id"], skus_qty)
        if check["sufficient"]:
            candidates.append(
                NodeCandidate(
                    node_id=node["id"],
                    latitude=node["latitude"],
                    longitude=node["longitude"],
                    capacity_per_day=node["capacity_per_day"],
                    current_backlog=node["current_backlog"],
                )
            )

    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=saga.order_id,
        event_type=EventType.INVENTORY_RESERVATION_REQUESTED,
        correlation_id=saga.correlation_id,
        causation_id=None,
        data={
            "order_id": order_id,
            "items": skus_qty,
            "candidate_node_ids": [c.node_id for c in candidates],
        },
    )
    db.commit()

    if not candidates:
        saga.current_step = STEP_FAIL_NO_INVENTORY
        db.commit()
        return

    ranked = score_candidates(saga.context["customer_id"], candidates)

    for candidate_score in ranked:
        reserved_ids: list[str] = []
        try:
            for item in items:
                handle = inventory_client.reserve(
                    order_id=order_id,
                    sku=item["sku"],
                    node_id=candidate_score.node_id,
                    qty=item["qty"],
                    correlation_id=str(saga.correlation_id),
                )
                reserved_ids.append(handle.id)
        except InventoryConflictError:
            for reservation_id in reserved_ids:
                try:
                    inventory_client.release(
                        reservation_id,
                        reason="rolling back partial reservation at rejected node",
                    )
                except InventoryConflictError:
                    logger.warning(
                        "failed to roll back reservation %s during node fallback", reservation_id
                    )
            continue  # try the next candidate node

        saga.context["node_id"] = candidate_score.node_id
        saga.context["reservation_ids"] = reserved_ids
        saga.context["score"] = candidate_score.score
        saga.context["score_breakdown"] = candidate_score.breakdown
        saga.context["estimated_ship_date_days"] = candidate_score.estimated_ship_date_days
        saga.current_step = STEP_ASSIGN_FULFILLMENT
        db.commit()
        return

    # every candidate rejected the reservation at attempt time
    saga.current_step = STEP_FAIL_NO_INVENTORY
    db.commit()


def _step_assign_fulfillment(
    db: Session, order_client: OrderServiceClient, saga: SagaInstance
) -> None:
    order_id = str(saga.order_id)
    current = order_client.get_order(order_id)
    if current.status == "INVENTORY_PENDING":
        current = order_client.transition(
            order_id, "INVENTORY_RESERVED", current.version, "orchestrator: inventory reserved"
        )
    if current.status == "INVENTORY_RESERVED":
        order_client.transition(
            order_id,
            "FULFILLMENT_ASSIGNED",
            current.version,
            f"orchestrator: assigned node (score={saga.context['score']})",
            node_id=saga.context["node_id"],
        )

    estimated_ship_date = datetime.now(UTC) + timedelta(
        days=saga.context["estimated_ship_date_days"]
    )
    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=saga.order_id,
        event_type=EventType.FULFILLMENT_ASSIGNED,
        correlation_id=saga.correlation_id,
        causation_id=None,
        data={
            "order_id": order_id,
            "node_id": saga.context["node_id"],
            "score": saga.context["score"],
            "score_breakdown": saga.context["score_breakdown"],
            "estimated_ship_date": estimated_ship_date.isoformat(),
        },
    )
    saga.current_step = STEP_AUTHORIZE_PAYMENT
    db.commit()


def _step_authorize_payment(
    db: Session, order_client: OrderServiceClient, saga: SagaInstance
) -> None:
    order_id = str(saga.order_id)
    current = order_client.get_order(order_id)
    if current.status == "FULFILLMENT_ASSIGNED":
        order_client.transition(
            order_id, "PROCESSING", current.version, "orchestrator: authorizing payment"
        )

    skus = [i["sku"] for i in saga.context["items"]]
    settings = get_settings()
    try:
        auth = retry_with_backoff(
            lambda attempt: authorize_payment(order_id, saga.context["order_total"], skus, attempt),
            retryable=(PaymentGatewayTimeoutError,),
            max_attempts=settings.payment_max_attempts,
            base_delay=settings.payment_retry_base_delay_seconds,
            max_delay=settings.payment_retry_max_delay_seconds,
        )
    except PaymentDeclinedError as exc:
        saga.context["failure_reason"] = str(exc)
        saga.context["failed_step"] = STEP_AUTHORIZE_PAYMENT
        saga.current_step = STEP_COMPENSATE_RELEASE_INVENTORY
        db.commit()
        return
    except RetryExhaustedError as exc:
        saga.context["failure_reason"] = str(exc.last_error)
        saga.context["failed_step"] = STEP_AUTHORIZE_PAYMENT
        saga.current_step = STEP_COMPENSATE_RELEASE_INVENTORY
        db.commit()
        return

    saga.context["authorization_id"] = auth.authorization_id
    saga.current_step = STEP_CONFIRM_SHIPMENT
    db.commit()


def _step_confirm_shipment(
    db: Session, order_client: OrderServiceClient, saga: SagaInstance
) -> None:
    order_id = str(saga.order_id)
    current = order_client.get_order(order_id)
    if current.status == "PROCESSING":
        order_client.transition(
            order_id,
            "SHIPPED",
            current.version,
            "orchestrator: payment authorized, shipment confirmed",
        )

    now = datetime.now(UTC)
    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=saga.order_id,
        event_type=EventType.ORDER_SHIPPED,
        correlation_id=saga.correlation_id,
        causation_id=None,
        data={
            "order_id": order_id,
            "node_id": saga.context["node_id"],
            "shipped_at": now.isoformat(),
            "carrier_sim": "sim-ground",
            "tracking_ref": f"TRACK-{saga.order_id}",
        },
    )
    saga.status = STATUS_COMPLETED
    saga.current_step = STEP_DONE
    db.commit()


def _step_compensate_release_inventory(
    db: Session,
    order_client: OrderServiceClient,
    inventory_client: InventoryServiceClient,
    saga: SagaInstance,
) -> None:
    order_id = str(saga.order_id)
    reservation_ids = saga.context.get("reservation_ids", [])
    for reservation_id in reservation_ids:
        try:
            inventory_client.release(
                reservation_id,
                reason="saga compensation: " + saga.context.get("failure_reason", "unknown"),
            )
        except InventoryConflictError:
            logger.warning(
                "compensation release failed for reservation %s (already released?)",
                reservation_id,
            )

    current = order_client.get_order(order_id)
    if current.status not in ("FAILED", "CANCELLED"):
        reason = saga.context.get("failure_reason", "payment failed")
        order_client.transition(order_id, "FAILED", current.version, reason)

    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=saga.order_id,
        event_type=EventType.ORDER_FAILED,
        correlation_id=saga.correlation_id,
        causation_id=None,
        data={
            "order_id": order_id,
            "failed_step": saga.context.get("failed_step", STEP_AUTHORIZE_PAYMENT),
            "reason": saga.context.get("failure_reason", "unknown"),
            "compensations_applied": ["inventory_release"] if reservation_ids else [],
        },
    )
    saga.status = STATUS_FAILED
    saga.current_step = STEP_DONE
    db.commit()


def _step_fail_no_inventory(
    db: Session, order_client: OrderServiceClient, saga: SagaInstance
) -> None:
    order_id = str(saga.order_id)
    current = order_client.get_order(order_id)
    if current.status not in ("FAILED", "CANCELLED"):
        order_client.transition(
            order_id,
            "FAILED",
            current.version,
            "orchestrator: no fulfillment node has sufficient stock",
        )

    stage_event(
        db,
        aggregate_type="order",
        aggregate_id=saga.order_id,
        event_type=EventType.ORDER_FAILED,
        correlation_id=saga.correlation_id,
        causation_id=None,
        data={
            "order_id": order_id,
            "failed_step": STEP_SELECT_AND_RESERVE,
            "reason": "no fulfillment node has sufficient stock",
            "compensations_applied": [],
        },
    )
    saga.status = STATUS_FAILED
    saga.current_step = STEP_DONE
    db.commit()


_STEP_HANDLERS = {
    STEP_FETCH_ORDER: lambda db, oc, ic, saga: _step_fetch_order(db, oc, saga),
    STEP_SELECT_AND_RESERVE: lambda db, oc, ic, saga: _step_select_and_reserve(db, oc, ic, saga),
    STEP_ASSIGN_FULFILLMENT: lambda db, oc, ic, saga: _step_assign_fulfillment(db, oc, saga),
    STEP_AUTHORIZE_PAYMENT: lambda db, oc, ic, saga: _step_authorize_payment(db, oc, saga),
    STEP_CONFIRM_SHIPMENT: lambda db, oc, ic, saga: _step_confirm_shipment(db, oc, saga),
    STEP_COMPENSATE_RELEASE_INVENTORY: (
        lambda db, oc, ic, saga: _step_compensate_release_inventory(db, oc, ic, saga)
    ),
    STEP_FAIL_NO_INVENTORY: lambda db, oc, ic, saga: _step_fail_no_inventory(db, oc, saga),
}


def _observe_saga_duration(saga: SagaInstance) -> None:
    now = datetime.now(UTC)
    created_at = saga.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    result = "completed" if saga.status == STATUS_COMPLETED else "failed"
    SAGA_DURATION_SECONDS.labels(result).observe((now - created_at).total_seconds())


def advance_saga(
    db: Session,
    order_client: OrderServiceClient,
    inventory_client: InventoryServiceClient,
    saga: SagaInstance,
) -> None:
    for _ in range(_MAX_STEPS_PER_ADVANCE):
        if saga.status != STATUS_RUNNING:
            return
        handler = _STEP_HANDLERS[saga.current_step]
        handler(db, order_client, inventory_client, saga)
        if saga.status != STATUS_RUNNING:
            _observe_saga_duration(saga)
            return
    logger.error(
        "saga %s did not reach a terminal state within %s steps",
        saga.id,
        _MAX_STEPS_PER_ADVANCE,
    )


def handle_order_validated(
    db: Session,
    order_client: OrderServiceClient,
    inventory_client: InventoryServiceClient,
    envelope: EventEnvelope,
) -> None:
    if envelope.event_type != EventType.ORDER_VALIDATED:
        return
    if _already_processed(db, envelope.event_id):
        return

    order_id = uuid.UUID(envelope.data["order_id"])
    existing = _find_saga(db, order_id)
    if existing is not None:
        # A saga already exists for this order — e.g. order.validated was
        # redelivered. Record this event as seen; if the existing saga
        # never reached a terminal state for some other reason, let it
        # continue from wherever it is.
        _mark_processed(db, envelope.event_id)
        db.commit()
        if existing.status == STATUS_RUNNING:
            advance_saga(db, order_client, inventory_client, existing)
        return

    saga = SagaInstance(
        order_id=order_id,
        correlation_id=uuid.UUID(envelope.correlation_id),
        current_step=STEP_FETCH_ORDER,
        status=STATUS_RUNNING,
        context={},
    )
    db.add(saga)
    _mark_processed(db, envelope.event_id)
    db.commit()

    advance_saga(db, order_client, inventory_client, saga)


def handle_order_cancelled(
    db: Session, inventory_client: InventoryServiceClient, envelope: EventEnvelope
) -> None:
    if envelope.event_type != EventType.ORDER_CANCELLED:
        return
    if _already_processed(db, envelope.event_id):
        return

    order_id = uuid.UUID(envelope.data["order_id"])
    saga = _find_saga(db, order_id)
    if saga is not None and saga.status == STATUS_RUNNING:
        for reservation_id in saga.context.get("reservation_ids", []):
            try:
                inventory_client.release(reservation_id, reason="order cancelled by customer")
            except InventoryConflictError:
                logger.warning(
                    "cancellation compensation release failed for reservation %s", reservation_id
                )
        saga.status = STATUS_FAILED
        saga.current_step = STEP_DONE
        saga.last_error = "order cancelled while saga was running"

    _mark_processed(db, envelope.event_id)
    db.commit()


def resume_incomplete_sagas(
    db: Session, order_client: OrderServiceClient, inventory_client: InventoryServiceClient
) -> int:
    """Called once at consumer startup — resumes any saga left `RUNNING` by
    a previous process that crashed mid-saga."""
    running = (
        db.execute(select(SagaInstance).where(SagaInstance.status == STATUS_RUNNING))
        .scalars()
        .all()
    )
    for saga in running:
        advance_saga(db, order_client, inventory_client, saga)
    return len(running)
