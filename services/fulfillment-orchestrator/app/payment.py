"""Deterministic payment simulator.

No real payment processor, no PCI scope anywhere in this system. Outcomes
are controlled by marker SKUs in the order's line items so saga tests — and
later the Phase 8 failure lab — can deterministically trigger each outcome
without randomness. `attempt_number` is supplied by the caller (see
app.retry.retry_with_backoff) rather than tracked as internal state here, so
this function stays pure and safely re-callable.
"""

from __future__ import annotations

from dataclasses import dataclass

DECLINE_SKU = "SKU-PAYMENT-DECLINE"
TRANSIENT_RECOVER_SKU = "SKU-PAYMENT-TIMEOUT-RECOVER"
TRANSIENT_PERSISTENT_SKU = "SKU-PAYMENT-TIMEOUT-PERSISTENT"


class PaymentDeclinedError(Exception):
    """A hard decline — not retryable, the saga must compensate."""


class PaymentGatewayTimeoutError(Exception):
    """A transient failure — retryable."""


@dataclass
class PaymentAuthorization:
    approved: bool
    authorization_id: str


def authorize_payment(
    order_id: str, order_total: float, skus: list[str], attempt_number: int
) -> PaymentAuthorization:
    if DECLINE_SKU in skus:
        raise PaymentDeclinedError(f"order {order_id}: payment declined (simulated)")

    if TRANSIENT_PERSISTENT_SKU in skus:
        raise PaymentGatewayTimeoutError(
            f"order {order_id}: gateway timeout (simulated, persistent, attempt {attempt_number})"
        )

    if TRANSIENT_RECOVER_SKU in skus and attempt_number < 2:
        raise PaymentGatewayTimeoutError(
            f"order {order_id}: gateway timeout (simulated, attempt {attempt_number})"
        )

    return PaymentAuthorization(approved=True, authorization_id=f"auth-{order_id}")
