# ADR 0010: Node-Scoring Formula and Saga Coordination via Direct REST

## Status
Accepted

## Context
Two things needed a concrete decision that Phase 0 planning left open:
(1) the actual formula behind "select a fulfillment node using stock,
distance, capacity, and delivery-promise signals" (`docs/product-
requirements.md`), and (2) how the Fulfillment Orchestrator actually talks
to Order Service and Inventory Service while executing a saga. Phase 0's
"Order sequence (happy path)" diagram sketched a fully event-driven flow
(`inventory.reservation.requested` published to a topic, Inventory Service
consuming it, publishing `inventory.reserved` back). Building the saga
literally that way means the orchestrator's own control flow — "did the
reservation succeed, what do I do next" — has to be reconstructed by
consuming its own downstream events, which is exactly the choreography
style ADR 0004 already rejected in favor of a central orchestrator that
"drives the next action."

## Decision

### Saga coordination: direct synchronous REST, informational events via Kafka
The orchestrator's Kafka consumption is real and is what actually starts and
resumes a saga (`order.validated`, `order.cancelled`) and routes poison
messages to the dead-letter table/topic. But once a saga is running, each
step (reserve inventory, check stock, transition order status, release on
compensation) is a direct, synchronous REST call to Order Service or
Inventory Service, not a second event round-trip. Both services still
publish their full documented event catalog (`inventory.reserved`,
`inventory.rejected`, `inventory.low`, `order.validated`, `order.cancelled`)
through their own outboxes — those events exist for the data platform
(Phase 4) and dashboard (Phase 7) to consume, not for saga control flow.
The orchestrator additionally publishes `inventory.reservation.requested`
itself (right before the real REST reservation call) purely so that event
exists in the stream for observability, even though nothing consumes it to
trigger action.

This makes the orchestrator a straightforward request/response state
machine to reason about and test (see `tests/test_saga_happy_path.py`,
`test_saga_failures.py`) while still emitting a complete, honest event
history. `docs/architecture.md`'s sequence diagrams are updated to show
both: the REST calls that actually drive the saga, and the events published
alongside them.

### Durability and crash-resume
Each saga step commits `saga_instances.current_step` (and a JSON `context`
scratchpad holding whatever the next step needs — the order snapshot,
ranked candidates, the chosen node, reservation ids, the payment
authorization id) before returning. On startup, the orchestrator resumes
every saga still `status = RUNNING` from exactly that `current_step`. A
narrow gap is accepted and documented rather than solved: if the process
crashes strictly between a reservation succeeding over REST and this step's
local commit, the orchestrator has no local record of that reservation and
fails the saga loudly (a clear `last_error`) instead of silently
double-reserving or guessing. Closing this gap for real needs idempotency
keys on Inventory Service's reservation endpoint tied to `(order_id, sku,
saga_step)`, so a resumed step can recognize "I already did this" — noted in
`RISKS.md` and `docs/interview-guide.md` as the next real improvement.

### Node-scoring formula
Candidate nodes must first pass a hard gate: Inventory Service's
`/stock/check` reports every line item as available at that node (an
advisory, unlocked pre-check — the real safety mechanism is the row lock in
`reserve_stock`, ADR 0002; a pass here followed by a reservation-time
rejection is possible under concurrency, and the saga falls back to the
next candidate when that happens, rolling back any already-reserved items
at the rejected node first).

Among nodes that pass the gate:

```
score = 0.35 * distance_score
      + 0.25 * delivery_score
      + 0.20 * backlog_score
      + 0.20 * capacity_score
```

- **distance_score / delivery_score** — min-max normalized within the
  candidate set (1.0 = closest/fastest among them, 0.0 = farthest/slowest;
  all-tied candidates — including the common single-candidate case — score
  1.0, since there is nothing to differentiate on). `delivery_score` is
  derived from distance via a simulated ground-shipping speed
  (500 km/day) plus one day of fixed processing time.
- **backlog_score** — `1 - current_backlog / capacity_per_day`, clipped to
  `[0, 1]`, per node (not comparative — a node's own headroom, independent
  of other candidates).
- **capacity_score** — `capacity_per_day / max(capacity_per_day)` among
  candidates (bigger raw daily throughput scores better).
- **stock** — always reported as `1.0` in the published `score_breakdown`;
  it is a gate, not a weighted term, so every node that reaches scoring
  already has it.

**Simulated distance**: there is no real customer geolocation anywhere in
this schema. A customer's location is derived deterministically from
`sha256(customer_id)` mapped onto a lat/long grid — stable per customer
(the same customer always scores the same candidate set the same way),
never random per request, which is what "simulated" is required to mean
here (`docs/product-requirements.md`: "Never fabricate ... deterministic").

## Consequences
- The saga is testable with plain function calls and hand-written fake
  REST clients (`tests/fakes.py`) — no need to run Kafka or two other
  live services to test saga logic, node fallback, or compensation.
- The event catalog stays complete and honest (all 11 event types are
  really published) even though only two of them (`order.validated`,
  `order.cancelled`) actually drive the orchestrator's behavior.
- The min-max normalization (not divide-by-max) is required for the
  single-candidate case to score correctly — an earlier divide-by-max
  version scored a lone candidate's distance/delivery components as 0.0
  (worst) instead of 1.0 (best, trivially, being the only option); caught by
  `tests/test_scoring.py::test_single_candidate_scores_perfectly_on_every_relative_component`
  before it shipped.
- The documented resume gap (reservation succeeds remotely, crash before
  local commit) is a real, accepted limitation of coordinating local saga
  state with remote REST calls without a second layer of idempotency keys —
  not silently ignored, but explicitly a "what I'd improve" item.

## Alternatives considered
- **Full choreography** (Inventory Service consumes
  `inventory.reservation.requested`, publishes `inventory.reserved`/
  `inventory.rejected`, orchestrator consumes those to continue): matches
  the original Phase 0 sketch more literally, but reintroduces exactly the
  "who's actually driving this workflow" ambiguity ADR 0004 rejected
  choreography for, and roughly doubles the event round-trips and
  idempotent-consumer surfaces needed for zero behavioral benefit at this
  project's scale.
- **Divide-by-max normalization** for distance/delivery (the first
  implementation): rejected after the single-candidate test above caught
  it scoring a lone, sufficient candidate as maximally undesirable on two
  of four weighted components.
