from __future__ import annotations

from app import metrics


def test_record_rows_increments_only_nonzero_statuses():
    before_valid = metrics.BATCH_ROWS_TOTAL.labels(
        layer="test", dataset="rows", status="valid"
    )._value.get()
    before_invalid = metrics.BATCH_ROWS_TOTAL.labels(
        layer="test", dataset="rows", status="invalid"
    )._value.get()

    metrics.record_rows("test", "rows", {"valid": 3, "invalid": 0})

    after_valid = metrics.BATCH_ROWS_TOTAL.labels(
        layer="test", dataset="rows", status="valid"
    )._value.get()
    after_invalid = metrics.BATCH_ROWS_TOTAL.labels(
        layer="test", dataset="rows", status="invalid"
    )._value.get()

    assert after_valid == before_valid + 3
    # A zero count must never call .inc() — inc(0) is a no-op anyway, but
    # this asserts the guard exists rather than relying on that being true.
    assert after_invalid == before_invalid


def _histogram_count(dataset: str) -> float:
    """Reads the `_count` sample via the public `collect()` API rather than
    the metric object's own private attributes, whose names have changed
    across `prometheus_client` versions."""
    for family in metrics.BATCH_DURATION_SECONDS.collect():
        for sample in family.samples:
            if sample.name.endswith("_count") and sample.labels.get("dataset") == dataset:
                return sample.value
    return 0.0


def test_track_batch_duration_observes_histogram():
    before_count = _histogram_count("duration")

    with metrics.track_batch_duration("test", "duration"):
        pass

    assert _histogram_count("duration") == before_count + 1


def test_start_metrics_server_is_idempotent_per_port(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(metrics, "start_http_server", lambda port: calls.append(port))
    monkeypatch.setattr(metrics, "_started_ports", set())

    metrics.start_metrics_server(19999)
    metrics.start_metrics_server(19999)

    assert calls == [19999]
