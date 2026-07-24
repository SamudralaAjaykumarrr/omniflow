import json
import logging

from event_contracts.logging_setup import JsonFormatter, correlation_id_var


def _make_record(message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_formatted_line_is_valid_json_with_expected_fields():
    formatter = JsonFormatter("order-service")
    record = _make_record("order created")
    line = formatter.format(record)

    payload = json.loads(line)
    assert payload["message"] == "order created"
    assert payload["service"] == "order-service"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert "timestamp" in payload


def test_correlation_id_is_included_when_set():
    formatter = JsonFormatter("order-service")
    token = correlation_id_var.set("corr-123")
    try:
        payload = json.loads(formatter.format(_make_record()))
        assert payload["correlation_id"] == "corr-123"
    finally:
        correlation_id_var.reset(token)


def test_correlation_id_is_null_when_not_set():
    formatter = JsonFormatter("order-service")
    payload = json.loads(formatter.format(_make_record()))
    assert payload["correlation_id"] is None


def test_extra_fields_are_included_without_clobbering_reserved_keys():
    formatter = JsonFormatter("order-service")
    record = _make_record()
    record.order_id = "abc-123"
    payload = json.loads(formatter.format(record))
    assert payload["order_id"] == "abc-123"
    assert payload["message"] == "hello"  # not overwritten by any extra


def test_exception_info_is_rendered_as_a_string():
    formatter = JsonFormatter("order-service")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert "ValueError: boom" in payload["exception"]
