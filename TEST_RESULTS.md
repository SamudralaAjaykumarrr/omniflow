# Test Results

Last updated: 2026-07-25 (Phase 5, Engineering quality, complete).

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

### 2026-07-25 — Phase 4: Data engineering platform

Commands run (via `docker run --rm ... mypy`, `docker compose run --rm
spark-gold pytest --cov=app --cov-report=term-missing`, and a real `docker
compose up`/`down -v` cycle against MinIO + Redpanda):

**Type checking** (`make typecheck`): all six packages pass clean —
`event_contracts` (8 files), `order-service/app` (14 files),
`inventory-service/app` (14 files), `fulfillment-orchestrator/app` (18
files), `api-gateway/app` (7 files), and (new this phase)
`data-platform/app` (19 files).

**data-platform** — 40 passed, 0 failed, 45% coverage (767 stmts, 423
missed). Missing lines are almost entirely real-client/CLI-entrypoint code
(`app/generator.py`, `app/lag_poller.py`, `app/gold/runner.py`'s `main`,
most of `app/backfill.py`/`app/dq/report.py`'s I/O) exercised for real
against MinIO/Redpanda in this phase's compose verification below, not in
these no-broker-needed unit tests — same pattern every prior phase's
real-Kafka-client code followed. Suites: `test_bronze.py` (3),
`test_silver.py` (11 — parsing, validation incl. the per-row
unknown-schema-version check, normalization, lateness marking, the
on-time/late/invalid split, the real streaming `dropDuplicatesWithinWatermark`
dedup primitive against a file source, and the deadletter
`original_event`-as-nested-JSON regression), `test_gold.py` (9, one per
streaming Gold dataset), `test_dq.py` (12, all five checks plus the report
module's date-partition reader), `test_backfill.py` (4), `test_restart.py`
(1, a real checkpoint-based restart-doesn't-reprocess proof against a file
source).

**Total: 167 passed, 0 failed** across the six suites (37 + 34 + 18 + 29 + 9
+ 40).

Lint/format: `ruff check .` — all checks passed. `ruff format --check .` —
130 files formatted, 0 remaining.

**Real bugs found and fixed during this phase** (full writeup in
`DECISIONS.md`), roughly in the order they surfaced running the real stack
against MinIO with real traffic — none were visible from unit tests alone,
since every one of them is a property of concurrent/real-storage execution:
1. `DeadLetterEventDataV1.original_event` (Phase 2, `event_contracts`) is a
   JSON *object*; Silver's Spark schema for it was `StringType`, so
   `from_json` silently nulled it on every real dead-letter row. Fixed by
   extracting it via `get_json_object` instead.
2. `validate()`'s `unknown_schema_version` check compared the query's own
   static `schema_version` parameter (always a registered value) instead of
   each row's own `schema_version` column — permanently dead code that
   could never fire for a real producer bug. Fixed to check the row's own
   column against the registry.
3. Structured Streaming's file source requires its source path to already
   exist at query-start (`PATH_NOT_FOUND` otherwise) — Silver/Gold crashed
   immediately on a genuinely fresh `docker compose up`, before
   Bronze/Silver had ever written anything. Fixed with a hidden placeholder
   object (`app.s3.ensure_prefix_exists`).
4. Structured Streaming's partition-column auto-discovery resolves once, at
   query-start, from whatever partition directories exist then — a query
   started against an empty path resolves with zero partition columns, and
   the first *real* `date=<Y>` directory appearing afterward broke the
   query with a schema-mismatch assertion. Fixed by declaring `date`
   explicitly in the schema for both Silver's Bronze-read and Gold's
   Silver-read, instead of relying on auto-discovery.
5. 11 concurrent Silver queries (one per event type) all wrote to one
   shared output path with Spark's default rename-based commit protocol —
   their `_temporary` staging directories collided against S3A/MinIO
   (rename there is copy+delete, not atomic), surfacing as a real
   `RemoteFileChangedException` that killed the query. Fixed by giving each
   event type its own distinct output path (Gold's 9 datasets already had
   this; added it for Silver and Silver's batch reprocessing).
6. This MinIO version rejects S3's bulk `DeleteObjects` API
   (`MissingContentMD5`) — `s3fs`'s `rm`/`mv` always route through it even
   for a single key. Fixed `app.backfill`'s swap step to delete via
   `boto3`'s single-object `delete_object` instead.
7. Gold's live streaming queries wrote via `.writeStream.format("parquet")`
   directly, which maintains a `_spark_metadata` sink commit log; any
   metadata-aware batch reader (including a plain `spark.read.parquet()`)
   only sees files recorded there, so `app.backfill`'s swap step wrote real,
   correct files that were invisible to any normal read afterward. Fixed by
   switching Gold to the same `foreachBatch` + plain-write pattern Silver
   already used, which never creates that log.
8. `build_spark_session`'s default was `local[2]`, contradicting ADR 0005's
   own decision to run `local[*]` (all host cores). Under 11 (Silver) or 9
   (Gold) genuinely concurrent streaming queries, Spark's default FIFO job
   scheduler combined with too few cores let some queries starve of
   scheduled time indefinitely, not just lag — order.created's Silver query
   stopped making progress entirely under real generated traffic. Fixed by
   correcting the default to `local[*]` (matching the ADR) and adding
   `spark.scheduler.mode=FAIR`.
9. `check_freshness` subtracted an aware `datetime.now(UTC)` from a naive
   one — Spark's `TimestampType` collects as a naive Python `datetime` even
   under `spark.sql.session.timeZone=UTC`, raising `TypeError` on real
   Bronze data (caught by running the DQ report for real, not by the unit
   tests, which happened not to exercise a real Spark-collected timestamp
   difference against an aware value in this exact way before the fix
   landed).

**Compose verification** (`docker compose up -d --build`, a real MinIO +
Redpanda + Bronze/Silver/Gold/lag-poller stack, `docker compose down -v`
between iterations to prove a genuinely fresh environment starts clean):
- Ran the unchanged Phase 1-3 `make smoke` end-to-end twice against this
  same stack (once before, once after the scheduling fix) — both **PASS**,
  confirming Phase 4's additions don't regress the real order lifecycle,
  traces, or metrics.
- Ran `python -m app.generator --orders 60 --dead-letters 4
  --duplicate-rate 0.1 --late-rate 0.1` against the live stack — published
  398-405 real events per run across 10 of the 11 topics (11th,
  `inventory.low`, is a ~5%-probability event per order and didn't always
  fire).
- **Bronze**: real Parquet under `s3a://omniflow/bronze/event_type=<X>/date=<Y>/`
  for all 11 event types (`order.cancelled` included only via a real Phase
  1 smoke-test cancellation from earlier project history sitting in
  Redpanda's persistent volume, replayed from `startingOffsets=earliest` —
  itself a real, useful confirmation that Bronze correctly replays a
  pre-existing backlog).
- **Silver**: real validated/deduplicated Parquet per event type; 0 rows in
  `silver_rejects` (no schema-invalid rows generated); real rows in
  `late_events` for the events the generator deliberately backdated.
- **Data-quality report** (`python -m app.dq.report`), run against the live
  MinIO data for the current date: **overall PASS** —
  `bronze_silver_reconciliation: 0` (every distinct Bronze `event_id`
  accounted for as on-time, late, or rejected in Silver), `schema_rejection_rate:
  0.0` (threshold 0.05), `duplicate_rate: 0.111` (informational — matches
  the generator's injected 10% duplicate rate), `late_event_rate: 0.094`
  (threshold 0.10), `freshness: ~2.1 minutes` (threshold 60). Report written
  to `s3a://omniflow/dq-reports/date=<today>/report.json`.
- **Backfill/reprocessing** (`python -m app.backfill gold --dataset ...
  --apply`), run for real against live Silver data for all 9 streaming Gold
  datasets — every one produced a real, non-zero row count and a
  successful swap into the live path, subsequently readable:
  `orders_per_minute` (1), `revenue_by_product_location` (59),
  `fulfillment_success_rate` (2), `fulfillment_latency` (2),
  `inventory_reservation_failure_rate` (1), `stockout_frequency` (11),
  `late_order_rate` (2), `product_demand_by_window` (20),
  `dead_letter_volume` (3). The 10th Gold dataset, `consumer_lag`
  (`app.lag_poller`, polling every 15s independent of Spark), had 270 real
  rows.
- Noted, not a bug: the synthetic generator publishes onto the same Kafka
  topics the real `order-service`/`fulfillment-orchestrator` consumers
  subscribe to, so those real consumers also process the synthetic events —
  observed as expected `404 Not Found` responses from `order-service` in
  `fulfillment-orchestrator-consumer`'s logs (the synthetic order IDs don't
  exist in Postgres) and correctly produced zero dead letters. Harmless
  cross-topic noise, not a functional break; documented in `RISKS.md`.

### 2026-07-25 — Phase 5: Engineering quality

Full narrative and rationale: `docs/phase-5-engineering-quality.md`. This
entry is the raw evidence, from a real `make ci` run
(`infra/docker/devtools/Dockerfile` built fresh, six suites executed with
coverage instrumentation, five application images built) — 6m50s wall time.

**Baseline (unchanged from Phase 4, re-verified): 167 passed, 0 failed, 0
skipped** across all six suites (37 event-contracts + 34 order-service + 18
inventory-service + 29 fulfillment-orchestrator + 9 api-gateway + 40
data-platform).

**Combined coverage** (`make coverage`, `coverage combine` across all six
per-service data files, statement coverage — no branch data, since each
service's own container runs pytest-cov without the repo-root
`pyproject.toml` present, so `[tool.coverage.run] branch = true` isn't
active at collection time; documented as a known limitation below):

| Suite | Stmts | Miss | Cover |
|---|---|---|---|
| event-contracts | 321 | 41 | 87% |
| order-service | 525 | 48 | 91% |
| inventory-service | 469 | 33 | 93% |
| api-gateway | 149 | 10 | 93% |
| fulfillment-orchestrator | 762 | 294 | 61% |
| data-platform | 767 | 423 | 45% |
| **TOTAL** | **2993** | **849** | **71.6%** |

`coverage.xml` (Cobertura format, `line-rate="0.7163"`) generated at repo
root by the same run. `COV_THRESHOLD := 65` in the root Makefile — set below
the measured 71.6%, not at it, so one new untested branch doesn't fail CI
outright. The two low outliers are both dragged down by modules that need a
live Kafka/HTTP/Spark stack to exercise, already covered by `make smoke`/the
Phase 4 compose verification instead of unit tests: fulfillment-orchestrator's
`main.py`/`middleware.py`/`routes.py`/`schemas.py`/`outbox_relay.py` (all
0%, FastAPI wiring and the outbox relay loop) and data-platform's
`generator.py`/`gold/runner.py`/`lag_poller.py` (all 0%, CLI entrypoints and
a live-Kafka poller).

**Formatting** (`make format-check`): 130 files, all already formatted.

**Lint** (`make lint`): all checks passed.

**Type checking** (`make typecheck`): all six packages pass clean —
`event_contracts` (8 files), `order-service/app` (14), `inventory-service/app`
(14), `fulfillment-orchestrator/app` (18), `api-gateway/app` (7),
`data-platform/app` (19).

**Pre-commit** (`make pre-commit`, `.pre-commit-config.yaml`, `--all-files`):
`trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`,
`check-added-large-files`, `check-yaml`, `check-json`, `check-toml`,
`detect-private-key`, `mixed-line-ending`, `ruff`, `ruff-format` — all
Passed.

**Security** (`make security`): `bandit -ll` (medium+ confidence/severity
only) — 0 medium, 0 high across 5,878 scanned lines (29 low-severity
informational findings, not blocking). `pip-audit --strict`, real query
against the OSV.dev database — found 14 known CVEs across 4 packages
(`pip`, `pytest`, `pyarrow`, `starlette`) on the initial run; `pip==26.1.2`
pinned in every Dockerfile fixed pip's 5 outright (re-verified: `make test`
still 167/167 passed after the bump). The remaining 9 IDs are accepted and
individually justified in `RISKS.md` #20 (starlette's fixes need a
fastapi major-version bump this codebase can't take in this pass — verified
via `pip install fastapi==0.115.0 starlette==0.40.0` → `ResolutionImpossible`
— pytest's and pyarrow's are both inapplicable to how this codebase actually
uses them). Final `make security` run: `No known vulnerabilities found` on
all six scan targets, `8/8/8/8/2/9` ignored IDs reported inline (visible,
not silently dropped).

**Docker Compose validation** (`make docker-validate`): `docker compose
config --quiet` — valid.

**Docker image builds** (`make docker-build`): `order-service`,
`inventory-service`, `fulfillment-orchestrator`, `api-gateway`, `spark-gold`
(data-platform) all built successfully.

**`make ci`**: exit 0. All of the above, in one real run, in that order.

**Known limitation carried into Phase 6+**: coverage is statement-only, not
branch, for the reason above (each per-service container lacks the repo-root
`pyproject.toml` at collection time). Making branch coverage real would mean
either copying `pyproject.toml` into every service image or passing
`--cov-branch` explicitly to every `pytest` invocation — deferred rather
than done speculatively in this pass; tracked in
`docs/phase-5-engineering-quality.md`.
  cross-topic noise, not a functional break; documented in `RISKS.md`.
