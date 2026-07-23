class OrderNotFoundError(Exception):
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"order {order_id} not found")


class IdempotencyKeyConflictError(Exception):
    """Same idempotency key reused with a different request payload."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"idempotency key {idempotency_key!r} reused with a different payload")


class ConcurrentUpdateError(Exception):
    """Optimistic concurrency check failed — order.version did not match."""

    def __init__(self, order_id: str, expected_version: int) -> None:
        self.order_id = order_id
        self.expected_version = expected_version
        super().__init__(
            f"order {order_id} was modified concurrently (expected version {expected_version})"
        )
