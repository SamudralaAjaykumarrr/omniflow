"""Exponential backoff + jitter retry for a single saga step (payment
authorization) — distinct from `event_contracts.run_consume_loop`'s
Kafka-message-redelivery retry, which governs a different axis (should this
whole message be reprocessed) than this one (should this specific
synchronous call be retried before either succeeding or triggering saga
compensation).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    def __init__(self, attempts: int, last_error: BaseException) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"gave up after {attempts} attempts: {last_error}")


def retry_with_backoff(
    fn: Callable[[int], T],
    *,
    retryable: tuple[type[BaseException], ...],
    max_attempts: int = 5,
    base_delay: float = 0.2,
    max_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn(attempt)` (1-indexed), retrying only on exceptions matching
    `retryable`, with exponential backoff (`base_delay * 2**(attempt-1)`,
    capped at `max_delay`) plus up to 10% jitter. Any other exception
    propagates immediately — a business rejection (e.g. a hard decline)
    should fail fast into compensation, not be retried. Raises
    RetryExhaustedError after `max_attempts`.
    """
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(attempt)
        except retryable as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay += random.uniform(0, delay * 0.1)
            sleep(delay)
    assert last_error is not None
    raise RetryExhaustedError(max_attempts, last_error)
