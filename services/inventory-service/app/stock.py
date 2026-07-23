import uuid

from sqlalchemy.orm import Session

from app.exceptions import UnknownStockError
from app.models import FulfillmentNode, InventoryStock
from app.schemas import SeedStockRequest


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
