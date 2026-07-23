import os

# Unconditional, not setdefault: when this suite runs via
# `docker compose run --rm api-gateway pytest`, docker-compose.yml has
# already injected GATEWAY_ORDER_SERVICE_URL/GATEWAY_INVENTORY_SERVICE_URL
# pointing at the real, healthy sibling containers — setdefault would be a
# no-op there, silently defeating the "upstream unreachable" test below.
os.environ["GATEWAY_ORDER_SERVICE_URL"] = "http://order-service-test"
os.environ["GATEWAY_INVENTORY_SERVICE_URL"] = "http://inventory-service-test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
