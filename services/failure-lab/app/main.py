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

_ERROR_CODES_BY_STATUS = {
    404: "not_found",
    409: "conflict",
    422: "validation_error",
}

_settings = get_settings()
configure_logging(_settings.service_name)
configure_tracing(_settings.service_name, _settings.otel_exporter_otlp_endpoint)
HTTPXClientInstrumentor().instrument()
register_db_pool_collector(get_engine())

app = FastAPI(
    title="OmniFlow Failure Laboratory",
    description=(
        "Phase 8: 10 deterministic failure scenarios exercising saga compensation, retry/"
        "backoff, idempotency, concurrency control, dead-letter routing, and data-quality "
        "quarantine against the real running stack. See docs/phase-8-failure-laboratory.md."
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
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="validation_error",
            message=str(exc.errors()),
            correlation_id=correlation_id,
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    error_code = _ERROR_CODES_BY_STATUS.get(exc.status_code, "error")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code=error_code,
            message=str(exc.detail),
            correlation_id=correlation_id,
        ).model_dump(),
    )
