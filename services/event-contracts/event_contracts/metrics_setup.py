"""Prometheus metrics shared by every service and worker.

Metric names are generic (`http_requests_total`, `kafka_consumer_lag`, ...);
which service/instance they came from is disambiguated by Prometheus's own
scrape-target labels (`job`, `instance`), not stuffed into every metric's
label set — the idiomatic Prometheus pattern.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import REGISTRY, Collector, CollectorRegistry
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

# Registered once at first import (module-level, per PEP 328 import caching)
# — re-importing this module within the same process never re-registers,
# which is what avoids prometheus_client's "Duplicated timeseries" error
# across repeated app construction in tests.
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests handled", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)
KAFKA_CONSUMER_RETRY_TOTAL = Counter(
    "kafka_consumer_retry_total", "Consumer message-processing retries", ["event_type"]
)
KAFKA_DEAD_LETTER_TOTAL = Counter(
    "kafka_dead_letter_total", "Messages routed to the dead-letter table/topic", ["event_type"]
)
KAFKA_MALFORMED_RECORD_TOTAL = Counter(
    "kafka_malformed_record_total",
    "Raw Kafka records that failed EventEnvelope parsing before any processing could even start "
    "(never routed to the per-event-type dead-letter path — there is no valid envelope to route)",
    ["topic"],
)
KAFKA_CONSUMER_LAG = Gauge(
    "kafka_consumer_lag",
    "Consumer lag in messages, per topic/partition (from librdkafka stats)",
    ["topic", "partition"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records request count + latency by (method, path, status). Uses the
    matched route's path template (e.g. `/orders/{order_id}`), not the raw
    URL, so per-order/per-reservation IDs don't explode the label
    cardinality."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            path = _route_template(request)
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(duration)
            HTTP_REQUESTS_TOTAL.labels(request.method, path, "500").inc()
            raise
        duration = time.perf_counter() - start
        path = _route_template(request)
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(duration)
        HTTP_REQUESTS_TOTAL.labels(request.method, path, str(response.status_code)).inc()
        return response


def _route_template(request: Request) -> str:
    """Resolve the matched route's path template (e.g. `/orders/{order_id}`)
    so per-order/per-reservation IDs don't explode metric-label
    cardinality. `request.scope["route"]` — the obvious way to get this —
    is not reliably populated yet by the time `BaseHTTPMiddleware.dispatch`
    gets control back from `call_next`, so this replicates Starlette's own
    route-matching against `request.app.routes` instead, which is
    independent of that timing quirk."""
    app = getattr(request, "app", None)
    for route in getattr(app, "routes", []):
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return request.url.path


def metrics_response() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


class DBPoolCollector(Collector):
    """A `prometheus_client` custom collector that reads a SQLAlchemy
    engine's connection pool state at scrape time (pull, not a
    continuously-updated push gauge) — checked-out/checked-in connection
    counts."""

    def __init__(self, engine) -> None:
        self._engine = engine

    def collect(self) -> Iterator[Metric]:
        pool = self._engine.pool
        checked_out = GaugeMetricFamily(
            "db_pool_checked_out_connections", "Checked-out (in-use) DB connections"
        )
        checked_out.add_metric([], pool.checkedout())
        yield checked_out

        checked_in = GaugeMetricFamily(
            "db_pool_checked_in_connections", "Checked-in (idle) DB connections"
        )
        checked_in.add_metric([], pool.checkedin())
        yield checked_in


def register_db_pool_collector(engine, registry: CollectorRegistry = REGISTRY) -> None:
    registry.register(DBPoolCollector(engine))


def kafka_stats_callback() -> Callable[[str], None]:
    """Builds a `stats_cb` for `confluent_kafka.Consumer` (paired with
    `statistics.interval.ms`) that updates `KAFKA_CONSUMER_LAG` from
    librdkafka's own per-partition `consumer_lag` stat."""

    def _callback(stats_json: str) -> None:
        try:
            stats = json.loads(stats_json)
        except (json.JSONDecodeError, TypeError):
            return
        for topic_name, topic_stats in stats.get("topics", {}).items():
            for partition_id, partition_stats in topic_stats.get("partitions", {}).items():
                if partition_id == "-1":
                    continue
                lag = partition_stats.get("consumer_lag")
                if lag is not None and lag >= 0:
                    KAFKA_CONSUMER_LAG.labels(topic_name, str(partition_id)).set(lag)

    return _callback
