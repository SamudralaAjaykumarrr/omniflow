"""Inventory-service-specific Prometheus metrics — not shared infra (that's
`event_contracts.metrics_setup`), so these live here rather than in the
shared package.
"""

from prometheus_client import Counter

INVENTORY_RESERVATION_CONFLICTS_TOTAL = Counter(
    "inventory_reservation_conflicts_total",
    "Reservation attempts rejected for insufficient stock (ADR 0002)",
    ["sku"],
)
