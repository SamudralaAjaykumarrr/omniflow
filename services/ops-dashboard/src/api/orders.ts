import { ApiError, API_BASE } from "./client";
import type { CancelOrderInput, CreateOrderInput, Order, OrderStatusHistoryEntry } from "./types";
import { get, post } from "./client";

const BASE = API_BASE.gateway;

/**
 * POST /api/orders — real order-service write path, proxied through the
 * gateway. Requires the `Idempotency-Key` header the gateway/order-service
 * contract enforces (services/order-service/app/routes.py:42); the shared
 * `post()` helper doesn't set custom headers, so this uses `fetch` directly.
 */
export async function createOrder(input: CreateOrderInput, idempotencyKey: string): Promise<Order> {
  const response = await fetch(`${BASE}/api/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    const message =
      body?.message ?? body?.detail ?? `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, body);
  }
  return (await response.json()) as Order;
}

/** GET /api/orders/{id} — real order-service read path. */
export function getOrder(orderId: string) {
  return get<Order>(BASE, `/api/orders/${orderId}`);
}

/** GET /api/orders/{id}/history — real order-service status-history path. */
export function getOrderHistory(orderId: string) {
  return get<OrderStatusHistoryEntry[]>(BASE, `/api/orders/${orderId}/history`);
}

/** POST /api/orders/{id}/cancel — real order-service cancellation path. */
export function cancelOrder(orderId: string, input: CancelOrderInput) {
  return post<Order>(BASE, `/api/orders/${orderId}/cancel`, input);
}
