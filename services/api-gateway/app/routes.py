import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.proxy import forward
from app.schemas import LoginRequest, MeResponse, TokenResponse
from app.security import get_current_user, issue_token, require_ops, require_viewer, verify_password
from event_contracts import TokenPayload

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


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Verifies bcrypt-hashed credentials and issues a short-lived JWT
    carrying the user's role (ADR 0009). Deliberately vague on failure — the
    same 401 for "no such user" and "wrong password" avoids confirming which
    emails are registered."""
    user = db.query(User).filter(User.email == request.email).one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(request.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="invalid email or password")
    token, expires_in = issue_token(user_id=str(user.id), email=user.email, role=user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/auth/me", response_model=MeResponse)
def me(user: TokenPayload = Depends(get_current_user)):
    return MeResponse(id=user.sub, email=user.email, role=user.role)


@router.post("/api/orders", dependencies=[Depends(require_ops)])
async def create_order(request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, "/orders")


@router.get("/api/orders/{order_id}", dependencies=[Depends(require_viewer)])
async def get_order(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}")


@router.get("/api/orders/{order_id}/history", dependencies=[Depends(require_viewer)])
async def get_order_history(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}/history")


@router.post("/api/orders/{order_id}/cancel", dependencies=[Depends(require_ops)])
async def cancel_order(order_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.order_service_url, f"/orders/{order_id}/cancel")


@router.get("/api/inventory/stock/{sku}/{node_id}", dependencies=[Depends(require_viewer)])
async def get_stock(sku: str, node_id: str, request: Request):
    settings = get_settings()
    return await forward(request, settings.inventory_service_url, f"/stock/{sku}/{node_id}")
