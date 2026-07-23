import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.proxy import forward

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    settings = get_settings()
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            order_health = await client.get(f"{settings.order_service_url}/healthz")
            inventory_health = await client.get(f"{settings.inventory_service_url}/healthz")
        except httpx.HTTPError:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
    if order_health.status_code != 200 or inventory_health.status_code != 200:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


@router.post("/api/orders")
async def create_order(request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, "/orders")


@router.get("/api/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}")


@router.get("/api/orders/{order_id}/history")
async def get_order_history(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}/history")


@router.post("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}/cancel")


@router.get("/api/inventory/stock/{sku}/{node_id}")
async def get_stock(sku: str, node_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.inventory_service_url, f"/stock/{sku}/{node_id}")
