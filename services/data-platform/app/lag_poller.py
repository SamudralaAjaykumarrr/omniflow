"""Gold dataset #10 — consumer processing lag.

Kafka consumer-group lag isn't event data flowing through Bronze/Silver, so
it doesn't fit the "Silver stream in, windowed aggregate out" shape every
other Gold dataset shares (`app.gold.queries`) — it's a periodic snapshot of
Kafka's own consumer-group offset metadata, taken directly against the
broker via `confluent_kafka.Consumer.committed()`/`get_watermark_offsets()`,
same mechanism `event_contracts.metrics_setup.kafka_stats_callback` already
uses for the real-time Prometheus lag gauge (docs/data-pipeline.md's
"Consumer lag and pipeline metrics" — visible both operationally and, via
this dataset, historically).

Deliberately not Spark: booting a JVM to append a handful of rows every
poll interval would be pure overhead. This writes Parquet straight through
pyarrow/s3fs — no Kafka topic, no Bronze/Silver detour.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
from confluent_kafka import Consumer, TopicPartition

from app.config import Settings, get_settings
from app.s3 import s3_options

logger = logging.getLogger("data_platform.lag_poller")

POLL_INTERVAL_SECONDS = 15

# The only two real consumer groups in the system (docs/event-catalog.md's
# "Consumer idempotency" section; see services/order-service/app/validator_consumer.py
# and services/fulfillment-orchestrator/app/consumer.py for where these are
# defined) — Spark's own Kafka source manages its offsets via checkpoint,
# not a Kafka consumer group, so it deliberately isn't one of these.
CONSUMER_GROUPS: dict[str, list[str]] = {
    "order-service-validator": ["order.created"],
    "fulfillment-orchestrator": ["order.validated", "order.cancelled"],
}

LAG_SCHEMA = pa.schema(
    [
        ("polled_at", pa.timestamp("us", tz="UTC")),
        ("consumer_group", pa.string()),
        ("topic", pa.string()),
        ("partition", pa.int32()),
        ("committed_offset", pa.int64()),
        ("latest_offset", pa.int64()),
        ("lag", pa.int64()),
        ("date", pa.string()),
    ]
)


def poll_group_lag(settings: Settings, group_id: str, topics: list[str]) -> list[dict]:
    """One snapshot of every partition's lag for one consumer group.
    Read-only: this consumer never subscribes/joins the group, so polling
    lag never perturbs the real consumer's partition assignment or offsets."""
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": f"lag-poller-{group_id}",
            "enable.auto.commit": False,
        }
    )
    rows: list[dict] = []
    try:
        polled_at = datetime.now(UTC)
        for topic in topics:
            metadata = consumer.list_topics(topic, timeout=10)
            partitions = list(metadata.topics[topic].partitions.keys())
            tps = [TopicPartition(topic, p) for p in partitions]
            committed = consumer.committed(tps, timeout=10)
            for tp in committed:
                low, high = consumer.get_watermark_offsets(
                    TopicPartition(topic, tp.partition), timeout=10, cached=False
                )
                committed_offset = tp.offset if tp.offset >= 0 else low
                rows.append(
                    {
                        "polled_at": polled_at,
                        "consumer_group": group_id,
                        "topic": topic,
                        "partition": tp.partition,
                        "committed_offset": committed_offset,
                        "latest_offset": high,
                        "lag": max(high - committed_offset, 0),
                        "date": polled_at.date().isoformat(),
                    }
                )
    finally:
        consumer.close()
    return rows


def write_lag_snapshot(settings: Settings, rows: list[dict]) -> None:
    if not rows:
        return
    table = pa.Table.from_pylist(rows, schema=LAG_SCHEMA)
    fs = s3fs.S3FileSystem(**s3_options(settings))
    base = f"{settings.data_lake_bucket}/gold/consumer_lag"
    pq.write_to_dataset(
        table,
        root_path=base,
        partition_cols=["date"],
        filesystem=fs,
        basename_template="part-{i}-" + str(int(time.time() * 1000)) + ".parquet",
    )


def run_forever(settings: Settings) -> None:
    while True:
        try:
            rows = []
            for group_id, topics in CONSUMER_GROUPS.items():
                rows.extend(poll_group_lag(settings, group_id, topics))
            write_lag_snapshot(settings, rows)
            logger.info("lag snapshot written: %s row(s)", len(rows))
        except Exception:
            logger.exception("lag poll iteration failed")
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consumer-group lag poller (Gold dataset #10)")
    parser.add_argument(
        "--once", action="store_true", help="Poll once, write one snapshot, then exit."
    )
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    if args.once:
        rows = []
        for group_id, topics in CONSUMER_GROUPS.items():
            rows.extend(poll_group_lag(settings, group_id, topics))
        write_lag_snapshot(settings, rows)
        logger.info("lag snapshot written: %s row(s)", len(rows))
    else:
        run_forever(settings)


if __name__ == "__main__":
    main()
