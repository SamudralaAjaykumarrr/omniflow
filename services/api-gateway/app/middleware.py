import logging
import time
import uuid
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.schemas import local_error
from event_contracts import correlation_id_var

CORRELATION_ID_HEADER = "X-Correlation-ID"

logger = logging.getLogger("api_gateway.access")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request log: one JSON-ish line per request with method,
    path, status, duration, and correlation_id — the minimum needed to trace
    a request through logs before the full OpenTelemetry pipeline (Phase 3)
    lands."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "correlation_id": correlation_id,
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window-per-client rate limit, in-process.

    Deliberately simple: a single-process in-memory counter is the honest
    local-demo substitute for a shared Redis-backed limiter, which is what a
    multi-instance deployment would need instead (see docs/reliability.md).
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._window_seconds = 60

    async def dispatch(self, request: Request, call_next) -> Response:
        limit = get_settings().rate_limit_per_minute
        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        # State lives on app.state (initialized in app.main), not on this
        # middleware instance — Starlette builds/caches one instance for the
        # app's whole lifetime, and tests need a reachable, resettable handle
        # on the hit counter without depending on TestClient's (version-
        # specific) way of simulating a distinct client host.
        hits_by_client: dict[str, deque] = request.app.state.rate_limit_hits
        window = hits_by_client[client_key]
        while window and now - window[0] > self._window_seconds:
            window.popleft()

        if len(window) >= limit:
            correlation_id = getattr(request.state, "correlation_id", None)
            return JSONResponse(
                status_code=429,
                content=local_error(
                    "rate_limited",
                    f"more than {limit} requests in {self._window_seconds}s",
                    correlation_id,
                ),
            )

        window.append(now)
        return await call_next(request)
