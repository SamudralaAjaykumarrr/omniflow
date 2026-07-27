import uuid

import pytest

from app.config import get_settings
from app.scenarios.base import ScenarioContext
from tests.fakes import (
    FakeGatewayClient,
    FakeInventoryServiceClient,
    FakeKafkaProducer,
    FakeOrchestratorClient,
    FakeOrderServiceClient,
)


@pytest.fixture
def make_ctx(db_session):
    """Factory fixture: builds a ScenarioContext wired to fresh fakes by
    default, with any of them overridable per test."""

    def _make(
        *,
        gateway: FakeGatewayClient | None = None,
        order_service: FakeOrderServiceClient | None = None,
        inventory: FakeInventoryServiceClient | None = None,
        orchestrator: FakeOrchestratorClient | None = None,
        producer: FakeKafkaProducer | None = None,
    ) -> ScenarioContext:
        producer = producer if producer is not None else FakeKafkaProducer()
        return ScenarioContext(
            settings=get_settings(),
            gateway=gateway if gateway is not None else FakeGatewayClient(),
            order_service=order_service if order_service is not None else FakeOrderServiceClient(),
            inventory=inventory if inventory is not None else FakeInventoryServiceClient(),
            orchestrator=orchestrator if orchestrator is not None else FakeOrchestratorClient(),
            correlation_id=str(uuid.uuid4()),
            db=db_session,
            producer_factory=lambda: producer,
        )

    return _make
