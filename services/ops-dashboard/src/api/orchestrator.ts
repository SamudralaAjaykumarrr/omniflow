import { API_BASE, get, post } from "./client";
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

/**
 * POST /dead-letters/{id}/replay — added in Phase 8 (failure-lab's
 * downstream-outage scenario needed this over HTTP, not just the CLI);
 * republishes the dead letter's original envelope back onto its topic and
 * marks it replayed. Closes the Phase 7 "CLI-only" limitation for this
 * screen too.
 */
export function replayDeadLetter(id: string) {
  return post<DeadLetterEvent>(BASE, `/dead-letters/${id}/replay`);
}
