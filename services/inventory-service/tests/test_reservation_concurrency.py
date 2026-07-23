"""The concurrency test that justifies ADR 0002.

Fires many concurrent reservation attempts at a SKU with exactly one unit of
stock, each on its own DB session/connection (mirroring separate concurrent
requests). Row-level locking (`SELECT ... FOR UPDATE` in
app.reservation.reserve_stock) must serialize these so exactly one succeeds
and the stock ledger ends up consistent — no oversell, no lost update.
"""

import threading
import uuid

from app.exceptions import InsufficientStockError
from app.reservation import reserve_stock
from app.schemas import ReserveRequest
from app.stock import get_stock
from tests.conftest import seed_stock

CONCURRENT_ATTEMPTS = 10


def test_concurrent_reservations_for_last_unit_exactly_one_succeeds(
    db_session, session_factory, seeded_node
):
    sku = "SKU-LAST-UNIT"
    node_id = seeded_node.id  # read once, in the main thread — see module docstring
    seed_stock(db_session, node_id, sku=sku, available_qty=1)

    successes: list[uuid.UUID] = []
    failures: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        session = session_factory()
        try:
            request = ReserveRequest(
                order_id=uuid.uuid4(),
                sku=sku,
                node_id=node_id,
                qty=1,
                correlation_id=uuid.uuid4(),
            )
            try:
                reservation = reserve_stock(session, request)
                with lock:
                    successes.append(reservation.id)
            except InsufficientStockError:
                with lock:
                    failures.append("rejected")
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(CONCURRENT_ATTEMPTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 1, f"expected exactly 1 winner, got {len(successes)}: {successes}"
    assert len(failures) == CONCURRENT_ATTEMPTS - 1

    db_session.expire_all()
    final_stock = get_stock(db_session, sku, node_id)
    assert final_stock.available_qty == 0
    assert final_stock.reserved_qty == 1


def test_concurrent_reservations_exactly_consume_multi_unit_stock(
    db_session, session_factory, seeded_node
):
    """Same race, but with 5 units of stock and 10 attempts: exactly 5 win."""
    sku = "SKU-FIVE-UNITS"
    node_id = seeded_node.id  # read once, in the main thread — see module docstring
    seed_stock(db_session, node_id, sku=sku, available_qty=5)

    successes: list[uuid.UUID] = []
    lock = threading.Lock()

    def attempt() -> None:
        session = session_factory()
        try:
            request = ReserveRequest(
                order_id=uuid.uuid4(),
                sku=sku,
                node_id=node_id,
                qty=1,
                correlation_id=uuid.uuid4(),
            )
            try:
                reservation = reserve_stock(session, request)
                with lock:
                    successes.append(reservation.id)
            except InsufficientStockError:
                pass
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(CONCURRENT_ATTEMPTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) == 5

    db_session.expire_all()
    final_stock = get_stock(db_session, sku, node_id)
    assert final_stock.available_qty == 0
    assert final_stock.reserved_qty == 5
