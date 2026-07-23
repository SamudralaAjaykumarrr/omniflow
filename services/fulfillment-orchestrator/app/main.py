import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routes import router
from app.schemas import ErrorResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_ERROR_CODES_BY_STATUS = {404: "not_found", 409: "conflict", 422: "validation_error"}

app = FastAPI(
    title="OmniFlow Fulfillment Orchestrator",
    description=(
        "Read-only surface over saga state and dead letters (the consumer "
        "and outbox relay run as separate processes — see docker-compose.yml)."
    ),
    version="0.1.0",
)
app.include_router(router)


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
