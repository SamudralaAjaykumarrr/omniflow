import os

os.environ.setdefault(
    "INVENTORY_SERVICE_DATABASE_URL",
    "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_inventory_test",
)

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, get_db, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import FulfillmentNode, InventoryStock  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Schema is owned by Alembic migrations — entrypoint.sh runs `alembic
    upgrade head` before pytest ever starts. `create_all` here only backfills
    tables for the rare case pytest runs outside that entrypoint (a no-op
    otherwise). Deliberately never `drop_all`: that wipes tables while
    leaving Alembic's own `alembic_version` bookkeeping in place, which
    desyncs the two the next time a new migration is added — a real bug
    hit during Phase 2 (see DECISIONS.md). Truncating (not dropping) at
    session start instead guards against leftover rows from a stale prior
    run without touching table structure or migration state.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    engine = get_engine()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def session_factory():
    return sessionmaker(bind=get_engine(), future=True)


@pytest.fixture
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_node(db_session):
    node = FulfillmentNode(
        name=f"node-{uuid.uuid4()}",
        latitude=40.0,
        longitude=-73.0,
        capacity_per_day=100,
    )
    db_session.add(node)
    db_session.commit()
    db_session.refresh(node)
    return node


def seed_stock(db_session, node_id, sku="SKU-1", available_qty=10, reorder_threshold=2):
    stock = InventoryStock(
        sku=sku,
        node_id=node_id,
        available_qty=available_qty,
        reorder_threshold=reorder_threshold,
    )
    db_session.add(stock)
    db_session.commit()
    return stock
