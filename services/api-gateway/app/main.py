from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.config import get_settings
from app.db import SessionLocal, get_engine
from app.middleware import CorrelationIdMiddleware, RateLimitMiddleware, RequestLoggingMiddleware
from app.routes import router
from app.seed import seed_demo_users
from event_contracts import (
    MetricsMiddleware,
    configure_logging,
    configure_tracing,
    metrics_response,
    register_db_pool_collector,
)

_settings = get_settings()
configure_logging(_settings.service_name)
configure_tracing(_settings.service_name, _settings.otel_exporter_otlp_endpoint)
register_db_pool_collector(get_engine())
HTTPXClientInstrumentor().instrument()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db = SessionLocal()
    try:
        seed_demo_users(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="OmniFlow API Gateway",
    description=(
        "Edge API: request validation, correlation IDs, rate limiting, "
        "structured errors, request logging, JWT authentication + "
        "role-based authorization (ADR 0009). Proxies to order-service and "
        "inventory-service; see docs/architecture.md for the full topology."
    ),
    version="0.1.0",
    lifespan=_lifespan,
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
