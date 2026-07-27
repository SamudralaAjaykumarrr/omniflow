import os

# Unconditional, not setdefault: when this suite runs via
# `docker compose run --rm api-gateway pytest`, docker-compose.yml has
# already injected GATEWAY_ORDER_SERVICE_URL/GATEWAY_INVENTORY_SERVICE_URL
# pointing at the real, healthy sibling containers — setdefault would be a
# no-op there, silently defeating the "upstream unreachable" test below.
os.environ["GATEWAY_ORDER_SERVICE_URL"] = "http://order-service-test"
os.environ["GATEWAY_INVENTORY_SERVICE_URL"] = "http://inventory-service-test"
# JWT settings: setdefault is fine here — `make test-gateway` already passes
# a real (test-only) secret + disables demo-user seeding; this only fills
# in defaults for an ad hoc `pytest` invocation outside that target.
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-never-used-outside-pytest")
os.environ.setdefault("GATEWAY_SEED_DEMO_USERS", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, get_db, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402,F401 (registers table with Base.metadata)
from app.security import hash_password  # noqa: E402
from event_contracts import create_access_token  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Schema is owned by Alembic migrations — entrypoint.sh runs `alembic
    upgrade head` before pytest ever starts. `create_all` here only backfills
    tables for the rare case pytest runs outside that entrypoint (a no-op
    otherwise). Deliberately never `drop_all` — see CLAUDE.md / RISKS.md #12."""
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


@pytest.fixture
def make_user(db_session):
    def _make(
        email: str = "user@example.com",
        password: str = "correct-horse-battery-staple",
        role: str = "viewer",
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email, password_hash=hash_password(password), role=role, is_active=is_active
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


@pytest.fixture
def make_token():
    def _make(
        *,
        user_id: str = "user-1",
        email: str = "user@example.com",
        role: str = "viewer",
        **overrides,
    ):
        settings = get_settings()
        return create_access_token(
            subject=user_id,
            email=email,
            role=role,
            secret=overrides.pop("secret", settings.jwt_secret_key),
            issuer=overrides.pop("issuer", settings.jwt_issuer),
            audience=overrides.pop("audience", settings.jwt_audience),
            expires_minutes=overrides.pop(
                "expires_minutes", settings.jwt_access_token_expires_minutes
            ),
        )

    return _make
