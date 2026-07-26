"""Prometheus metrics for the Spark bronze/silver/gold streaming jobs.

Closes RISKS.md #19: `docker-compose.yml`'s `spark-bronze`/`spark-silver`/
`spark-gold` services already declare and `expose` a `METRICS_PORT`, but
until this module nothing started a `prometheus_client` HTTP server on it,
and none of them ran any real per-job business metrics. Each job's `main()`
calls `start_metrics_server(settings.metrics_port)` once at startup — the
same standalone-exporter pattern every other background worker in this repo
already uses (event-contracts' outbox relays, order-service's validator
consumer, the orchestrator's saga consumer), just with Spark-specific
metric names. `infra/docker/prometheus/prometheus.yml` scrapes these same
ports.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Histogram, start_http_server

logger = logging.getLogger("data_platform.metrics")

BATCH_ROWS_TOTAL = Counter(
    "data_platform_batch_rows_total",
    "Rows processed per streaming micro-batch, by pipeline layer, dataset, and outcome "
    "(e.g. valid, invalid, late, malformed, output).",
    ["layer", "dataset", "status"],
)

BATCH_DURATION_SECONDS = Histogram(
    "data_platform_batch_duration_seconds",
    "Wall-clock time to process one streaming micro-batch (transform + write).",
    ["layer", "dataset"],
)

# A job's `main()` is exercised more than once in the same process during
# tests; `prometheus_client.start_http_server` raises `OSError` if asked to
# bind the same port twice, so this is made idempotent per-process.
_started_ports: set[int] = set()


def start_metrics_server(port: int) -> None:
    if port in _started_ports:
        return
    start_http_server(port)
    _started_ports.add(port)
    logger.info("metrics server started on port %s", port)


def record_rows(layer: str, dataset: str, counts: dict[str, int]) -> None:
    """`counts` maps outcome (e.g. "valid", "invalid", "late", "malformed",
    "output") to that micro-batch's row count for this layer/dataset. Only
    non-zero counts are recorded — an outcome that never happens simply
    never creates a labelled timeseries, rather than reporting a
    permanently-zero one."""
    for status, count in counts.items():
        if count:
            BATCH_ROWS_TOTAL.labels(layer=layer, dataset=dataset, status=status).inc(count)


@contextmanager
def track_batch_duration(layer: str, dataset: str) -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        BATCH_DURATION_SECONDS.labels(layer=layer, dataset=dataset).observe(
            time.monotonic() - start
        )
