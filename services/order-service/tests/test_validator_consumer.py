import uuid

from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.models import Customer, Order, OrderItem, OutboxEvent, ProcessedEvent
from app.state_machine import OrderStatus
from app.validator_consumer import process_order_created
from event_contracts import EventEnvelope, EventType


def _seed_order(db_session, status: str = OrderStatus.CREATED.value) -> Order:
    customer = Customer(id=uuid.uuid4(), email="x@example.com", display_name="X")
    db_session.add(customer)
    order = Order(
        customer_id=customer.id,
        status=status,
        version=1,
        correlation_id=uuid.uuid4(),
        order_total=10.0,
        currency="USD",
    )
    order.items = [OrderItem(sku="SKU-1", qty=1, unit_price=10.0)]
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def _created_envelope(order_id: uuid.UUID) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": str(order_id)},
    )


def test_validates_a_created_order_and_stages_order_validated(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    order = _seed_order(db_session)
    envelope = _created_envelope(order.id)

    process_order_created(session_factory, envelope)

    db_session.expire_all()
    refreshed = db_session.get(Order, order.id)
    assert refreshed.status == OrderStatus.VALIDATED.value
    assert refreshed.version == 2

    outbox_rows = (
        db_session.query(OutboxEvent).filter_by(event_type=EventType.ORDER_VALIDATED).all()
    )
    assert len(outbox_rows) == 1
    assert outbox_rows[0].causation_id == uuid.UUID(envelope.event_id)


def test_redelivery_of_the_same_event_is_a_no_op(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    order = _seed_order(db_session)
    envelope = _created_envelope(order.id)

    process_order_created(session_factory, envelope)
    process_order_created(session_factory, envelope)  # redelivered

    db_session.expire_all()
    refreshed = db_session.get(Order, order.id)
    assert refreshed.version == 2  # only advanced once

    outbox_rows = (
        db_session.query(OutboxEvent).filter_by(event_type=EventType.ORDER_VALIDATED).all()
    )
    assert len(outbox_rows) == 1  # not duplicated

    processed_rows = db_session.query(ProcessedEvent).all()
    assert len(processed_rows) == 1


def test_order_already_moved_on_is_a_no_op_not_an_error(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    order = _seed_order(db_session, status=OrderStatus.CANCELLED.value)
    envelope = _created_envelope(order.id)

    process_order_created(session_factory, envelope)  # must not raise

    db_session.expire_all()
    refreshed = db_session.get(Order, order.id)
    assert refreshed.status == OrderStatus.CANCELLED.value  # untouched

    processed_rows = db_session.query(ProcessedEvent).all()
    assert len(processed_rows) == 1  # still marked seen


def test_unrelated_event_type_is_ignored(db_session):
    session_factory = sessionmaker(bind=get_engine(), future=True)
    order = _seed_order(db_session)
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CANCELLED,
        producer="order-service",
        correlation_id=str(uuid.uuid4()),
        data={"order_id": str(order.id)},
    )

    process_order_created(session_factory, envelope)  # must not raise or touch anything

    db_session.expire_all()
    refreshed = db_session.get(Order, order.id)
    assert refreshed.status == OrderStatus.CREATED.value
    assert db_session.query(ProcessedEvent).count() == 0
