import { API_BASE, get, post } from "./client";
import type { FulfillmentNode, Stock, StockCheckItemInput, StockCheckResult } from "./types";

const INVENTORY = API_BASE.inventory;
const GATEWAY = API_BASE.gateway;

/** GET /fulfillment-nodes — real inventory-service read path (not proxied by the gateway). */
export function listFulfillmentNodes() {
  return get<FulfillmentNode[]>(INVENTORY, "/fulfillment-nodes");
}

/** GET /api/inventory/stock/{sku}/{node_id} — real path, proxied through the gateway. */
export function getStock(sku: string, nodeId: string) {
  return get<Stock>(GATEWAY, `/api/inventory/stock/${encodeURIComponent(sku)}/${nodeId}`);
}

/** POST /stock/check — real inventory-service advisory pre-check (not proxied by the gateway). */
export function checkStock(nodeId: string, items: StockCheckItemInput[]) {
  return post<StockCheckResult>(INVENTORY, "/stock/check", { node_id: nodeId, items });
}
