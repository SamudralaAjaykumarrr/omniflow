"""A single shared Kafka producer for the FastAPI process — used by the
`/dead-letters/{id}/replay` route (app.replay's `replay_one`, now also
reachable over HTTP rather than only via the CLI)."""

from functools import lru_cache

from confluent_kafka import Producer

from app.config import get_settings
from event_contracts import build_producer


@lru_cache
def get_producer() -> Producer:
    return build_producer(get_settings().kafka_bootstrap_servers)
