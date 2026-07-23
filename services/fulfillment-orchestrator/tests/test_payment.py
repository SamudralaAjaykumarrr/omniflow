import pytest

from app.payment import (
    DECLINE_SKU,
    TRANSIENT_PERSISTENT_SKU,
    TRANSIENT_RECOVER_SKU,
    PaymentDeclinedError,
    PaymentGatewayTimeoutError,
    authorize_payment,
)


def test_normal_order_is_approved():
    result = authorize_payment("order-1", 25.0, ["SKU-1"], attempt_number=1)
    assert result.approved is True
    assert result.authorization_id == "auth-order-1"


def test_decline_sku_raises_a_non_retryable_error():
    with pytest.raises(PaymentDeclinedError):
        authorize_payment("order-1", 25.0, [DECLINE_SKU], attempt_number=1)


def test_persistent_timeout_sku_always_raises_transient_error():
    for attempt in range(1, 5):
        with pytest.raises(PaymentGatewayTimeoutError):
            authorize_payment("order-1", 25.0, [TRANSIENT_PERSISTENT_SKU], attempt_number=attempt)


def test_recoverable_timeout_sku_fails_first_attempt_then_succeeds():
    with pytest.raises(PaymentGatewayTimeoutError):
        authorize_payment("order-1", 25.0, [TRANSIENT_RECOVER_SKU], attempt_number=1)

    result = authorize_payment("order-1", 25.0, [TRANSIENT_RECOVER_SKU], attempt_number=2)
    assert result.approved is True


def test_function_is_pure_and_stateless_across_calls():
    # Calling with attempt_number=1 again after a successful attempt=2 call
    # must still fail — there is no hidden internal counter.
    authorize_payment("order-1", 25.0, [TRANSIENT_RECOVER_SKU], attempt_number=2)
    with pytest.raises(PaymentGatewayTimeoutError):
        authorize_payment("order-1", 25.0, [TRANSIENT_RECOVER_SKU], attempt_number=1)
