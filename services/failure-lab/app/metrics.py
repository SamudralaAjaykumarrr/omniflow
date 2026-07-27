"""Failure-lab-specific Prometheus metrics — not shared infra (that's
`event_contracts.metrics_setup`), so these live here rather than in the
shared package.
"""

from prometheus_client import Counter, Histogram

FAILURE_LAB_SCENARIO_RUNS_TOTAL = Counter(
    "failure_lab_scenario_runs_total",
    "Failure-lab scenario executions, by scenario and terminal status",
    ["scenario_id", "status"],
)

FAILURE_LAB_SCENARIO_DURATION_SECONDS = Histogram(
    "failure_lab_scenario_duration_seconds",
    "Wall-clock duration of a failure-lab scenario run",
    ["scenario_id"],
)

FAILURE_LAB_SCENARIO_RESETS_TOTAL = Counter(
    "failure_lab_scenario_resets_total",
    "Failure-lab scenario reset() invocations, by scenario",
    ["scenario_id"],
)
