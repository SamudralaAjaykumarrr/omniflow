"""Orchestrator-specific Prometheus metrics — not shared infra (that's
`event_contracts.metrics_setup`), so these live here rather than in the
shared package.
"""

from prometheus_client import Histogram

SAGA_DURATION_SECONDS = Histogram(
    "saga_duration_seconds",
    "Wall-clock time from saga creation to reaching a terminal state",
    ["result"],
)
