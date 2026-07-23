import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import UnknownStockError
from app.models import FulfillmentNode, InventoryStock
from app.schemas import SeedStockRequest, StockCheckItem, StockCheckShortfall


def upsert_stock(db: Session, request: SeedStockRequest) -> InventoryStock:
    stock = db.get(InventoryStock, (request.sku, request.node_id))
    if stock is None:
        stock = InventoryStock(
            sku=request.sku,
            node_id=request.node_id,
            available_qty=request.available_qty,
            reorder_threshold=request.reorder_threshold,
        )
        db.add(stock)
    else:
        stock.available_qty = request.available_qty
        stock.reorder_threshold = request.reorder_threshold
        stock.version += 1
    db.commit()
    db.refresh(stock)
    return stock


def get_stock(db: Session, sku: str, node_id: uuid.UUID) -> InventoryStock:
    stock = db.get(InventoryStock, (sku, node_id))
    if stock is None:
        raise UnknownStockError(sku, str(node_id))
    return stock


def create_node(db: Session, node: FulfillmentNode) -> FulfillmentNode:
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def list_nodes(db: Session) -> list[FulfillmentNode]:
    return list(db.scalars(select(FulfillmentNode)))


def check_stock_sufficiency(
    db: Session, node_id: uuid.UUID, items: list[StockCheckItem]
) -> tuple[bool, list[StockCheckShortfall]]:
    """Best-effort, unlocked pre-check used by the orchestrator to rank
    candidate nodes before attempting a real reservation. Not the safety
    mechanism — `reserve_stock`'s row lock is (see ADR 0002) — so a pass here
    followed by a rejection at reservation time is possible under
    concurrency; the orchestrator falls back to the next candidate node
    when that happens.
    """
    shortfalls: list[StockCheckShortfall] = []
    for item in items:
        stock = db.get(InventoryStock, (item.sku, node_id))
        available = stock.available_qty if stock is not None else 0
        if available < item.qty:
            shortfalls.append(
                StockCheckShortfall(sku=item.sku, requested_qty=item.qty, available_qty=available)
            )
    return not shortfalls, shortfalls
