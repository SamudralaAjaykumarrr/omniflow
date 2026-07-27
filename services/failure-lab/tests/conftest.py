import os

os.environ.setdefault(
    "FAILURE_LAB_DATABASE_URL",
    "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_failure_lab_test",
)
# Fast, deterministic polling for tests — production defaults (30s timeout)
# would make a poll-timeout test actually take 30 seconds for no benefit.
os.environ.setdefault("FAILURE_LAB_POLL_TIMEOUT_SECONDS", "1")
os.environ.setdefault("FAILURE_LAB_POLL_INTERVAL_SECONDS", "0.05")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, get_db, get_engine  # noqa: E402
from app.models import FailureLabDeadLetter, ScenarioReset, ScenarioRun  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """See order-service/tests/conftest.py for why this never drop_alls —
    same reasoning applies here (Alembic owns the schema; this only
    backfills tables for the case pytest runs outside entrypoint.sh, and
    truncates leftover rows from a stale prior run)."""
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
    from app.main import app

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def settings():
    return get_settings()
