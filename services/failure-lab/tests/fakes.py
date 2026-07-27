"""Hand-written fakes for the four REST clients app.clients defines — same
convention as fulfillment-orchestrator/tests/fakes.py: scenario unit tests
assert against in-memory state and can script exact response sequences,
instead of parsing respx call args against four separate mocked base URLs.
The real clients are exercised for real over HTTP by scripts/
phase8_smoke_test.sh (make phase8-smoke) against the live stack.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.clients import ConflictError, NotFoundError


@dataclass
class FakeResponse:
    status_code: int


class FakeGatewayClient:
    def __init__(self) -> None:
        self.created_orders: list[dict] = []
        self._idempotency_store: dict[str, tuple[str, dict]] = {}
        self.readyz_response: tuple[int, dict] = (200, {"status": "ready"})

    @staticmethod
    def _hash(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def create_order(self, payload: dict, idempotency_key: str) -> dict:
        payload_hash = self._hash(payload)
        existing = self._idempotency_store.get(idempotency_key)
        if existing is not None:
            stored_hash, response = existing
            if stored_hash != payload_hash:
                raise ConflictError(
                    "POST", "/api/orders", 409, "idempotency key reused with a different payload"
                )
            return response
        order_id = str(uuid.uuid4())
        response = {"id": order_id, "status": "CREATED", "version": 1}
        self._idempotency_store[idempotency_key] = (payload_hash, response)
        self.created_orders.append(payload)
        return response

    def readyz(self) -> tuple[int, dict]:
        return self.readyz_response


class FakeOrderServiceClient:
    def __init__(self, auto_process_events: bool = False) -> None:
        self.orders: dict[str, dict] = {}
        self.processed_events: dict[str, dict] = {}
        # Simulates an idempotent consumer that processes an event the
        # first time its status is checked — good enough to test
        # duplicate-event-delivery's "processed_at is stable across
        # redeliveries" assertion without a real Kafka consumer.
        self.auto_process_events = auto_process_events

    def get_order(self, order_id: str) -> dict:
        if order_id not in self.orders:
            raise NotFoundError("GET", f"/orders/{order_id}", 404, "not found")
        return self.orders[order_id]

    def get_history(self, order_id: str) -> list[dict]:
        return []

    def processed_event_status(
        self, event_id: str, consumer_name: str = "order-service-validator"
    ) -> dict:
        if event_id not in self.processed_events and self.auto_process_events:
            self.processed_events[event_id] = {
                "event_id": event_id,
                "consumer_name": consumer_name,
                "processed": True,
                "processed_at": "2026-01-01T00:00:00+00:00",
            }
        return self.processed_events.get(
            event_id,
            {
                "event_id": event_id,
                "consumer_name": consumer_name,
                "processed": False,
                "processed_at": None,
            },
        )


class FakeInventoryServiceClient:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.stock: dict[tuple[str, str], dict] = {}
        self.reservations: list[dict] = []
        self.outage_active = False
        self.outage_calls: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

    def list_nodes(self) -> list[dict]:
        return list(self.nodes.values())

    def get_or_create_node(self, name: str, **fields: Any) -> dict:
        for node in self.nodes.values():
            if node["name"] == name:
                return node
        node = {"id": str(uuid.uuid4()), "name": name, **fields}
        self.nodes[node["id"]] = node
        return node

    def upsert_stock(
        self, sku: str, node_id: str, available_qty: int, reorder_threshold: int = 0
    ) -> dict:
        stock = {
            "sku": sku,
            "node_id": node_id,
            "available_qty": available_qty,
            "reserved_qty": 0,
            "committed_qty": 0,
            "reorder_threshold": reorder_threshold,
            "version": 1,
        }
        self.stock[(sku, node_id)] = stock
        return stock

    def get_stock(self, sku: str, node_id: str) -> dict:
        return self.stock[(sku, node_id)]

    def reserve(
        self, order_id: str, sku: str, node_id: str, qty: int, correlation_id: str
    ) -> FakeResponse:
        # A real lock — faithfully models the real service's row-level-lock
        # guarantee (ADR 0002) for the inventory-oversell-race scenario's
        # concurrent-thread test, not just a single-threaded stand-in.
        with self._lock:
            stock = self.stock.get((sku, node_id))
            if stock is None:
                raise NotFoundError("POST", "/reservations", 404, "no stock record")
            if stock["available_qty"] < qty:
                raise ConflictError("POST", "/reservations", 409, "insufficient stock")
            stock["available_qty"] -= qty
            stock["reserved_qty"] += qty
            self.reservations.append(
                {
                    "id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "sku": sku,
                    "node_id": node_id,
                    "qty": qty,
                }
            )
        return FakeResponse(status_code=201)

    def release(self, reservation_id: str, reason: str) -> None:
        return None

    def enable_outage(self, duration_seconds: int) -> dict:
        self.outage_active = True
        self.outage_calls.append(("enable", duration_seconds))
        return {"active": True, "until": None}

    def disable_outage(self) -> dict:
        self.outage_active = False
        self.outage_calls.append(("disable", None))
        return {"active": False, "until": None}

    def outage_status(self) -> dict:
        return {"active": self.outage_active, "until": None}


@dataclass
class FakeOrchestratorClient:
    sagas: dict[str, dict] = field(default_factory=dict)
    dead_letters: list[dict] = field(default_factory=list)
    replayed_ids: list[str] = field(default_factory=list)
    resume_calls: list[str] = field(default_factory=list)
    on_resume: Any = (
        None  # optional callable(order_id) -> None, mutates self.sagas as a side effect
    )

    def get_saga_for_order(self, order_id: str) -> dict | None:
        return self.sagas.get(order_id)

    def list_dead_letters(self, unreplayed_only: bool = False) -> list[dict]:
        if unreplayed_only:
            return [d for d in self.dead_letters if d.get("replayed_at") is None]
        return list(self.dead_letters)

    def replay_dead_letter(self, dead_letter_id: str) -> dict:
        self.replayed_ids.append(dead_letter_id)
        for dead_letter in self.dead_letters:
            if dead_letter["id"] == dead_letter_id:
                dead_letter["replayed_at"] = "2026-01-01T00:00:00Z"
                return dead_letter
        return {"id": dead_letter_id}

    def resume_saga(self, order_id: str) -> dict | None:
        self.resume_calls.append(order_id)
        if self.on_resume is not None:
            self.on_resume(order_id)
        return self.sagas.get(order_id)


class FakeKafkaProducer:
    """Stands in for confluent_kafka.Producer — mimics just enough of its
    API (`produce`/`flush`) for `event_contracts.publish_envelope` and
    `app.kafka.publish_malformed_record` to work against it, without a live
    broker. Every `produce()` call is recorded for assertions, and the
    delivery callback is invoked synchronously (as if delivery always
    succeeds immediately) rather than needing a real `poll()` loop."""

    def __init__(self) -> None:
        self.produced: list[dict] = []

    def produce(self, topic, key=None, value=None, on_delivery=None) -> None:  # noqa: ANN001
        self.produced.append({"topic": topic, "key": key, "value": value})
        if on_delivery is not None:
            on_delivery(None, None)

    def flush(self, timeout: float | None = None) -> int:
        return 0
