import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from event_contracts import correlation_id_var

CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagate or mint a correlation ID for every request.

    Downstream code reads it from `request.state.correlation_id`; it is also
    set on `event_contracts.correlation_id_var` for the duration of the
    request, so every structured log line emitted while handling it carries
    the same id, and echoed back on the response so a caller who didn't
    supply one can still correlate logs/events for a request they made.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
