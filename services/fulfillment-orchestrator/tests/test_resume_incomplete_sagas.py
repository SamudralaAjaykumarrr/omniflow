"""Regression tests for a real bug found during Phase 8 validation:
`resume_incomplete_sagas` (called once at every consumer process startup)
used to let a single unresumable saga's exception crash the whole process
before it ever started consuming Kafka — found for real against a stale
RUNNING saga left over from earlier synthetic-generator testing, whose
order_id no longer existed in order-service. See RISKS.md and
app.saga.resume_incomplete_sagas's docstring.
"""

import uuid

from app.clients import OrderNotFoundRemoteError
from app.models import SagaInstance
from app.saga import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STEP_DONE,
    resume_incomplete_sagas,
)
from tests.fakes import FakeInventoryServiceClient, FakeOrderServiceClient


def _resumable_saga(order_client, inventory_client, order_id: str) -> SagaInstance:
    order_client.seed_order(
        order_id,
        status="VALIDATED",
        version=1,
        customer_id="customer-1",
        order_total=10.0,
        items=[{"sku": "SKU-1", "qty": 1, "unit_price": 10.0}],
    )
    inventory_client.add_node(
        "node-a", latitude=47.6, longitude=-122.3, capacity_per_day=100, current_backlog=0
    )
    inventory_client.set_stock("node-a", "SKU-1", 10)
    return SagaInstance(
        order_id=uuid.UUID(order_id),
        correlation_id=uuid.uuid4(),
        current_step="FETCH_ORDER",
        status=STATUS_RUNNING,
        context={},
    )


def test_a_saga_for_a_missing_order_is_marked_failed_not_crashed(db_session):
    order_client = FakeOrderServiceClient()  # no seeded order -> get_order raises
    inventory_client = FakeInventoryServiceClient()
    orphaned_order_id = str(uuid.uuid4())
    orphaned = SagaInstance(
        order_id=uuid.UUID(orphaned_order_id),
        correlation_id=uuid.uuid4(),
        current_step="FETCH_ORDER",
        status=STATUS_RUNNING,
        context={},
    )
    db_session.add(orphaned)
    db_session.commit()

    resumed_count = resume_incomplete_sagas(db_session, order_client, inventory_client)

    assert resumed_count == 1
    db_session.refresh(orphaned)
    assert orphaned.status == STATUS_FAILED
    assert orphaned.current_step == STEP_DONE
    assert "failed to resume at startup" in orphaned.last_error


def test_one_broken_saga_does_not_prevent_other_sagas_from_resuming(db_session):
    order_client = FakeOrderServiceClient()
    inventory_client = FakeInventoryServiceClient()

    good_order_id = str(uuid.uuid4())
    good_saga = _resumable_saga(order_client, inventory_client, good_order_id)
    db_session.add(good_saga)

    orphaned = SagaInstance(
        order_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        current_step="FETCH_ORDER",
        status=STATUS_RUNNING,
        context={},
    )
    db_session.add(orphaned)
    db_session.commit()

    resumed_count = resume_incomplete_sagas(db_session, order_client, inventory_client)

    assert resumed_count == 2
    db_session.refresh(good_saga)
    db_session.refresh(orphaned)
    assert good_saga.status == STATUS_COMPLETED  # resumed and completed normally
    assert orphaned.status == STATUS_FAILED  # failed loud, independently


def test_get_order_not_found_is_the_specific_error_this_guards_against(db_session):
    """Sanity check that the fixture actually reproduces the real failure
    mode (OrderNotFoundRemoteError), not some other unrelated error."""
    order_client = FakeOrderServiceClient()
    try:
        order_client.get_order(str(uuid.uuid4()))
        raise AssertionError("expected OrderNotFoundRemoteError")
    except OrderNotFoundRemoteError:
        pass
