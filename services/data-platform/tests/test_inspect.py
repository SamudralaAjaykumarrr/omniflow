from __future__ import annotations

from app.inspect import summarize


def test_summarize_counts_objects_and_bytes_by_top_level_partition():
    objects = [
        {"Key": "bronze/event_type=order.created/date=2026-07-25/part-0.parquet", "Size": 100},
        {"Key": "bronze/event_type=order.created/date=2026-07-26/part-0.parquet", "Size": 50},
        {"Key": "bronze/event_type=order.shipped/date=2026-07-25/part-0.parquet", "Size": 25},
    ]

    result = summarize("bronze", objects)

    assert "3 object(s), 175 byte(s)" in result
    assert "event_type=order.created: 2 object(s)" in result
    assert "event_type=order.shipped: 1 object(s)" in result


def test_summarize_excludes_keep_placeholder_from_partition_breakdown():
    objects = [{"Key": "silver_rejects/.keep", "Size": 0}]

    result = summarize("silver_rejects", objects)

    assert "0 object(s), 0 byte(s)" in result
    assert ".keep" not in result


def test_summarize_handles_empty_prefix():
    result = summarize("gold", [])

    assert result == "gold: 0 object(s), 0 byte(s)"
