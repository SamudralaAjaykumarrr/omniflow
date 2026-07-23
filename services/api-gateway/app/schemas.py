def local_error(error_code: str, message: str, correlation_id: str | None) -> dict:
    """Build an ErrorResponse-shaped body for failures the gateway itself
    detects (rate limit, upstream unreachable) — upstream service errors are
    already shaped this way and are relayed verbatim instead."""
    return {"error_code": error_code, "message": message, "correlation_id": correlation_id}
