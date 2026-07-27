from app.scenarios.registry import REGISTRY, SCENARIO_ORDER

EXPECTED_IDS = [
    "payment-decline",
    "payment-timeout",
    "inventory-oversell-race",
    "duplicate-order-submit",
    "duplicate-event-delivery",
    "poison-message-dlq",
    "malformed-kafka-record",
    "late-event-arrival",
    "saga-crash-resume",
    "downstream-outage",
]


def test_registry_has_exactly_the_10_documented_scenarios():
    assert len(REGISTRY) == 10
    assert set(REGISTRY.keys()) == set(EXPECTED_IDS)
    assert SCENARIO_ORDER == EXPECTED_IDS


def test_every_scenario_has_complete_catalog_metadata():
    for scenario_id, entry in REGISTRY.items():
        assert entry.id == scenario_id
        assert entry.name
        assert entry.description
        assert entry.category
        assert entry.mechanism_reference
        assert entry.expected_failure_behavior
        assert entry.expected_recovery_behavior
        assert callable(entry.run)
        assert callable(entry.reset)
        assert entry.safe_to_rerun is True
