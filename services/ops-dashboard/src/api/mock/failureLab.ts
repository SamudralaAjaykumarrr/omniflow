/**
 * Failure Laboratory scenario catalog. Phase 8 ("Failure laboratory", 10
 * deterministic scenarios) is listed `Not started` in PROJECT_STATUS.md —
 * there is no backend to trigger these yet. This screen documents the
 * planned scenarios (each grounded in a mechanism this repo has already
 * built and documented — RISKS.md / docs/architecture.md) as an inert
 * preview, not a working control panel; every trigger is disabled and
 * labeled so this never reads as a real capability.
 */
export interface FailureScenario {
  id: string;
  name: string;
  description: string;
  exercises: string;
  reference: string;
}

export const FAILURE_LAB_SCENARIOS: FailureScenario[] = [
  {
    id: "payment-decline",
    name: "Payment hard decline",
    description: "Force the deterministic payment simulator to decline an in-flight order.",
    exercises: "Saga compensation: inventory reservation release, order -> FAILED.",
    reference: "docs/architecture.md — Saga compensation (failure path)",
  },
  {
    id: "payment-timeout",
    name: "Payment gateway timeout",
    description: "Force a transient timeout on the first authorization attempt.",
    exercises: "Retry with backoff + jitter before a second attempt succeeds or exhausts.",
    reference: "docs/event-catalog.md — Retry policy (consumers)",
  },
  {
    id: "inventory-oversell-race",
    name: "Concurrent reservation race",
    description: "Fire N concurrent reservation requests for the last unit of one SKU/node.",
    exercises: "Row-level locking (SELECT ... FOR UPDATE) — exactly one reservation succeeds.",
    reference: "ADR 0002 — Inventory concurrency control",
  },
  {
    id: "duplicate-order-submit",
    name: "Duplicate order submission",
    description: "Replay the same Idempotency-Key + payload against POST /api/orders.",
    exercises: "Idempotency-key dedup — identical cached response returned, no duplicate order.",
    reference: "docs/data-model.md — idempotency_keys",
  },
  {
    id: "duplicate-event-delivery",
    name: "Duplicate event redelivery",
    description: "Re-publish an already-processed event with the same event_id.",
    exercises: "processed_events idempotent-consumer ledger — no-op re-apply.",
    reference: "docs/event-catalog.md — Consumer idempotency",
  },
  {
    id: "poison-message-dlq",
    name: "Poison message / retry exhaustion",
    description: "Feed a consumer an event that fails every retry attempt.",
    exercises:
      "Exponential backoff to exhaustion, routed to deadletter.event, never dropped silently.",
    reference: "docs/event-catalog.md — Retry policy; Dead Letter Queue screen",
  },
  {
    id: "malformed-kafka-record",
    name: "Malformed Kafka record",
    description: "Publish a non-JSON / non-envelope-shaped raw record onto a real topic.",
    exercises: "Bronze's malformed-JSON quarantine (bronze_rejects), never written as if valid.",
    reference: "docs/data-pipeline.md — Bronze, malformed-event handling",
  },
  {
    id: "late-event-arrival",
    name: "Late-arriving event",
    description:
      "Publish an event whose occurred_at trails real time well past the dedup watermark.",
    exercises: "Silver's late_events side path, distinct from silver_rejects.",
    reference: "docs/data-pipeline.md — Watermarks and late data",
  },
  {
    id: "saga-crash-resume",
    name: "Orchestrator crash mid-saga",
    description: "Kill the orchestrator consumer process between two saga steps.",
    exercises: "Resumable saga_instances-backed recovery on restart (known gap: RISKS.md #11).",
    reference: "RISKS.md #11 — Saga resume gap",
  },
  {
    id: "downstream-outage",
    name: "Downstream service outage",
    description: "Stop inventory-service while orders are mid-saga.",
    exercises: "Gateway /readyz degradation, saga retry/backoff against an unreachable dependency.",
    reference: "docs/architecture.md — Service boundaries",
  },
];
