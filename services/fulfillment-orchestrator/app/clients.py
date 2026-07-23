"""REST clients the orchestrator uses to drive Order Service and Inventory
Service through the saga — see docs/adrs/0010-node-scoring-and-saga-orchestration.md
for why saga coordination is direct REST rather than a second event-driven
round trip through inventory.reservation.requested/inventory.reserved.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class OrderConflictError(Exception):
    """Order Service rejected a transition: invalid transition or stale version."""


class OrderNotFoundRemoteError(Exception):
    pass


class InventoryConflictError(Exception):
    """Insufficient stock at reservation time (a race with the advisory
    pre-check) or an otherwise-rejected reservation/release request."""


@dataclass
class OrderSnapshot:
    id: str
    status: str
    version: int
    customer_id: str
    order_total: float
    items: list[dict]


@dataclass
class ReservationHandle:
    id: str
    sku: str
    node_id: str
    qty: int


def _to_snapshot(body: dict) -> OrderSnapshot:
    return OrderSnapshot(
        id=body["id"],
        status=body["status"],
        version=body["version"],
        customer_id=body["customer_id"],
        order_total=body["order_total"],
        items=body["items"],
    )


class OrderServiceClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def get_order(self, order_id: str) -> OrderSnapshot:
        resp = httpx.get(f"{self._base_url}/orders/{order_id}", timeout=self._timeout)
        if resp.status_code == 404:
            raise OrderNotFoundRemoteError(order_id)
        resp.raise_for_status()
        return _to_snapshot(resp.json())

    def transition(
        self,
        order_id: str,
        to_status: str,
        expected_version: int,
        reason: str,
        node_id: str | None = None,
    ) -> OrderSnapshot:
        payload = {"to_status": to_status, "expected_version": expected_version, "reason": reason}
        if node_id is not None:
            payload["node_id"] = node_id
        resp = httpx.post(
            f"{self._base_url}/orders/{order_id}/transition", json=payload, timeout=self._timeout
        )
        if resp.status_code == 404:
            raise OrderNotFoundRemoteError(order_id)
        if resp.status_code in (409, 422):
            raise OrderConflictError(resp.json().get("message", resp.text))
        resp.raise_for_status()
        return _to_snapshot(resp.json())


class InventoryServiceClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def list_nodes(self) -> list[dict]:
        resp = httpx.get(f"{self._base_url}/fulfillment-nodes", timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def check_stock(self, node_id: str, items: list[dict]) -> dict:
        resp = httpx.post(
            f"{self._base_url}/stock/check",
            json={"node_id": node_id, "items": items},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def reserve(
        self, order_id: str, sku: str, node_id: str, qty: int, correlation_id: str
    ) -> ReservationHandle:
        resp = httpx.post(
            f"{self._base_url}/reservations",
            json={
                "order_id": order_id,
                "sku": sku,
                "node_id": node_id,
                "qty": qty,
                "correlation_id": correlation_id,
            },
            timeout=self._timeout,
        )
        if resp.status_code in (404, 409):
            raise InventoryConflictError(resp.json().get("message", resp.text))
        resp.raise_for_status()
        body = resp.json()
        return ReservationHandle(
            id=body["id"], sku=body["sku"], node_id=body["node_id"], qty=body["qty"]
        )

    def release(self, reservation_id: str, reason: str) -> None:
        resp = httpx.post(
            f"{self._base_url}/reservations/{reservation_id}/release",
            json={"reason": reason},
            timeout=self._timeout,
        )
        if resp.status_code in (404, 409):
            raise InventoryConflictError(resp.json().get("message", resp.text))
        resp.raise_for_status()
