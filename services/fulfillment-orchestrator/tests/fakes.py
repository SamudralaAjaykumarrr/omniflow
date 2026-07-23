"""Hand-written fakes for OrderServiceClient/InventoryServiceClient — used
instead of respx-mocking two separate service URLs so saga tests can assert
directly against in-memory state (order status/version, stock levels,
reservation status) rather than parsing HTTP call args. The real clients
are exercised for real over HTTP in the docker-compose smoke test.
"""

from __future__ import annotations

from app.clients import (
    InventoryConflictError,
    OrderConflictError,
    OrderNotFoundRemoteError,
    OrderSnapshot,
    ReservationHandle,
)


class FakeOrderServiceClient:
    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.transition_calls: list[tuple] = []

    def seed_order(
        self,
        order_id: str,
        *,
        status: str,
        version: int,
        customer_id: str,
        order_total: float,
        items: list[dict],
    ) -> None:
        self.orders[order_id] = {
            "status": status,
            "version": version,
            "customer_id": customer_id,
            "order_total": order_total,
            "items": items,
            "node_id": None,
        }

    def get_order(self, order_id: str) -> OrderSnapshot:
        o = self.orders.get(order_id)
        if o is None:
            raise OrderNotFoundRemoteError(order_id)
        return OrderSnapshot(
            id=order_id,
            status=o["status"],
            version=o["version"],
            customer_id=o["customer_id"],
            order_total=o["order_total"],
            items=o["items"],
        )

    def transition(
        self,
        order_id: str,
        to_status: str,
        expected_version: int,
        reason: str,
        node_id: str | None = None,
    ) -> OrderSnapshot:
        self.transition_calls.append((order_id, to_status, expected_version, reason, node_id))
        o = self.orders.get(order_id)
        if o is None:
            raise OrderNotFoundRemoteError(order_id)
        if o["version"] != expected_version:
            raise OrderConflictError(f"stale version for {order_id}")
        o["status"] = to_status
        o["version"] += 1
        if node_id is not None:
            o["node_id"] = node_id
        return self.get_order(order_id)


class FakeInventoryServiceClient:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.stock: dict[tuple[str, str], int] = {}
        self.reservations: dict[str, dict] = {}
        self._next_id = 0
        self._forced_rejections: dict[str, int] = {}
        self._forced_sku_rejections: dict[tuple[str, str], int] = {}

    def force_reserve_rejection(self, node_id: str, times: int = 1) -> None:
        """Makes `reserve()` reject the next `times` calls for `node_id`
        regardless of actual stock — simulates a race where the advisory
        stock-check passed but a concurrent order won the row lock first.
        """
        self._forced_rejections[node_id] = times

    def force_reserve_rejection_for_sku(self, node_id: str, sku: str, times: int = 1) -> None:
        """Like `force_reserve_rejection`, but scoped to one (node, sku) pair
        — `check_stock` still reports the real (sufficient) quantity, only
        `reserve()` for that specific item rejects. Used to exercise
        partial-reservation rollback: item 1 at a node reserves fine, item 2
        at the same node is rejected by a race the pre-check couldn't see.
        """
        self._forced_sku_rejections[(node_id, sku)] = times

    def add_node(
        self,
        node_id: str,
        *,
        latitude: float,
        longitude: float,
        capacity_per_day: int,
        current_backlog: int = 0,
        active: bool = True,
    ) -> None:
        self.nodes.append(
            {
                "id": node_id,
                "latitude": latitude,
                "longitude": longitude,
                "capacity_per_day": capacity_per_day,
                "current_backlog": current_backlog,
                "active": active,
            }
        )

    def set_stock(self, node_id: str, sku: str, qty: int) -> None:
        self.stock[(node_id, sku)] = qty

    def list_nodes(self) -> list[dict]:
        return list(self.nodes)

    def check_stock(self, node_id: str, items: list[dict]) -> dict:
        shortfalls = []
        for item in items:
            available = self.stock.get((node_id, item["sku"]), 0)
            if available < item["qty"]:
                shortfalls.append(
                    {"sku": item["sku"], "requested_qty": item["qty"], "available_qty": available}
                )
        return {"node_id": node_id, "sufficient": not shortfalls, "shortfalls": shortfalls}

    def reserve(
        self, order_id: str, sku: str, node_id: str, qty: int, correlation_id: str
    ) -> ReservationHandle:
        remaining_forced = self._forced_rejections.get(node_id, 0)
        if remaining_forced > 0:
            self._forced_rejections[node_id] = remaining_forced - 1
            raise InventoryConflictError(f"forced rejection (race simulation) for {node_id}")

        remaining_sku_forced = self._forced_sku_rejections.get((node_id, sku), 0)
        if remaining_sku_forced > 0:
            self._forced_sku_rejections[(node_id, sku)] = remaining_sku_forced - 1
            raise InventoryConflictError(f"forced rejection (race simulation) for {sku}@{node_id}")

        available = self.stock.get((node_id, sku), 0)
        if available < qty:
            raise InventoryConflictError(f"insufficient stock for {sku} at {node_id}")
        self.stock[(node_id, sku)] = available - qty
        self._next_id += 1
        reservation_id = f"res-{self._next_id}"
        self.reservations[reservation_id] = {
            "sku": sku,
            "node_id": node_id,
            "qty": qty,
            "status": "ACTIVE",
        }
        return ReservationHandle(id=reservation_id, sku=sku, node_id=node_id, qty=qty)

    def release(self, reservation_id: str, reason: str) -> None:
        res = self.reservations.get(reservation_id)
        if res is None or res["status"] != "ACTIVE":
            raise InventoryConflictError(f"reservation {reservation_id} not active")
        res["status"] = "RELEASED"
        self.stock[(res["node_id"], res["sku"])] = (
            self.stock.get((res["node_id"], res["sku"]), 0) + res["qty"]
        )
