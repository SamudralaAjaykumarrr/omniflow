# Event Catalog

All events are Kafka-protocol messages on Redpanda. Delivery is **at-least-once**
— nothing in this system claims exactly-once semantics. Every consumer is
required to be idempotent (see "Consumer idempotency" below). Topic naming is
`<event_type>` with dots (matches the event type itself), e.g. topic
`order.created`. Partition key is `order_id` (or `sku:node_id` for inventory
events) so that all events for one aggregate land on the same partition and
are processed in order relative to each other.

## Envelope (every event)

All events share this envelope; `data` is the event-specific payload.

```json
{
  "event_id": "uuid4",
  "event_type": "order.created",
  "schema_version": "1.0.0",
  "occurred_at": "2026-07-23T18:04:11.482Z",
  "producer": "order-service",
  "correlation_id": "uuid4 — ties every event in one order's lifecycle together",
  "causation_id": "uuid4 or null — event_id of the event that caused this one",
  "trace_context": {
    "traceparent": "00-<trace-id>-<span-id>-01"
  },
  "data": { "...": "event-specific fields" }
}
```

| Envelope field | Type | Rule |
|---|---|---|
| `event_id` | UUID v4 | Unique per event; consumers dedupe on this |
| `event_type` | string | Matches the topic name |
| `schema_version` | semver | Bumped per the compatibility rules below |
| `occurred_at` | RFC3339 UTC | Always UTC, never local time |
| `producer` | string | Service name that emitted the event |
| `correlation_id` | UUID v4 | Set once at order creation, propagated everywhere |
| `causation_id` | UUID v4 or null | Points at the direct cause; null only for root events (`order.created`) |
| `trace_context.traceparent` | W3C Trace Context string | Enables Jaeger to stitch the whole saga into one trace |

## Schema compatibility rule

Additive, backward-compatible changes (new optional field) bump the **patch**
version. New required field or changed field type bumps **minor** and requires
a migration window where both old and new consumers run. Removing/renaming a
field is a **major** bump and requires a new topic version
(`order.created.v2`) rather than breaking the existing one in place. Contract
tests (`docs/testing-strategy.md`) assert that a producer's current payload
still validates against the last two published schema versions.

## Events

### 1. `order.created` (v1.0.0)
- **Producer:** Order Service (via Outbox Relay)
- **Consumers:** Fulfillment Orchestrator, Spark (bronze)
- **Trigger:** New order persisted (state `CREATED`), first event in the saga (`causation_id: null`)
- **Payload:** `order_id, customer_id, correlation_id, items[{sku, node_hint, qty, unit_price}], order_total, currency, idempotency_key`

### 2. `order.validated` (v1.0.0)
- **Producer:** Order Service
- **Consumers:** Fulfillment Orchestrator, Spark
- **Trigger:** Payload/customer validation passed, state `CREATED -> VALIDATED`
- **Payload:** `order_id, validated_at`

### 3. `inventory.reservation.requested` (v1.0.0)
- **Producer:** Fulfillment Orchestrator
- **Consumers:** Inventory Service, Spark
- **Trigger:** Orchestrator begins the reservation step of the saga, state `VALIDATED -> INVENTORY_PENDING`
- **Payload:** `order_id, items[{sku, qty}], candidate_node_ids[]`

### 4. `inventory.reserved` (v1.0.0)
- **Producer:** Inventory Service
- **Consumers:** Fulfillment Orchestrator, Spark
- **Trigger:** All line items successfully reserved (row-lock section committed), state `INVENTORY_PENDING -> INVENTORY_RESERVED`
- **Payload:** `order_id, reservations[{sku, node_id, qty, reservation_id, expires_at}]`

### 5. `inventory.rejected` (v1.0.0)
- **Producer:** Inventory Service
- **Consumers:** Fulfillment Orchestrator, Spark
- **Trigger:** Insufficient stock for one or more items across all candidate nodes
- **Payload:** `order_id, reasons[{sku, requested_qty, available_qty}]`

### 6. `fulfillment.assigned` (v1.0.0)
- **Producer:** Fulfillment Orchestrator
- **Consumers:** Order Service, Spark
- **Trigger:** Node scoring complete and a node selected, state `INVENTORY_RESERVED -> FULFILLMENT_ASSIGNED`
- **Payload:** `order_id, node_id, score, score_breakdown{stock, distance, capacity, delivery_estimate, backlog}, estimated_ship_date`

### 7. `order.shipped` (v1.0.0)
- **Producer:** Fulfillment Orchestrator (after simulated payment capture)
- **Consumers:** Order Service, Spark
- **Trigger:** Payment authorized and fulfillment confirmed, state `PROCESSING -> SHIPPED`
- **Payload:** `order_id, node_id, shipped_at, carrier_sim, tracking_ref`

### 8. `order.cancelled` (v1.0.0)
- **Producer:** Order Service
- **Consumers:** Inventory Service (release), Fulfillment Orchestrator (abort saga), Spark
- **Trigger:** Customer/ops cancellation request accepted by the state machine (only from cancellable states)
- **Payload:** `order_id, cancelled_by, reason, previous_state`

### 9. `order.failed` (v1.0.0)
- **Producer:** Fulfillment Orchestrator
- **Consumers:** Order Service, Spark
- **Trigger:** Saga compensation completed after unrecoverable failure (retries exhausted), state `-> FAILED`
- **Payload:** `order_id, failed_step, reason, compensations_applied[]`

### 10. `inventory.low` (v1.0.0)
- **Producer:** Inventory Service
- **Consumers:** Spark, Dashboard alerting view
- **Trigger:** `available_qty` for a SKU/node crosses below its configured reorder threshold
- **Payload:** `sku, node_id, available_qty, threshold, evaluated_at`

### 11. `deadletter.event` (v1.0.0)
- **Producer:** Any consumer, on retry exhaustion or poison-message detection
- **Consumers:** Spark, Dashboard DLQ viewer, Replay tool
- **Trigger:** A consumer failed to process an event after its configured max retries/backoff window
- **Payload:** `original_event (full envelope + data), failed_consumer, error_type, error_message, attempt_count, first_failed_at, last_failed_at`

## Consumer idempotency

Every consumer maintains a `processed_events` record (`event_id`, consumer
name, processed_at) checked before applying side effects, so redelivery of an
already-applied event is a no-op. This is what makes at-least-once delivery
safe without claiming exactly-once.

## Retry policy (consumers)

Exponential backoff with jitter: `base=200ms, factor=2, max=30s`, capped at a
configurable max attempt count (default 5). Exhaustion routes the original
event to `deadletter.event` with full failure context, never silently dropped.

## Replay tooling

A CLI (`scripts/replay_events.py`, Phase 2) re-publishes a `deadletter.event`'s
`original_event` back onto its original topic after an operator fixes the root
cause, preserving `event_id` (so idempotent consumers correctly treat it as
the same logical event, not a new one).
