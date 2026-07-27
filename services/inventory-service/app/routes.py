import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.exceptions import (
    InsufficientStockError,
    ReservationNotActiveError,
    ReservationNotFoundError,
    UnknownStockError,
)
from app.models import FulfillmentNode
from app.outage import get_outage_state
from app.reservation import expire_stale_reservations, release_reservation, reserve_stock
from app.schemas import (
    CreateNodeRequest,
    EnableOutageRequest,
    NodeResponse,
    OutageStatus,
    ReleaseRequest,
    ReservationResponse,
    ReserveRequest,
    SeedStockRequest,
    StockCheckRequest,
    StockCheckResponse,
    StockResponse,
)
from app.stock import check_stock_sufficiency, create_node, get_stock, list_nodes, upsert_stock

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/fulfillment-nodes", response_model=NodeResponse, status_code=201)
def post_node(request: CreateNodeRequest, db: Session = Depends(get_db)):
    node = create_node(
        db,
        FulfillmentNode(
            name=request.name,
            latitude=request.latitude,
            longitude=request.longitude,
            capacity_per_day=request.capacity_per_day,
        ),
    )
    return NodeResponse.model_validate(node)


@router.get("/fulfillment-nodes", response_model=list[NodeResponse])
def list_nodes_route(db: Session = Depends(get_db)):
    return [NodeResponse.model_validate(n) for n in list_nodes(db)]


@router.post("/stock/check", response_model=StockCheckResponse)
def check_stock_route(request: StockCheckRequest, db: Session = Depends(get_db)):
    sufficient, shortfalls = check_stock_sufficiency(db, request.node_id, request.items)
    return StockCheckResponse(node_id=request.node_id, sufficient=sufficient, shortfalls=shortfalls)


@router.post("/stock", response_model=StockResponse)
def post_stock(request: SeedStockRequest, db: Session = Depends(get_db)):
    stock = upsert_stock(db, request)
    return StockResponse.model_validate(stock)


@router.get("/stock/{sku}/{node_id}", response_model=StockResponse)
def get_stock_route(sku: str, node_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        stock = get_stock(db, sku, node_id)
    except UnknownStockError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StockResponse.model_validate(stock)


@router.post("/reservations", response_model=ReservationResponse, status_code=201)
def post_reservation(request: ReserveRequest, db: Session = Depends(get_db)):
    try:
        reservation = reserve_stock(db, request)
    except UnknownStockError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReservationResponse.model_validate(reservation)


@router.post("/reservations/{reservation_id}/release", response_model=ReservationResponse)
def release_reservation_route(
    reservation_id: uuid.UUID, request: ReleaseRequest, db: Session = Depends(get_db)
):
    try:
        reservation = release_reservation(db, reservation_id, request.reason)
    except ReservationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReservationNotActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReservationResponse.model_validate(reservation)


@router.post("/reservations/expire", response_model=list[ReservationResponse])
def expire_reservations_route(db: Session = Depends(get_db)):
    expired = expire_stale_reservations(db)
    return [ReservationResponse.model_validate(r) for r in expired]


@router.post("/internal/failure-lab/outage/enable", response_model=OutageStatus)
def enable_outage_route(request: EnableOutageRequest):
    """Phase 8 downstream-outage scenario: see app.outage / app.middleware.
    SimulatedOutageMiddleware for what "enabled" does to every other route."""
    state = get_outage_state()
    state.enable(request.duration_seconds)
    return OutageStatus(active=state.active, until=state.until)


@router.post("/internal/failure-lab/outage/disable", response_model=OutageStatus)
def disable_outage_route():
    state = get_outage_state()
    state.disable()
    return OutageStatus(active=state.active, until=state.until)


@router.get("/internal/failure-lab/outage/status", response_model=OutageStatus)
def outage_status_route():
    state = get_outage_state()
    return OutageStatus(active=state.active, until=state.until)
