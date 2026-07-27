/**
 * Typed contracts mirroring the Pydantic response models in
 * services/{order-service,inventory-service,fulfillment-orchestrator}/app/schemas.py.
 * Keep these in sync by hand — there is no shared schema codegen in this
 * repo (Python services don't publish an OpenAPI client build step).
 */

export type OrderStatus =
  | "CREATED"
  | "VALIDATED"
  | "INVENTORY_PENDING"
  | "INVENTORY_RESERVED"
  | "FULFILLMENT_ASSIGNED"
  | "PROCESSING"
  | "SHIPPED"
  | "CANCELLED"
  | "FAILED";

export interface OrderItem {
  sku: string;
  qty: number;
  unit_price: number;
}

export interface Order {
  id: string;
  customer_id: string;
  status: OrderStatus;
  version: number;
  correlation_id: string;
  assigned_node_id: string | null;
  order_total: number;
  currency: string;
  items: OrderItem[];
  created_at: string;
  updated_at: string;
}

export interface OrderStatusHistoryEntry {
  from_status: string | null;
  to_status: string;
  reason: string | null;
  changed_at: string;
}

export interface CreateOrderItemInput {
  sku: string;
  qty: number;
  unit_price: number;
}

export interface CreateOrderInput {
  customer_id: string;
  customer_email: string;
  customer_display_name: string;
  items: CreateOrderItemInput[];
  currency?: string;
}

export interface CancelOrderInput {
  reason: string;
  expected_version: number;
}

export interface FulfillmentNode {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  capacity_per_day: number;
  current_backlog: number;
  active: boolean;
}

export interface Stock {
  sku: string;
  node_id: string;
  available_qty: number;
  reserved_qty: number;
  committed_qty: number;
  reorder_threshold: number;
  version: number;
  updated_at: string;
}

export interface StockCheckShortfall {
  sku: string;
  requested_qty: number;
  available_qty: number;
}

export interface StockCheckResult {
  node_id: string;
  sufficient: boolean;
  shortfalls: StockCheckShortfall[];
}

export interface StockCheckItemInput {
  sku: string;
  qty: number;
}

export interface SagaInstance {
  id: string;
  order_id: string;
  correlation_id: string;
  current_step: string;
  status: "RUNNING" | "COMPLETED" | "FAILED" | string;
  attempt_count: number;
  last_error: string | null;
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DeadLetterEvent {
  id: string;
  original_event_id: string;
  event_type: string;
  failed_consumer: string;
  error_type: string;
  error_message: string;
  attempt_count: number;
  payload: Record<string, unknown>;
  first_failed_at: string;
  last_failed_at: string;
  replayed_at: string | null;
}

/**
 * Phase 8 (Failure laboratory) — mirrors
 * services/failure-lab/app/schemas.py exactly.
 */
export type ScenarioRunStatus = "RUNNING" | "PASSED" | "RECOVERED" | "FAILED" | "ERROR";

export interface FailureScenarioCatalogEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  mechanism_reference: string;
  expected_failure_behavior: string;
  expected_recovery_behavior: string;
  safe_to_rerun: boolean;
}

export interface ScenarioRun {
  id: string;
  scenario_id: string;
  run_number: number;
  status: ScenarioRunStatus;
  correlation_id: string;
  summary: string | null;
  diagnostics: Record<string, unknown>;
  resources: Record<string, unknown>;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ScenarioResetResult {
  scenario_id: string;
  summary: string;
  reset_at: string;
}

export interface ScenarioDetail {
  catalog: FailureScenarioCatalogEntry;
  latest_run: ScenarioRun | null;
  last_reset: ScenarioResetResult | null;
  run_count: number;
}

export interface ApiErrorBody {
  error_code?: string;
  message?: string;
  detail?: string;
  correlation_id?: string | null;
}

export interface HealthStatus {
  status: string;
}

/**
 * Every screen that renders data tags it "live" (came from a real backend
 * call this session) or "mock" (no read API exists yet for that data —
 * docs/architecture.md itself calls the DQ/Gold/forecast read path "target
 * state, not yet built"). `MockDataNotice` renders a visible banner
 * whenever `source === "mock"`; never silently blended with real data.
 */
export type DataSource = "live" | "mock";
