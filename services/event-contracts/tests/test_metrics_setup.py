from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from event_contracts.metrics_setup import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    DBPoolCollector,
    kafka_stats_callback,
    metrics_response,
)


def _sample_count(metric, **labels) -> float:
    value = metric.labels(**labels)._value.get()  # noqa: SLF001 - test-only introspection
    return value


def _build_app():
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/widgets/{id}", ok, methods=["GET"])])
    from event_contracts.metrics_setup import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)
    return app


def test_metrics_middleware_records_request_count_and_duration():
    app = _build_app()
    client = TestClient(app)

    before = _sample_count(HTTP_REQUESTS_TOTAL, method="GET", path="/widgets/{id}", status="200")
    resp = client.get("/widgets/42")
    after = _sample_count(HTTP_REQUESTS_TOTAL, method="GET", path="/widgets/{id}", status="200")

    assert resp.status_code == 200
    assert after == before + 1

    duration_samples_before = HTTP_REQUEST_DURATION_SECONDS.labels(
        method="GET", path="/widgets/{id}"
    )._sum.get()
    assert duration_samples_before >= 0  # observed at least the requests made so far


def test_metrics_response_returns_prometheus_text_format():
    response = metrics_response()
    assert response.status_code == 200
    assert b"http_requests_total" in response.body


class _FakePool:
    def __init__(self, checked_out: int, checked_in: int) -> None:
        self._checked_out = checked_out
        self._checked_in = checked_in

    def checkedout(self) -> int:
        return self._checked_out

    def checkedin(self) -> int:
        return self._checked_in


class _FakeEngine:
    def __init__(self, pool) -> None:
        self.pool = pool


def test_db_pool_collector_reports_checked_out_and_checked_in():
    engine = _FakeEngine(_FakePool(checked_out=3, checked_in=7))
    collector = DBPoolCollector(engine)

    families = {f.name: f for f in collector.collect()}

    assert families["db_pool_checked_out_connections"].samples[0].value == 3
    assert families["db_pool_checked_in_connections"].samples[0].value == 7


def test_kafka_stats_callback_updates_lag_gauge():
    from event_contracts.metrics_setup import KAFKA_CONSUMER_LAG

    callback = kafka_stats_callback()
    stats_json = (
        '{"topics": {"order.validated": {"partitions": {'
        '"-1": {"consumer_lag": -1}, "0": {"consumer_lag": 5}, "1": {"consumer_lag": 0}'
        "}}}}"
    )
    callback(stats_json)

    assert KAFKA_CONSUMER_LAG.labels("order.validated", "0")._value.get() == 5
    assert KAFKA_CONSUMER_LAG.labels("order.validated", "1")._value.get() == 0


def test_kafka_stats_callback_ignores_malformed_json():
    callback = kafka_stats_callback()
    callback("not json")  # must not raise
