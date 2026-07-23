# Data Model

Transactional store is PostgreSQL, owned per-service (Order Service and
Inventory Service each own their tables; no cross-service foreign keys at the
DB level — cross-service references are by ID only, enforced in application
code and checked by data-quality jobs downstream). Migrations are managed with
Alembic, one migration chain per service.

## Entity-relationship diagram

```mermaid
erDiagram
  CUSTOMERS ||--o{ ORDERS : places
  ORDERS ||--o{ ORDER_ITEMS : contains
  ORDERS ||--o{ ORDER_STATUS_HISTORY : transitions
  ORDERS ||--o{ OUTBOX_EVENTS : emits
  ORDERS ||--o| IDEMPOTENCY_KEYS : "created via"
  ORDERS ||--o{ SAGA_INSTANCES : orchestrated_by
  FULFILLMENT_NODES ||--o{ INVENTORY_STOCK : stocks
  INVENTORY_STOCK ||--o{ INVENTORY_RESERVATIONS : "reserved from"
  ORDERS ||--o{ INVENTORY_RESERVATIONS : reserves
  FULFILLMENT_NODES ||--o{ ORDERS : "assigned to (via saga)"
  USERS ||--o{ AUDIT_LOG : performs

  CUSTOMERS {
    uuid id PK
    string email
    string display_name
    timestamptz created_at
  }
  ORDERS {
    uuid id PK
    uuid customer_id FK
    string status
    int version
    uuid correlation_id
    uuid assigned_node_id
    numeric order_total
    string currency
    timestamptz created_at
    timestamptz updated_at
  }
  ORDER_ITEMS {
    uuid id PK
    uuid order_id FK
    string sku
    int qty
    numeric unit_price
  }
  ORDER_STATUS_HISTORY {
    uuid id PK
    uuid order_id FK
    string from_status
    string to_status
    string reason
    timestamptz changed_at
  }
  IDEMPOTENCY_KEYS {
    string idempotency_key PK
    string request_hash
    jsonb response_body
    int response_status
    uuid order_id FK
    timestamptz created_at
    timestamptz expires_at
  }
  OUTBOX_EVENTS {
    uuid id PK
    string aggregate_type
    uuid aggregate_id
    string event_type
    jsonb payload
    uuid correlation_id
    uuid causation_id
    timestamptz created_at
    timestamptz published_at
    int attempt_count
  }
  FULFILLMENT_NODES {
    uuid id PK
    string name
    float latitude
    float longitude
    int capacity_per_day
    int current_backlog
    boolean active
  }
  INVENTORY_STOCK {
    string sku PK
    uuid node_id PK,FK
    int available_qty
    int reserved_qty
    int committed_qty
    int reorder_threshold
    int version
    timestamptz updated_at
  }
  INVENTORY_RESERVATIONS {
    uuid id PK
    uuid order_id FK
    string sku
    uuid node_id FK
    int qty
    string status
    timestamptz expires_at
    timestamptz created_at
  }
  SAGA_INSTANCES {
    uuid id PK
    uuid order_id FK
    uuid correlation_id
    string current_step
    string status
    int attempt_count
    timestamptz next_retry_at
    string last_error
    timestamptz created_at
    timestamptz updated_at
  }
  DEAD_LETTER_EVENTS {
    uuid id PK
    uuid original_event_id
    string event_type
    string failed_consumer
    string error_type
    string error_message
    int attempt_count
    jsonb payload
    timestamptz first_failed_at
    timestamptz last_failed_at
    timestamptz replayed_at
  }
  PROCESSED_EVENTS {
    string consumer_name PK
    uuid event_id PK
    timestamptz processed_at
  }
  USERS {
    uuid id PK
    string email
    string password_hash
    string role
    timestamptz created_at
  }
  AUDIT_LOG {
    uuid id PK
    uuid actor_user_id FK
    string action
    string target_type
    uuid target_id
    jsonb metadata
    timestamptz created_at
  }
```

## Notes on key tables

- **`orders.version`** — optimistic concurrency column (ADR 0002). Every
  update does `UPDATE orders SET ..., version = version + 1 WHERE id = :id AND
  version = :expected_version`; zero rows affected means a concurrent writer
  won and the caller retries or fails with 409.
- **`inventory_stock`** — primary key is `(sku, node_id)`. Reservation is a
  single transaction: `SELECT ... FOR UPDATE` on the row, check
  `available_qty >= requested_qty`, then `UPDATE available_qty -=, reserved_qty
  +=` in the same transaction (ADR 0002). `inventory_stock.version` is kept
  too, for audit/debugging, but the lock — not the version check — is what
  prevents overselling.
- **`idempotency_keys`** — checked and written in the same transaction as order
  creation. A retried request with the same key and an identical
  `request_hash` (SHA-256 of the normalized request body) returns the stored
  response verbatim. Same key with a different hash is a `409 Conflict`
  ("idempotency key reused with a different payload"). Rows expire (default
  24h) to bound table growth; expiry does not affect already-completed orders.
- **`outbox_events`** — written in the same DB transaction as the business
  state change it announces (this is what makes "state change + event" atomic
  without two-phase commit across Postgres and Redpanda). The Outbox Relay
  polls `WHERE published_at IS NULL ORDER BY created_at`, publishes, then
  marks `published_at`. `attempt_count` backs its own retry/backoff.
- **`saga_instances`** — one row per order per active saga run; `current_step`
  and `status` let the orchestrator resume a saga after a crash by reading
  this table on startup, rather than relying on in-memory state.
- **`processed_events`** — the idempotent-consumer ledger referenced in
  `docs/event-catalog.md`; composite PK `(consumer_name, event_id)` makes a
  duplicate delivery a no-op insert-conflict rather than a re-applied side effect.

## Cross-service reference integrity

`orders.assigned_node_id` and `inventory_reservations.node_id` reference
`fulfillment_nodes.id`, and `inventory_reservations.order_id` references
`orders.id` — but Inventory and Order are separate services/schemas in this
design, so these are **not** enforced as live SQL foreign keys across service
boundaries; they are validated by (a) application-level checks at write time
and (b) the referential-integrity data-quality check in
`docs/data-pipeline.md` / `docs/testing-strategy.md`, which reconciles Gold
datasets against expected ID spaces.
