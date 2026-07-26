import { API_BASE, get } from "./client";
import type { DeadLetterEvent, SagaInstance } from "./types";

const BASE = API_BASE.orchestrator;

/** GET /saga-instances — real fulfillment-orchestrator read path (not proxied by the gateway). */
export function listSagaInstances(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return get<SagaInstance[]>(BASE, `/saga-instances${qs}`);
}

/** GET /saga-instances/{order_id} */
export function getSagaInstanceForOrder(orderId: string) {
  return get<SagaInstance>(BASE, `/saga-instances/${orderId}`);
}

/** GET /dead-letters — real fulfillment-orchestrator DLQ read path. */
export function listDeadLetters(unreplayedOnly = true) {
  return get<DeadLetterEvent[]>(BASE, `/dead-letters?unreplayed_only=${unreplayedOnly}`);
}
