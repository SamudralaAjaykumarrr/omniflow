import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.middleware import CorrelationIdMiddleware
from app.routes import router
from app.schemas import ErrorResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_ERROR_CODES_BY_STATUS = {
    404: "not_found",
    409: "conflict",
    422: "validation_error",
}

app = FastAPI(
    title="OmniFlow Inventory Service",
    description="Stock levels, concurrency-safe reservations, and release/expiry.",
    version="0.1.0",
)
app.add_middleware(CorrelationIdMiddleware)
app.include_router(router)


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
