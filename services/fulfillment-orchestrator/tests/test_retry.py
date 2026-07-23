import pytest

from app.retry import RetryExhaustedError, retry_with_backoff


def test_succeeds_on_first_attempt_without_sleeping():
    sleeps = []
    result = retry_with_backoff(lambda attempt: "ok", retryable=(ValueError,), sleep=sleeps.append)
    assert result == "ok"
    assert sleeps == []


def test_retries_transient_failures_then_succeeds():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        if attempt < 3:
            raise ValueError("transient")
        return "recovered"

    sleeps = []
    result = retry_with_backoff(
        fn, retryable=(ValueError,), max_attempts=5, base_delay=0.01, sleep=sleeps.append
    )

    assert result == "recovered"
    assert calls == [1, 2, 3]
    assert len(sleeps) == 2  # slept between attempts 1->2 and 2->3, not after success


def test_backoff_delays_grow_exponentially_and_are_capped():
    def always_fails(attempt):
        raise ValueError("still failing")

    sleeps = []
    with pytest.raises(RetryExhaustedError):
        retry_with_backoff(
            always_fails,
            retryable=(ValueError,),
            max_attempts=4,
            base_delay=1.0,
            max_delay=2.5,
            sleep=sleeps.append,
        )

    # base_delay * 2**(attempt-1) for attempts 1,2,3 = 1, 2, 4 -> capped at 2.5
    # plus up to 10% jitter, so each observed delay must be within [base, cap*1.1]
    assert len(sleeps) == 3
    assert sleeps[0] >= 1.0
    assert sleeps[1] >= 2.0
    assert sleeps[2] <= 2.5 * 1.1


def test_non_retryable_exception_propagates_immediately_without_retrying():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        raise KeyError("not retryable here")

    with pytest.raises(KeyError):
        retry_with_backoff(fn, retryable=(ValueError,), max_attempts=5, sleep=lambda _: None)

    assert calls == [1]  # never retried


def test_exhaustion_raises_retry_exhausted_with_the_last_error():
    def fn(attempt):
        raise ValueError(f"fail {attempt}")

    with pytest.raises(RetryExhaustedError) as exc_info:
        retry_with_backoff(
            fn, retryable=(ValueError,), max_attempts=3, base_delay=0.001, sleep=lambda _: None
        )

    assert exc_info.value.attempts == 3
    assert "fail 3" in str(exc_info.value.last_error)
