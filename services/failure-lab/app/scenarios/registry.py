"""The 10 deterministic Phase 8 failure scenarios, in the exact order
documented in docs/phase-8-failure-laboratory.md (matching the catalog
originally previewed by services/ops-dashboard/src/api/mock/failureLab.ts,
now the live backend behind it).
"""

from __future__ import annotations

from app.scenarios import (
    downstream_outage,
    duplicate_event_delivery,
    duplicate_order_submit,
    inventory_oversell_race,
    late_event_arrival,
    malformed_kafka_record,
    payment_decline,
    payment_timeout,
    poison_message_dlq,
    saga_crash_resume,
)
from app.scenarios.base import ScenarioEntry

_MODULES = [
    payment_decline,
    payment_timeout,
    inventory_oversell_race,
    duplicate_order_submit,
    duplicate_event_delivery,
    poison_message_dlq,
    malformed_kafka_record,
    late_event_arrival,
    saga_crash_resume,
    downstream_outage,
]

REGISTRY: dict[str, ScenarioEntry] = {
    module.id: ScenarioEntry(
        id=module.id,
        name=module.name,
        description=module.description,
        category=module.category,
        mechanism_reference=module.mechanism_reference,
        expected_failure_behavior=module.expected_failure_behavior,
        expected_recovery_behavior=module.expected_recovery_behavior,
        run=module.run,
        reset=module.reset,
    )
    for module in _MODULES
}

SCENARIO_ORDER: list[str] = [module.id for module in _MODULES]

assert len(REGISTRY) == 10, f"expected exactly 10 registered scenarios, found {len(REGISTRY)}"
