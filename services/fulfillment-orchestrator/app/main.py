from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import get_settings
from app.db import get_engine
from app.middleware import CorrelationIdMiddleware
from app.routes import router
from app.schemas import ErrorResponse
from event_contracts import (
    MetricsMiddleware,
    configure_logging,
    configure_tracing,
    metrics_response,
    register_db_pool_collector,
)

_ERROR_CODES_BY_STATUS = {404: "not_found", 409: "conflict", 422: "validation_error"}

_settings = get_settings()
configure_logging(_settings.service_name)
configure_tracing(_settings.service_name, _settings.otel_exporter_otlp_endpoint)
register_db_pool_collector(get_engine())
# Note: this process (the read-only API) never calls httpx itself — the
# saga's REST calls to order/inventory services happen in app/consumer.py,
# a separate process, which is where HTTPXClientInstrumentor is applied.

app = FastAPI(
    title="OmniFlow Fulfillment Orchestrator",
    description=(
        "Read-only surface over saga state and dead letters (the consumer "
        "and outbox relay run as separate processes — see docker-compose.yml)."
    ),
    version="0.1.0",
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.include_router(router)
FastAPIInstrumentor.instrument_app(app)


@app.get("/metrics")
def metrics():
    return metrics_response()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="validation_error", message=str(exc.errors())
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    error_code = _ERROR_CODES_BY_STATUS.get(exc.status_code, "error")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error_code=error_code, message=str(exc.detail)).model_dump(),
    )
