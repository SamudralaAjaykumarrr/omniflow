from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

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
# Phase 8 added two routes that call order-service/inventory-service
# directly from this process (the saga-crash-resume `resume` route calls
# advance_saga, which makes the same REST calls app/consumer.py's saga
# consumer makes) — this process is no longer purely read-only, so it now
# instruments httpx too, same as every other FastAPI service.
HTTPXClientInstrumentor().instrument()

app = FastAPI(
    title="OmniFlow Fulfillment Orchestrator",
    description=(
        "Saga state and dead-letter read API, plus two Phase 8 failure-lab admin actions "
        "(dead-letter replay, on-demand saga resume) — the consumer and outbox relay still "
        "run as separate processes (see docker-compose.yml)."
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
