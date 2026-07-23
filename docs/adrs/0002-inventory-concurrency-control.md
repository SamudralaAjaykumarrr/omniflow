# ADR 0002: Inventory Concurrency — Row-Level Locking + Optimistic Order Versioning

## Status
Accepted

## Context
Two correctness properties are the crux of this project: (1) two concurrent
requests for the last unit of a SKU must not both succeed, and (2) order state
transitions must not be silently clobbered by concurrent writers. These are
different contention profiles — inventory rows for popular SKUs are genuinely
hot (many orders racing for the same row), while a single order is normally
only touched by one saga at a time with occasional concurrent reads.

## Decision
Two different, individually justified strategies for two different tables:

- **`inventory_stock`: pessimistic row-level locking.** The reservation
  critical section runs `SELECT available_qty, reserved_qty FROM
  inventory_stock WHERE sku = :sku AND node_id = :node FOR UPDATE`, checks
  `available_qty >= requested_qty` inside the same transaction, and updates
  both counters before committing. Postgres serializes concurrent
  transactions on that row; the loser simply waits for the lock and then sees
  the post-update quantity, so it either succeeds against remaining stock or
  is correctly rejected — no lost updates, no oversell, no busy-retry storm.
- **`orders`: optimistic concurrency via a `version` integer column.** State
  transitions execute `UPDATE orders SET status = :new, version = version + 1
  WHERE id = :id AND version = :expected`. Zero rows affected means someone
  else moved the order first; the caller re-reads and retries or surfaces a
  409. Orders are not hot in the same way inventory rows are, so optimism
  (assume no conflict, detect it cheaply) is the lower-overhead choice, and it
  also demonstrates the technique the spec explicitly asks for ("optimistic
  concurrency protection").

## Consequences
- Two concurrency techniques are implemented and tested for real, not just
  described — a concurrency test drives N parallel reservation requests at a
  1-unit-remaining SKU and asserts exactly one succeeds; a second test drives
  two concurrent state transitions on one order and asserts one gets a 409.
- Row-level locks are held only for the duration of the small
  check-then-update transaction, not the whole saga, so lock contention does
  not extend to the payment-simulation or node-selection steps (those happen
  after the reservation transaction has already committed).
- Reservation expiration (a reservation not confirmed within its TTL reverts
  `reserved_qty` back to `available_qty`) is a separate, lock-scoped
  transaction on the same row — no additional concurrency primitive needed.

## Alternatives considered
- **Optimistic concurrency (version column) on `inventory_stock` too**: would
  require client-side retry loops under real contention (last-unit races are
  exactly the case where many transactions collide), trading a bounded lock
  wait for an unbounded retry storm. Rejected for the hot-row case.
- **Serializable transaction isolation for everything**: correct but forces
  Postgres to detect conflicts via serialization failures and retry at the
  application layer for every table, including low-contention ones — more
  retry-handling code for no benefit over targeted row locks + optimistic
  versioning.
- **Redis-based distributed lock / counter**: adds an operational dependency
  and a second source of truth for stock levels; rejected in favor of keeping
  Postgres the single authority for inventory correctness.
