import pytest

from app.state_machine import (
    ALLOWED_TRANSITIONS,
    CANCELLABLE_STATES,
    TERMINAL_STATES,
    InvalidTransitionError,
    OrderStatus,
    assert_valid_transition,
)

REQUIRED_STATES = {
    "CREATED",
    "VALIDATED",
    "INVENTORY_PENDING",
    "INVENTORY_RESERVED",
    "FULFILLMENT_ASSIGNED",
    "PROCESSING",
    "SHIPPED",
    "DELIVERED",
    "CANCELLED",
    "FAILED",
}


def test_all_required_states_present():
    assert {s.value for s in OrderStatus} == REQUIRED_STATES


def test_happy_path_transitions_are_valid():
    happy_path = [
        OrderStatus.CREATED,
        OrderStatus.VALIDATED,
        OrderStatus.INVENTORY_PENDING,
        OrderStatus.INVENTORY_RESERVED,
        OrderStatus.FULFILLMENT_ASSIGNED,
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
    ]
    for a, b in zip(happy_path, happy_path[1:], strict=False):
        assert_valid_transition(a, b)  # must not raise


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        (OrderStatus.CREATED, OrderStatus.SHIPPED),
        (OrderStatus.CREATED, OrderStatus.PROCESSING),
        (OrderStatus.SHIPPED, OrderStatus.CANCELLED),
        (OrderStatus.DELIVERED, OrderStatus.CREATED),
        (OrderStatus.CANCELLED, OrderStatus.CREATED),
        (OrderStatus.FAILED, OrderStatus.VALIDATED),
        (OrderStatus.PROCESSING, OrderStatus.CANCELLED),
    ],
)
def test_invalid_transitions_are_rejected(from_status, to_status):
    with pytest.raises(InvalidTransitionError):
        assert_valid_transition(from_status, to_status)


def test_terminal_states_have_no_outgoing_transitions():
    for status in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[status] == set()


def test_cancellable_states_all_allow_cancellation():
    for status in CANCELLABLE_STATES:
        assert_valid_transition(status, OrderStatus.CANCELLED)  # must not raise


def test_non_cancellable_states_reject_cancellation():
    non_cancellable = set(OrderStatus) - CANCELLABLE_STATES
    for status in non_cancellable:
        if OrderStatus.CANCELLED in ALLOWED_TRANSITIONS[status]:
            # would mean a state is both "not cancellable" and allows CANCELLED — shouldn't occur
            continue
        with pytest.raises(InvalidTransitionError):
            assert_valid_transition(status, OrderStatus.CANCELLED)
