# Test Results

Last updated: 2026-07-24 (Phase 2 complete).

This file is updated after every phase with real output from real commands;
no number here is ever estimated or invented (see `RISKS.md` #4).

## Format

Each phase appends a dated section with:
- The exact command(s) run (`pytest`, `docker compose run ...`, etc.)
- Pass/fail counts and coverage percentage, pasted from actual output
- Any known-excluded lines/files and why
- Load-test results (when applicable): p50/p95/p99 latency, throughput,
  error rate, from an actual local run, with the exact load profile used

## History

### 2026-07-23 — Phase 1: Core domain

Commands run (via `docker compose run --rm <service> pytest -q --cov=app
--cov-report=term-missing`, each against its own `*_test` Postgres database):

**order-service** — 21 passed, 0 failed, 96% coverage (337 stmts, 14 missed).
Missing lines are `app/db.py` (the `get_db` generator's teardown path, only
exercised under real ASGI request/response lifecycle, not the test session
fixture) and a couple of unreached branches in `app/routes.py` /
`app/service.py` for error paths not currently hit by a dedicated test.

**inventory-service** — 9 passed, 0 failed, 95% coverage (345 stmts, 17
missed). Includes the two concurrency tests described below. Missing lines
are the same `app/db.py` teardown path plus a couple of unreached error
branches in `app/routes.py`/`app/stock.py`.

**api-gateway** — 9 passed, 0 failed, 93% coverage (132 stmts, 9 missed).
Missing lines are mostly alternate proxy-route error branches not covered by
a dedicated test yet.

**Total: 39 passed, 0 failed** across the three service suites.

Concurrency tests (the core claim of ADR 0002), run against a real
Postgres, each attempt on its own DB connection/session:
- `test_concurrent_reservations_for_last_unit_exactly_one_succeeds`: 10
  concurrent threads race to reserve 1 unit of stock — exactly 1 succeeds, 9
  correctly rejected, final ledger `available_qty=0, reserved_qty=1`.
- `test_concurrent_reservations_exactly_consume_multi_unit_stock`: 10 threads
  race for 5 units — exactly 5 succeed, final ledger `available_qty=0,
  reserved_qty=5`.

End-to-end acceptance check (real `docker compose up`, all 4 containers
healthy, verified via `curl` against the running stack — not just unit
tests):
- Created an order through the API Gateway (`POST /api/orders`) — `201`,
  state `CREATED`.
- Resubmitted the identical request with the same `Idempotency-Key` — `201`
  with the *same* order `id`, proving idempotent replay.
- Cancelled the order (`CREATED -> CANCELLED`, valid transition) — `200`.
- Cancelled it again (`CANCELLED -> CANCELLED`, invalid transition) — `409`
  with `error_code: conflict`.

Lint/format: `ruff check .` — all checks passed. `ruff format --check .` —
50 files already formatted, 0 remaining.

**Bugs found and fixed during this test pass** (see `DECISIONS.md` for the
full writeup): a Docker entrypoint bug that silently ignored `docker compose
run`'s command override and started the API server instead of running
tests; a test-only thread-safety bug in the concurrency test harness (shared
ORM object accessed from multiple threads); a real header-duplication bug in
the gateway's proxy layer (`X-Correlation-ID` sent as two header lines,
joined into one comma-separated value on receipt); and two test-isolation
bugs in the gateway suite (a `setdefault` that a real compose-injected env
var silently defeated, and a shared in-process rate-limit counter leaking
state between test functions).

### 2026-07-24 — Phase 2: Event platform

Commands run (via `docker compose run --rm <service> pytest -q --cov=app
--cov-report=term-missing` against each service's `*_test` database, and
`docker run --rm ... pytest --cov=event_contracts` for the shared package):

**event-contracts** — 21 passed, 0 failed, 90% coverage (181 stmts, 19
missed — mostly `kafka.py`'s real-Kafka-client code paths, which are
exercised for real in the compose smoke test below, not in these
no-broker-needed unit tests).

**order-service** — 34 passed, 0 failed, 91% coverage (492 stmts, 43
missed). 13 new tests since Phase 1: the `order.created -> order.validated`
consumer (idempotent redelivery, no-op on an order that already moved on),
the generic `/orders/{id}/transition` endpoint (valid/invalid transitions,
stale version, `FULFILLMENT_ASSIGNED` requiring `node_id`), and the outbox
relay (publish, backoff-on-failure, skip-not-yet-due, skip-already-published).

**inventory-service** — 16 passed, 0 failed, 93% coverage (435 stmts, 31
missed). 7 new tests: `GET /fulfillment-nodes`, `POST /stock/check`
(sufficient / shortfall / unknown-SKU), and the outbox relay (same 4 cases
as order-service's).

**fulfillment-orchestrator** — 27 passed, 0 failed, 65% coverage (700
stmts, 247 missed — `clients.py`, `main.py`, `routes.py`, `schemas.py`,
`outbox_relay.py` are exercised over real HTTP/Kafka in the compose smoke
test, not unit tests, which use hand-written fake clients instead of
respx-mocking two separate service URLs). Covers: node-scoring formula
(single-candidate edge case, closer-wins, backlog-wins, determinism),
the payment simulator (decline / persistent-timeout / recover-on-retry /
purity), the generic backoff-with-jitter retry helper (succeeds first try,
retries-then-succeeds, exponential+capped+jittered delays, non-retryable
exceptions propagate immediately, exhaustion), the saga happy path
(including node-fallback on a forced reservation-time rejection and
partial-reservation rollback across a two-item order), saga failure paths
(no node has stock, payment hard-decline compensation, payment
retry-exhaustion compensation, payment retry-recovery, cancellation racing
a running saga), idempotent redelivery of `order.validated`, and
poison-message DLQ routing + replay.

**api-gateway** — 9 passed, 0 failed, 93% coverage (unchanged from Phase 1).

**Total: 107 passed, 0 failed** across the five suites (21 + 34 + 16 + 27 + 9).

Lint/format: `ruff check .` — all checks passed. `ruff format --check .` —
91 files already formatted, 0 remaining.

**Real bugs found and fixed during this test pass** (full writeup in
`DECISIONS.md`):
- **Node-scoring divide-by-max bug**: a lone (or all-tied) candidate scored
  its distance/delivery components as `0.0` (worst) instead of `1.0` (best,
  trivially, as the only option) — `1 - value/max(value)` degenerates to 0
  whenever a value equals the max, which is *always* true for a singleton
  set. Fixed with proper min-max normalization (range `== 0` → `1.0` for
  every candidate). Caught by
  `test_single_candidate_scores_perfectly_on_every_relative_component`
  before it shipped — see ADR 0010.
- **Alembic vs. test-conftest schema management collision**: Phase 1's test
  fixtures used `Base.metadata.drop_all`/`create_all` directly, bypassing
  Alembic; Phase 1's entrypoint fix (in the previous phase) made
  `alembic upgrade head` run unconditionally before every test invocation.
  Combined, this left the `*_test` databases with an `alembic_version` row
  claiming migration `0001` applied while the actual tables had been dropped
  by the previous test session's teardown — so Phase 2's new migration
  (`0002`, adding `outbox_events.next_attempt_at`) tried to `ALTER TABLE` a
  table that didn't exist. Fixed by dropping `create_all`'s companion
  `drop_all` from every service's test fixtures (truncate instead of drop,
  never touching Alembic's bookkeeping) and manually repairing the
  already-desynced test databases once.
- Two trivial test-authoring bugs caught immediately by the first run:
  outbox-relay tests omitted the required `correlation_id` column on a
  hand-built `OutboxEvent` row (`NotNullViolation`), and compared a
  publish-call's key against a plain string when `publish_envelope` encodes
  it to `bytes` before handing it to the Kafka client.
- `api-gateway` had no Docker healthcheck defined since Phase 1 (the other
  three FastAPI services do) — invisible until the Phase 2 compose smoke
  test's health-wait loop timed out on a service that was actually running
  fine. Added the same healthcheck pattern used by the other services.

**Compose smoke test** (`make smoke` / `scripts/compose_smoke_test.sh`) —
brings up the entire real stack (Postgres, Redpanda, all three APIs, both
outbox relays, the order-validator consumer, the saga consumer) and:
- Seeded a fulfillment node + stock via the Inventory Service.
- Created a real order through the API Gateway; polled until the saga
  carried it through `CREATED -> VALIDATED -> INVENTORY_PENDING ->
  INVENTORY_RESERVED -> FULFILLMENT_ASSIGNED -> PROCESSING -> SHIPPED`.
  **PASS** — reached `SHIPPED`, `saga_instances.status = COMPLETED`, 0 dead
  letters, stock correctly decremented (`10 -> 8` for a 2-unit order).
- Separately, live-tested the compensation path: an order for
  `SKU-PAYMENT-DECLINE` reached `FAILED`, its `saga_instances` row shows
  `failed_step: AUTHORIZE_PAYMENT`, `compensations_applied` released the
  reservation, and the inventory row was actually restored
  (`available_qty` back to 5, `reserved_qty` back to 0) — confirmed via
  direct `GET /stock/...` against the live inventory-service, not inferred.
- Confirmed `GET /dead-letters` stayed empty across both live runs.

### 2026-07-24 — Phase 3: Observability

Commands run (via `docker run --rm ... mypy`, `docker compose run --rm
<service> pytest --cov=app --cov-report=term-missing` against each
service's `*_test` database, and `docker run --rm ... pytest
--cov=event_contracts` for the shared package):

**Type checking** (`make typecheck` — mypy 1.11.2, `--ignore-missing-imports`,
one invocation per service so each service's identically-named `app`
package isn't treated as a duplicate module): all five packages pass clean
— `event_contracts` (8 files), `order-service/app` (14 files),
`inventory-service/app` (14 files), `fulfillment-orchestrator/app` (18
files), `api-gateway/app` (7 files). Two real findings fixed: a custom
Prometheus collector (`DBPoolCollector`) didn't formally inherit from
`prometheus_client`'s `Collector` ABC; and a redundant/invalid inline type
annotation on a non-`self` attribute assignment
(`app.state.rate_limit_hits: dict[...] = ...`) in api-gateway's `main.py`
— Phase 1 code, fixed as a zero-behavior-change annotation removal. One
suppressed with a scoped `# type: ignore[arg-type]` and an explanatory
comment: SQLAlchemy's own stub for `Mutable.as_mutable` only declares the
`TypeEngine` *instance* form, but passing the class (`JSONB`, not
`JSONB()`) is the documented, runtime-supported idiom — a stub gap, not a
real bug, in Phase 2's `fulfillment-orchestrator/app/models.py`.

**event-contracts** — 37 passed, 0 failed, 87% coverage (321 stmts, 41
missed — mostly `kafka.py`'s real-Kafka-client code paths and a few
unreached tracing/logging edges, exercised for real in the compose smoke
test, not these no-broker-needed unit tests). 11 new tests since Phase 2:
`logging_setup.py`'s `JsonFormatter` (valid JSON, correlation ID
included/null, extra fields, exception rendering), `metrics_setup.py`'s
`MetricsMiddleware`/`metrics_response`/`DBPoolCollector`/`kafka_stats_callback`,
`tracing_setup.py`'s traceparent capture/round-trip, and `kafka.py`'s
`run_consume_loop` gained a correlation-ID-set-and-cleared test and a
retry/dead-letter-counter-increments test.

**order-service** — 34 passed, 0 failed, 91% coverage (525 stmts, 48
missed — same shape as Phase 2, plus the outbox relay's new tracing-span
branches and the validator consumer's metrics-server startup path, neither
exercised by no-broker unit tests).

**inventory-service** — 18 passed, 0 failed, 93% coverage (469 stmts, 33
missed). 2 new tests: `app/metrics.py`'s
`INVENTORY_RESERVATION_CONFLICTS_TOTAL` increments on a real 409, and the
`GET /metrics` route exposes Prometheus text format.

**fulfillment-orchestrator** — 29 passed, 0 failed, 61% coverage (762
stmts, 294 missed — `main.py`/`routes.py`/`schemas.py`/`outbox_relay.py`/
`middleware.py` are exercised over real HTTP/Kafka in the compose smoke
test, same Phase 2 pattern). 2 new tests: `app/metrics.py`'s
`SAGA_DURATION_SECONDS` observes a real positive duration with the
`completed` label on a successful saga and the `failed` label on a
declined-payment saga.

**api-gateway** — 9 passed, 0 failed, 93% coverage (unchanged from Phase
1/2 — no new gateway-specific tests this phase; its metrics/tracing wiring
is exercised end-to-end in the compose smoke test below).

**Total: 127 passed, 0 failed** across the five suites (37 + 34 + 18 + 29 + 9).

Lint/format: `ruff check .` — all checks passed (after `ruff check --fix`
resolved 9 import-ordering findings — `event_contracts` imports weren't
grouped consistently across the newly-touched files). `ruff format --check
.` — 102 files formatted, 0 remaining (after `ruff format .` reformatted 4
files this phase touched).

**Real bugs found and fixed during this test pass** (full writeup in
`DECISIONS.md`):
- A custom `prometheus_client` collector (`DBPoolCollector`) wasn't
  registered as a real `Collector` subclass — worked at runtime (Python
  duck-typing), but is exactly the kind of thing a first real type-check
  pass exists to catch before it silently drifts from the library's actual
  interface.
- `scripts/compose_smoke_test.sh` used hardcoded values
  (`smoke-test-node`, `SKU-SMOKE`, `smoke@example.com`) that are fine
  against a fresh `docker compose up -d -v` volume but violate real unique
  constraints (`fulfillment_nodes.name`, `customers.email`) on any
  re-run against a persistent dev database — caught by actually re-running
  `make smoke` twice in this session rather than trusting a single pass.
  Fixed by suffixing all three with a per-run random ID, same pattern the
  script already used for `customer_id`/`Idempotency-Key`.
- `event-contracts`' own test suite silently depended on `httpx` (via
  `starlette.testclient`, used by the new `MetricsMiddleware` test)
  without declaring it — passed locally by accident wherever httpx
  happened to already be installed, failed clean in a fresh container.
  Fixed by adding it to `make test-contracts`'s ad hoc pip install, same
  place `pytest`/`pytest-cov` already live (event-contracts' `pyproject.toml`
  intentionally lists only real runtime dependencies).

**Compose smoke test** (`make smoke` / `scripts/compose_smoke_test.sh`) —
brings up the entire real stack including the new observability services
(Jaeger, OTel Collector, Prometheus, Grafana — 17 containers total) and:
- Ran the full Phase 2 order-lifecycle assertions unchanged: order reached
  `SHIPPED`, saga `COMPLETED`, 0 dead letters, stock correctly decremented.
- **Traces**: queried Jaeger's API for each of `api-gateway`,
  `order-service`, `inventory-service`, `fulfillment-orchestrator` —
  real traces present for all four. Manually inspected one full trace
  (`0e2292f36a0af1ce302787ab1468f55f`) end-to-end: a single trace ID
  covers `api-gateway`'s `POST /api/orders`, `order-service`'s handler,
  `order-service`'s own `publish order.created` / `consume order.created`
  / `publish order.validated` (its internal validator consumer),
  `fulfillment-orchestrator`'s `consume order.validated` and every
  subsequent saga step (REST calls to order-service and
  inventory-service — node scoring, stock checks, reservation, status
  transitions), all the way to `publish inventory.reserved` and `publish
  order.shipped` — confirming the envelope's `trace_context.traceparent`
  round-trip across the Kafka boundary actually works, not just in unit
  tests with an in-memory exporter.
- **Metrics**: queried Prometheus's `/api/v1/targets` — all 10 scrape
  targets (4 FastAPI services + 5 background workers + Prometheus itself)
  report `health: up`. Queried `sum(http_requests_total)` — real nonzero
  value (142 at the time of the run). Spot-checked `kafka_consumer_lag` (5
  series), `saga_duration_seconds_count` (1 series, the completed saga
  above), `db_pool_checked_out_connections` (3 series, one per
  stateful service).
- **Grafana**: `GET /api/health` OK; `GET /api/datasources/uid/prometheus`
  confirms the provisioned Prometheus datasource is live; `GET
  /api/search?query=OmniFlow` finds the provisioned "OmniFlow Overview"
  dashboard.
- Scanned every background worker's logs plus the OTel Collector's logs
  for errors/exceptions/warnings after the full run — none found.
