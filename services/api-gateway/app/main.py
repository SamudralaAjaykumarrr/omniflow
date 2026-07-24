from collections import defaultdict, deque

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.config import get_settings
from app.middleware import CorrelationIdMiddleware, RateLimitMiddleware, RequestLoggingMiddleware
from app.routes import router
from event_contracts import (
    MetricsMiddleware,
    configure_logging,
    configure_tracing,
    metrics_response,
)

_settings = get_settings()
configure_logging(_settings.service_name)
configure_tracing(_settings.service_name, _settings.otel_exporter_otlp_endpoint)
HTTPXClientInstrumentor().instrument()

app = FastAPI(
    title="OmniFlow API Gateway",
    description=(
        "Edge API: request validation, correlation IDs, rate limiting, "
        "structured errors, request logging. Proxies to order-service and "
        "inventory-service; see docs/architecture.md for the full topology."
    ),
    version="0.1.0",
)
app.state.rate_limit_hits = defaultdict(deque)

# Added in reverse-of-execution order: the LAST middleware added runs FIRST,
# so CorrelationIdMiddleware must be added last to set request.state.correlation_id
# before RateLimitMiddleware/RequestLoggingMiddleware/MetricsMiddleware read it.
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(router)
FastAPIInstrumentor.instrument_app(app)


@app.get("/metrics")
def metrics():
    return metrics_response()
