import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.outage import get_outage_state
from event_contracts import correlation_id_var

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Paths that must keep working even during a simulated outage: the failure
# lab's own control endpoints (so `disable` is always reachable) and
# /metrics (so Prometheus/Grafana can keep observing the service through
# the outage — arguably the most useful moment to watch it).
_OUTAGE_EXEMPT_PREFIXES = ("/internal/failure-lab/", "/metrics")


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


class SimulatedOutageMiddleware(BaseHTTPMiddleware):
    """Phase 8 downstream-outage scenario: while active, every route except
    the exempt prefixes above (including /healthz — deliberately, since the
    API Gateway's real /readyz live-pings this service's /healthz, and that
    genuine 503 propagating is the whole point of the scenario) returns 503
    instead of running its normal handler. See app.outage for why this is
    an in-process flag rather than actually stopping the container."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith(_OUTAGE_EXEMPT_PREFIXES) or not get_outage_state().active:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "status": "simulated_outage",
                "detail": "inventory-service is simulating an outage (Phase 8 failure lab)",
            },
        )
