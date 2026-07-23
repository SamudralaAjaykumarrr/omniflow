import uuid
from datetime import UTC, datetime, timedelta

from app.models import InventoryReservation, ReservationStatus
from app.reservation import expire_stale_reservations
from app.stock import get_stock
from tests.conftest import seed_stock


def test_expire_stale_reservations_restores_stock(db_session, seeded_node):
    sku = "SKU-EXPIRE"
    seed_stock(db_session, seeded_node.id, sku=sku, available_qty=10)

    stale = InventoryReservation(
        order_id=uuid.uuid4(),
        sku=sku,
        node_id=seeded_node.id,
        qty=4,
        status=ReservationStatus.ACTIVE.value,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(stale)
    stock = get_stock(db_session, sku, seeded_node.id)
    stock.available_qty -= 4
    stock.reserved_qty += 4
    db_session.commit()

    still_active = InventoryReservation(
        order_id=uuid.uuid4(),
        sku=sku,
        node_id=seeded_node.id,
        qty=2,
        status=ReservationStatus.ACTIVE.value,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(still_active)
    stock2 = get_stock(db_session, sku, seeded_node.id)
    stock2.available_qty -= 2
    stock2.reserved_qty += 2
    db_session.commit()

    expired = expire_stale_reservations(db_session)

    assert len(expired) == 1
    assert expired[0].id == stale.id
    assert expired[0].status == ReservationStatus.EXPIRED.value

    db_session.expire_all()
    final_stock = get_stock(db_session, sku, seeded_node.id)
    # the stale reservation's 4 units are restored; the still-active one's 2 remain reserved
    assert final_stock.available_qty == 10 - 2
    assert final_stock.reserved_qty == 2
