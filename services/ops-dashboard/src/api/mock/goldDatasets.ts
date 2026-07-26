/**
 * Fixtures shaped like the 10 Gold datasets documented in
 * docs/data-pipeline.md's table (services/data-platform/app/gold/queries.py).
 * No browser-facing read API exists over MinIO's Gold Parquet yet — this is
 * a clearly-labeled local fallback, not live Gold data. Field names and
 * grains match the real datasets so a future thin read API is a drop-in
 * data source swap for this same UI.
 */

export interface OrdersPerMinutePoint {
  window_start: string;
  order_count: number;
}

export interface RevenueByProduct {
  sku: string;
  node_id: string;
  revenue: number;
}

export interface FulfillmentSuccessRatePoint {
  window_start: string;
  success_rate: number;
}

export interface StockoutFrequency {
  sku: string;
  rejection_count: number;
}

export interface DeadLetterVolume {
  event_type: string;
  failed_consumer: string;
  count: number;
}

export const MOCK_ORDERS_PER_MINUTE: OrdersPerMinutePoint[] = [
  { window_start: "13:00", order_count: 22 },
  { window_start: "13:05", order_count: 27 },
  { window_start: "13:10", order_count: 19 },
  { window_start: "13:15", order_count: 31 },
  { window_start: "13:20", order_count: 34 },
  { window_start: "13:25", order_count: 29 },
  { window_start: "13:30", order_count: 25 },
];

export const MOCK_REVENUE_BY_PRODUCT: RevenueByProduct[] = [
  { sku: "SKU-1042", node_id: "node-atl", revenue: 18420.5 },
  { sku: "SKU-2087", node_id: "node-dfw", revenue: 15310.0 },
  { sku: "SKU-3311", node_id: "node-ord", revenue: 12876.25 },
  { sku: "SKU-4456", node_id: "node-atl", revenue: 9902.75 },
  { sku: "SKU-5203", node_id: "node-sea", revenue: 7643.1 },
];

export const MOCK_FULFILLMENT_SUCCESS_RATE: FulfillmentSuccessRatePoint[] = [
  { window_start: "09:00", success_rate: 0.97 },
  { window_start: "10:00", success_rate: 0.96 },
  { window_start: "11:00", success_rate: 0.94 },
  { window_start: "12:00", success_rate: 0.98 },
  { window_start: "13:00", success_rate: 0.95 },
];

export const MOCK_STOCKOUT_FREQUENCY: StockoutFrequency[] = [
  { sku: "SKU-2087", rejection_count: 14 },
  { sku: "SKU-3311", rejection_count: 9 },
  { sku: "SKU-1042", rejection_count: 6 },
  { sku: "SKU-7788", rejection_count: 4 },
];

export const MOCK_DEAD_LETTER_VOLUME: DeadLetterVolume[] = [
  { event_type: "inventory.reservation.requested", failed_consumer: "inventory-service", count: 5 },
  { event_type: "order.validated", failed_consumer: "fulfillment-orchestrator", count: 3 },
  { event_type: "order.shipped", failed_consumer: "data-platform", count: 1 },
];
