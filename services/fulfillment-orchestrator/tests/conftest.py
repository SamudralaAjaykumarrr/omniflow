import os

os.environ.setdefault(
    "ORCHESTRATOR_DATABASE_URL",
    "postgresql+psycopg://omniflow:omniflow@postgres:5432/omniflow_orchestrator_test",
)
# Fast, deterministic retry timing for tests — real defaults (200ms base,
# 5 attempts) would make the retry-exhaustion tests take seconds for no
# benefit; the backoff *shape* is what test_retry.py verifies, not the
# production timing.
os.environ.setdefault("ORCHESTRATOR_PAYMENT_MAX_ATTEMPTS", "3")
os.environ.setdefault("ORCHESTRATOR_PAYMENT_RETRY_BASE_DELAY_SECONDS", "0.001")
os.environ.setdefault("ORCHESTRATOR_PAYMENT_RETRY_MAX_DELAY_SECONDS", "0.01")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, get_db, get_engine  # noqa: E402
from app.models import DeadLetterEvent, OutboxEvent, ProcessedEvent, SagaInstance  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """See order-service/tests/conftest.py for why this never drop_alls —
    same reasoning applies here."""
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
