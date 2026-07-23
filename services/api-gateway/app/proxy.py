import httpx
from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.schemas import local_error

_HOP_BY_HOP_REQUEST_HEADERS = {"host", "content-length", "x-correlation-id"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "connection"}


async def forward(request: Request, base_url: str, upstream_path: str) -> Response:
    """Forward `request` to `base_url + upstream_path`, relaying the body,
    correlation ID, and status/response body back verbatim. Gateway-local
    failures (upstream unreachable/timeout) get their own ErrorResponse-shaped
    body rather than leaking an httpx traceback to the caller.

    The inbound X-Correlation-ID (if any) is deliberately excluded from the
    copied header set and re-added once from `request.state.correlation_id`
    — copying it AND re-adding it under a different-case dict key produced
    two distinct header entries that httpx sent as two header lines, which
    the receiving side then joined into "id, id".
    """
    settings = get_settings()
    correlation_id = getattr(request.state, "correlation_id", None)
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_REQUEST_HEADERS
    }
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    body = await request.body()
    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=settings.upstream_timeout_seconds
        ) as client:
            upstream_response = await client.request(
                request.method,
                upstream_path,
                content=body,
                headers=headers,
                params=request.query_params,
            )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content=local_error(
                "upstream_timeout", f"{base_url} did not respond in time", correlation_id
            ),
        )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=502,
            content=local_error(
                "upstream_unavailable", f"{base_url} is unreachable", correlation_id
            ),
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers={
            k: v
            for k, v in upstream_response.headers.items()
            if k.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
        },
        media_type=upstream_response.headers.get("content-type"),
    )
