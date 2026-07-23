# ADR 0003: Reliable Event Publish — Transactional Outbox, not CDC

## Status
Accepted

## Context
An order write and the `order.created` event it implies must be atomic: if
the DB commit succeeds but the event never gets published, downstream
inventory/fulfillment never hears about the order (a silently stuck order).
If the event publishes but the DB transaction rolls back, downstream systems
react to an order that doesn't exist. Postgres and Redpanda cannot share a
two-phase commit.

## Decision
Transactional outbox: the same DB transaction that writes/updates the
business row also inserts a row into `outbox_events` (aggregate id, event
type, payload, correlation/causation ids). A separate Outbox Relay worker
polls `outbox_events WHERE published_at IS NULL`, publishes to Redpanda, and
marks the row published. If the relay crashes mid-publish, the same row is
simply re-published on restart — the target topic is deduplicated downstream
by `event_id` (which is generated once, at insert time, and stored in the
outbox row — not regenerated on republish), so this is safe under
at-least-once delivery.

## Consequences
- Order/inventory writes and their events are atomic with respect to the
  local database, with no distributed transaction.
- Publish latency is bounded by the relay's poll interval (documented,
  default 250ms) — an honest, measurable tradeoff, not hidden.
- The outbox table needs housekeeping (archiving/deleting published rows past
  a retention window) — included in the Phase 2 implementation, not deferred
  indefinitely.

## Alternatives considered
- **Debezium / CDC on the WAL**: removes the polling latency and relay
  process, but adds a Kafka Connect deployment, WAL-level operational
  knowledge, and a heavier moving part for a project already running
  Postgres + Redpanda + Spark + observability stack on one machine. The
  correctness property (atomic write + eventual publish) is identical either
  way; CDC is the better choice at real production scale and is named here as
  the natural next step, not silently ignored.
- **Publish-then-write (event first, DB write second)**: if the DB write then
  fails, downstream systems have already reacted to an order that doesn't
  exist — rejected, this is strictly less safe than the outbox.
- **Write-then-publish, no outbox (publish directly after commit, best
  effort)**: a crash between commit and publish silently loses the event with
  no recovery path — rejected, this is exactly the failure mode the outbox
  exists to close.
