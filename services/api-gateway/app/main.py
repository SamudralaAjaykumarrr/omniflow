import logging
from collections import defaultdict, deque

from fastapi import FastAPI

from app.middleware import CorrelationIdMiddleware, RateLimitMiddleware, RequestLoggingMiddleware
from app.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="OmniFlow API Gateway",
    description=(
        "Edge API: request validation, correlation IDs, rate limiting, "
        "structured errors, request logging. Proxies to order-service and "
        "inventory-service; see docs/architecture.md for the full topology."
    ),
    version="0.1.0",
)
app.state.rate_limit_hits: dict[str, deque] = defaultdict(deque)

# Added in reverse-of-execution order: the LAST middleware added runs FIRST,
# so CorrelationIdMiddleware must be added last to set request.state.correlation_id
# before RateLimitMiddleware/RequestLoggingMiddleware read it.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(router)
