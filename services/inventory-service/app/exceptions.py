class UnknownStockError(Exception):
    """A SKU/node combination has no inventory_stock row at all."""

    def __init__(self, sku: str, node_id: str) -> None:
        self.sku = sku
        self.node_id = node_id
        super().__init__(f"no stock record for sku={sku!r} at node={node_id}")


class InsufficientStockError(Exception):
    def __init__(self, sku: str, node_id: str, requested: int, available: int) -> None:
        self.sku = sku
        self.node_id = node_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient stock for sku={sku!r} at node={node_id}: "
            f"requested={requested}, available={available}"
        )


class ReservationNotFoundError(Exception):
    def __init__(self, reservation_id: str) -> None:
        self.reservation_id = reservation_id
        super().__init__(f"reservation {reservation_id} not found")


class ReservationNotActiveError(Exception):
    def __init__(self, reservation_id: str, status: str) -> None:
        self.reservation_id = reservation_id
        self.status = status
        super().__init__(f"reservation {reservation_id} is {status}, not ACTIVE")
