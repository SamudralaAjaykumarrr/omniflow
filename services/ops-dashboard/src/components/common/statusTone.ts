export type StatusTone = "good" | "warning" | "serious" | "critical" | "neutral";

const GOOD = new Set(["SHIPPED", "COMPLETED", "PASS", "ok", "ready", "true", "ACTIVE"]);
const WARNING = new Set([
  "CREATED",
  "VALIDATED",
  "INVENTORY_PENDING",
  "INVENTORY_RESERVED",
  "FULFILLMENT_ASSIGNED",
  "PROCESSING",
  "RUNNING",
]);
const CRITICAL = new Set(["FAILED", "FAIL", "not_ready", "error", "CANCELLED"]);

/** Maps the many status-ish strings across this app (order/saga/health/DQ) to one of the four reserved status colors, never a categorical hue. */
export function statusTone(status: string): StatusTone {
  if (GOOD.has(status)) return "good";
  if (WARNING.has(status)) return "warning";
  if (CRITICAL.has(status)) return "critical";
  return "neutral";
}
