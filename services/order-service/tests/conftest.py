import os

os.environ.setdefault(
    "ORDER_SERVICE_DATABASE_URL",
    "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_orders_test",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, get_db, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ProcessedEvent  # noqa: E402,F401 (registers table with Base.metadata)


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
def db_session():
    session_factory = sessionmaker(bind=get_engine(), future=True)
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
