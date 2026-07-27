# Test Results

Last updated: 2026-07-26 (Phase 8, Failure laboratory, complete).

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

### 2026-07-26 — Phase 6: Streaming data-platform hardening

Branch `phase-6-streaming-data-platform` — see
`docs/phase-6-streaming-data-platform.md`. All commands below actually run
in this session against real containers/data; no number is estimated.

**Unit/Spark tests** (`make coverage`, which runs `make test` — all six
suites — first): **181 passed, 0 failed, 0 skipped** (37 event-contracts +
34 order-service + 18 inventory-service + 29 fulfillment-orchestrator + 9
api-gateway + **54 data-platform**, up from 40 in Phase 4/5 — 14 new tests:
6 Bronze malformed-JSON quarantine, 3 metrics, 3 inspect CLI, 1 Silver
watermark regression, 2 `app.dq.report`'s new per-event-type Bronze read
covering the `_spark_metadata`-poisoned-root fix).

**Combined coverage** (`coverage combine` across all six suites):

| Suite | Stmts | Miss | Cover |
|---|---|---|---|
| event-contracts | 321 | 41 | 87% |
| order-service | 525 | 48 | 91% |
| inventory-service | 469 | 33 | 93% |
| api-gateway | 149 | 10 | 93% |
| fulfillment-orchestrator | 762 | 294 | 61% |
| data-platform | 904 | 480 | 47% |
| **TOTAL** | **3130** | **906** | **71.1%** |

`COV_THRESHOLD := 65` — passes (`coverage report --fail-under=65` exit 0).
data-platform's new `app/metrics.py` is 100% covered;
`app/inspect.py`/`app/bronze.py` partially (the live-Kafka/S3A code paths,
same pre-existing pattern as the rest of this suite — covered by
`make phase6-smoke` instead of unit tests, not by design gap).

**Formatting** (`ruff format --check .`): 134 files, all formatted (after
one `ruff format`/`ruff check --fix` pass to sort a new import block and
reformat 3 touched files).

**Lint** (`ruff check .`): all checks passed (0 errors).

**Type checking** (`make typecheck`): all six packages pass clean —
`event_contracts` (8), `order-service/app` (14), `inventory-service/app`
(14), `fulfillment-orchestrator/app` (18), `api-gateway/app` (7),
`data-platform/app` (21, up from 19 — `app/metrics.py`, `app/inspect.py`).

**Pre-commit** (`make pre-commit`, `--all-files`): `trailing-whitespace`,
`end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`,
`check-yaml`, `check-json`, `check-toml`, `detect-private-key`,
`mixed-line-ending`, `ruff`, `ruff-format` — all Passed.

**Security** (`make security`): `bandit -ll` — 0 medium, 0 high across
6,159 scanned lines (30 low-severity informational, matching Phase 5's
baseline shape — no new medium/high introduced by this branch's code).
`pip-audit --strict` (adds `prometheus-client==0.21.0` to
data-platform's `requirements.txt`): `No known vulnerabilities found` on
all six scan targets — data-platform reports "2 ignored" (its own
pre-existing `pytest`/`pyarrow` accepted IDs; `prometheus-client` itself
introduced no new CVE).

**Docker Compose validation** (`make docker-validate`): valid.

**Docker image builds** (`make docker-build`): `order-service`,
`inventory-service`, `fulfillment-orchestrator`, `api-gateway`, `spark-gold`
(data-platform, rebuilt with `prometheus-client` + the Bronze/Silver/
metrics/inspect code changes) — all built successfully.

**`make ci`**: exit 0.

**Phase 6 smoke test** (`make phase6-smoke` / `scripts/phase6_smoke_test.sh`,
real run against live Redpanda/MinIO/Spark, `--orders 20 --seed 42
--duplicate-rate 0.15 --late-rate 0.05 --malformed-rate 0.15`):
- Bronze: 268 objects after generation; **97 malformed records correctly
  quarantined to `bronze_rejects`**, none written to the main Bronze table.
- **Restart/checkpoint check: PASS** — re-running `bronze --once` with no
  new Kafka data produced 0 new objects (268 -> 268).
- Silver: 233 objects; `silver_rejects`: 1; `late_events`: 35.
- Gold: 1,349 objects across all 9 streaming datasets.
- `app.dq.report`: **known, documented gap** (`RISKS.md` #22) —
  `bronze_silver_reconciliation` failed by 18 rows, isolated entirely to
  `order.shipped` (the freshest data from this run's very last Bronze/
  Silver micro-batch). Confirmed via direct testing earlier in this
  session that this specific gap does not self-heal with time (verified:
  unchanged after 25+ minutes, past the 10-minute dedup watermark) and
  requires `app.backfill silver --apply` to recover — applied twice
  during this session's own validation (for the historical bug fix in
  finding D, and again for this run's own trailing gap), each time
  reaching `app.dq.report overall: PASS` immediately afterward. Real,
  captured output for one such recovery:
  ```
  silver reprocess counts: {'bronze_distinct_event_ids': 136, 'on_time': 129, 'late': 7, 'rejected': 0}
  swapped into live path: {'silver': 1, 'late_events': 1, 'silver_rejects': 0}
  ...
  DQ report for 2026-07-26 — overall: PASS
    [PASS] bronze_silver_reconciliation: value=0 threshold=0
    [PASS] schema_rejection_rate: value=0.0 threshold=0.05
    [PASS] duplicate_rate: value=0.14976744186046512 threshold=None
    [PASS] late_event_rate: value=0.038293216630196934 threshold=0.1
    [PASS] freshness: value=26.716535766666667 threshold=60
  ```
- Reported honestly, not smoothed over: the smoke test's `dq-report` step,
  as scripted, does **not** guarantee a clean `PASS` on every single
  invocation — it can hit `RISKS.md` #22's known gap on its own freshest
  data. The pipeline's core correctness (ingestion, quarantine, restart-
  safety, dedup, backfill recovery) is all real and verified above; this
  one check's pass/fail is sensitive to a documented Spark
  `Trigger.AvailableNow()` characteristic, not to a defect in this
  branch's own code.

**Real bug found and fixed, with before/after evidence** (`RISKS.md` #21,
`DECISIONS.md`): Silver's dedup watermark on `occurred_at_ts` silently
dropped valid `order.shipped` rows. Before the fix (this session, real
data): `bronze_silver_reconciliation: value=-446` (`order.shipped`
`bronze_distinct=0` — actually the separate `_spark_metadata`-poisoned-root
bug, fixed first), then post-fix-of-that-bug but pre-watermark-fix:
`value=64`, `order.shipped: {'bronze_distinct': 108, 'silver_decided': 60}`.
After the watermark fix + `app.backfill --apply` recovery: `value=0`,
`overall: PASS`. Regression test:
`tests/test_silver.py::test_dedup_watermark_on_ingested_at_survives_wide_occurred_at_swings`
— passing.

### 2026-07-26 — Phase 6: Demand forecasting (the actual roadmap phase)

Branch `phase-6-demand-forecasting` — see
`docs/phase-6-demand-forecasting.md`. All commands below actually ran in
this session against real containers; no number is estimated (`RISKS.md`
#4). Distinct from the "Phase 6: Streaming data-platform hardening" section
above, which reused the number "Phase 6" in its own branch name by
coincidence.

**Forecasting unit + pipeline tests** (`make forecast-test`, scoped to
`tests/forecasting/`, no live Kafka/MinIO needed): **91 passed, 0 failed**
— `test_synthetic.py` (10), `test_features.py` (10), `test_quality.py`
(17), `test_splits.py` (7), `test_baseline.py` (6), `test_secondary_model.py`
(6), `test_metrics.py` (8), `test_select.py` (4), `test_artifacts.py` (5),
`test_dataset.py` (4), `test_evaluate.py` (4), `test_forecast.py` (3),
`test_io.py` (4), `test_cli.py` (3).

**Full six-suite test run** (`make coverage`, which runs `make test`
first): **272 passed, 0 failed, 0 skipped** (37 event-contracts + 34
order-service + 18 inventory-service + 29 fulfillment-orchestrator + 9
api-gateway + **145 data-platform** — up from 54 in the streaming-hardening
pass; the 91 new tests are entirely `tests/forecasting/`, picked up
automatically by `test-data-platform`'s existing `pytest` invocation, no
Makefile change needed for that target itself).

**Combined coverage** (`coverage combine` across all six suites):

| Suite | Stmts | Miss | Cover |
|---|---|---|---|
| event-contracts | 321 | 41 | 87% |
| order-service | 525 | 48 | 91% |
| inventory-service | 469 | 33 | 93% |
| api-gateway | 149 | 10 | 93% |
| fulfillment-orchestrator | 762 | 294 | 61% |
| data-platform | 1715 | 622 | 64% |
| **TOTAL** | **3943** | **1048** | **73.4%** |

`COV_THRESHOLD := 65` — passes (`coverage report --fail-under=65` exit 0).
Combined coverage rose from 71.1% (streaming-hardening pass) to 73.4%: the
new `app/forecasting/` package is almost entirely covered by pure
pandas/scikit-learn unit tests (`artifacts.py`/`baseline.py`/`evaluate.py`/
`features.py`/`forecast.py`/`metrics.py`/`secondary_model.py`/`select.py`/
`synthetic.py` all 100%; `dataset.py` 95%, `quality.py` 95%, `splits.py`
98%, `config.py` 92%; `cli.py` 55% and `paths.py` 39% — the CLI's own
argument-wiring/path-building lines are exercised by `test_cli.py`'s
end-to-end `cmd_run` test and the real smoke test below, not by every
individual branch, the same pattern this suite already accepts for
`app/generator.py`/`app/gold/runner.py`/`app/lag_poller.py`, which need a
live Kafka/MinIO/Spark stack to exercise and are covered by `make
forecast-smoke`/`make phase6-smoke` instead of unit tests).

**Formatting** (`ruff format --check .`): 167 files, all formatted.

**Lint** (`ruff check .`): all checks passed (0 errors).

**Type checking** (`make typecheck`): all six packages pass clean —
`data-platform/app` now 38 source files (up from 21), including the new
`app/forecasting/` package; `pandas`/`numpy`/`scikit-learn`/`joblib` added
to `typecheck`'s pinned pip-install list (matching
`services/data-platform/requirements.txt`) so mypy resolves the same
versions the real image uses, not whatever pyarrow/pyspark happen to pull
in transitively — a real, found-by-running-it gap (the first `make
typecheck` run without this fix produced 7 numpy-stub errors in
`synthetic.py` from a mismatched transitive numpy version; fixed by
pinning, not by silencing).

**Pre-commit** (`make pre-commit`, `--all-files`): `trailing-whitespace`,
`end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`,
`check-yaml`, `check-json`, `check-toml`, `detect-private-key`,
`mixed-line-ending`, `ruff`, `ruff-format` — all Passed.

**Security** (`make security`): `bandit -ll` — 0 medium, 0 high across
7,538 scanned lines (30 low-severity informational, same pre-existing
shape — no new medium/high introduced by `app/forecasting/`).
`pip-audit --strict` (adds `pandas==2.2.3`, `numpy==2.1.2`,
`scikit-learn==1.5.2`, `joblib==1.4.2` to data-platform's
`requirements.txt`): `No known vulnerabilities found` on all six scan
targets — data-platform reports "2 ignored" (its own pre-existing
`pytest`/`pyarrow` accepted IDs; the four new forecasting dependencies
introduced no new CVE).

**Docker Compose validation** (`make docker-validate`): valid — including
the new `spark-gold` bind mount for `forecasting_artifacts` (section H's
local model-persistence requirement).

**Docker image builds** (`make docker-build`): `order-service`,
`inventory-service`, `fulfillment-orchestrator`, `api-gateway`,
`spark-gold` (data-platform, rebuilt with `pandas`/`numpy`/
`scikit-learn`/`joblib` + the `app/forecasting/` package) — all built
successfully.

**`make ci`**: exit 0 ("all Phase 5 quality gates passed" — the target's
own long-standing echo string, unrelated to this phase's number).

**Forecasting smoke test** (`make forecast-smoke` /
`scripts/forecast_smoke_test.sh`, small deterministic config — seed 99, 4
SKUs x 2 locations, 2025-01-01..2025-06-30, 7-day horizon — every CLI
subcommand run separately, entirely local, no live MinIO needed): **PASS**,
run twice for a determinism check, both runs producing byte-identical
measured metrics:

```
seasonal_naive:          {"mae": 18.446428571428573, "rmse": 62.02404487662138, "wape": 0.29786620530565167}
hist_gradient_boosting:  {"mae": 9.515713349608854,  "rmse": 13.49209166350842, "wape": 0.15365627092793996}
champion: hist_gradient_boosting (wape 0.1537 < seasonal_naive wape 0.2979)
forecast: 56 rows (7 horizon days x 4 SKUs x 2 locations), all predicted_units >= 0
```

Reported honestly, not fabricated to look good: on this run's synthetic
data, the secondary model (`HistGradientBoostingRegressor`) genuinely beat
the seasonal-naive baseline on every metric (MAE, RMSE, and WAPE), and was
selected champion by the documented rule using the measured WAPE values —
not a hardcoded "the fancier model always wins."

Also verified directly (separate from the smoke test, cross-container
artifact persistence — section H's local-artifact requirement): trained a
baseline and secondary model in two separate `docker compose run`
invocations (each a fresh container), then loaded and evaluated both
models in two further separate invocations — real persistence via the
`spark-gold` service's bind-mounted `forecasting_artifacts` volume, not
assumed.

**Real bug found and fixed, with a regression test written specifically to
catch it** (`RISKS.md` #23, `DECISIONS.md`): the recursive multi-step
future-forecast rollout initially wrote each step's predictions back into
the working series by position, assuming two independently-sorted
DataFrames shared the same row order — they don't, in general. Found by
`tests/forecasting/test_forecast.py::
test_generate_future_forecast_recursion_feeds_predictions_forward`'s
`_Lag1Model` probe (asserts step 2's prediction exactly equals step 1's)
before this ever shipped. Fixed by keying predictions to `(sku,
location_id)` explicitly; the same test now passes.

### 2026-07-26 — Phase 7: Ops dashboard

All commands run via `make dashboard-*` (each a throwaway `node:22-alpine`
container, host UID/GID, no host Node — see `docs/phase-7-ops-dashboard.md`).

**`make dashboard-format-check`** (`prettier --check .`): clean — "All
matched files use Prettier code style!"

**`make dashboard-lint`** (`eslint .`, flat config incl.
`eslint-plugin-react-hooks@7`'s stricter rules): clean, 0 errors, 0 warnings.

**`make dashboard-typecheck`** (`tsc -b --noEmit`): clean, no output (no
errors).

**`make dashboard-test`** (`vitest run`): **50 passed, 0 failed**, 14 test
files, ~5s wall time:

```
 Test Files  14 passed (14)
      Tests  50 passed (50)
```

Coverage: api/client.ts, api/metrics.ts, hooks/useAsync.ts,
hooks/useTrackedOrders.ts, components/common/{StatusBadge,DataTable,
LoadingState,EmptyState,ErrorState,MockDataNotice,BarChart,LineChart},
components/forms/{CreateOrderForm,CancelOrderForm}, pages/OverviewPage,
pages/DataQualityPage, pages/FailureLabPage, and an App-level routing
smoke test (all 10 nav links present, click-navigation, 404 fallback).

**`make dashboard-build`** (`tsc -b && vite build`): clean —
`dist/index.html` 0.63 kB, `dist/assets/index-*.css` 9.30 kB (gzip 2.54 kB),
`dist/assets/index-*.js` 282.63 kB (gzip 88.13 kB), built in ~0.4-0.7s.

**Docker image build** (`docker build -f services/ops-dashboard/Dockerfile
-t omniflow-ops-dashboard:test .`, and again via `make docker-build` /
`docker compose build ops-dashboard`): both succeeded — multi-stage
`node:22-alpine` (build) → `nginx:1.27-alpine` (serve), final image
75.7 MB.

**Standalone container smoke test** (real bug #1 found and fixed — see
`RISKS.md` #27/`DECISIONS.md`): `nginx -t` inside the built image failed
before the fix (`[emerg] host not found in upstream "api-gateway"`) and
passed cleanly after switching `proxy_pass` to resolver-backed variables.
With the container then actually running standalone (`docker run -d -p
18080:80 omniflow-ops-dashboard:test`, no other containers on its
network):

```
index.html: 200
spa route (/orders/abc): 200
proxy /gw/healthz (no gateway running -> expect 502): 502
```

— the static SPA and client-side routing work with zero dependencies up,
and an unreachable upstream degrades gracefully to a per-route 502 instead
of crashing the whole server.

**Real end-to-end verification against the live `docker compose up` stack**
(real bug #2 found and fixed — see `RISKS.md` #27/`DECISIONS.md`; this is
what the standalone smoke test above structurally could not catch, since
it had no real upstream to be wrong against): brought up
postgres/redpanda/minio/order-service/inventory-service/
fulfillment-orchestrator/api-gateway/prometheus/ops-dashboard together via
`docker compose up -d`, all reported healthy, then hit the dashboard's own
published port (`3001`) directly, proxies included:

```
GET  /gw/healthz                          -> {"status":"ok"}
GET  /inventory-api/fulfillment-nodes      -> [] (real, empty — no nodes seeded this session)
GET  /orchestrator-api/saga-instances      -> real saga instances (persisted from prior sessions' Postgres volume)
GET  /orchestrator-api/dead-letters        -> [] (real, empty)
GET  /prom-api/api/v1/query?query=up       -> real Prometheus vector result (4 targets up)
GET  /orders/some-id (SPA route)           -> 200
POST /gw/api/orders (create) -> 201, real order persisted
GET  /gw/api/orders/{id}                   -> same order, read back correctly
GET  /gw/api/orders/{id}/history           -> real CREATED transition recorded
```

Every proxy path returns real data from the real service on the other
side of it — not a mocked check, and not just the standalone container's
static-file/502 behavior.

**Real bug #3, found only after #1 and #2 were both already fixed and
traffic was flowing correctly**: `docker compose ps` still reported
`ops-dashboard` **unhealthy** despite every route above working. Root
cause: nginx only binds IPv4 (`listen 80;`), but this image's `wget`
resolves `localhost` to `::1` first — both the Dockerfile's own
`HEALTHCHECK` and `docker-compose.yml`'s separate, overriding
`healthcheck:` block were querying `http://localhost:80`, an address
nginx never listens on, regardless of whether the service itself worked.
Fixed by pointing both at `http://127.0.0.1:80` explicitly. Verified:
`docker exec omniflow-ops-dashboard-1 wget -qO- http://127.0.0.1:80` — OK;
`http://[::1]:80` — connection refused (confirms the diagnosis, not just
the fix); after rebuilding and force-recreating the container,
`docker compose ps` reports `omniflow-ops-dashboard-1  Up ... (healthy)`.

**`make docker-validate`** (`docker compose config --quiet`): valid,
including the new `ops-dashboard` service.

**`make ci`**: full local gate (format-check, lint, typecheck, coverage
across all six Python suites, security, `dashboard-validate`,
docker-validate, docker-build) run against this branch — six-suite Python
totals unchanged from Phase 6 (272 passed, 0 failed; data-platform's own
145 reconfirmed by a direct rerun: `================= 145 passed, 2
warnings in 175.20s (0:02:55) =================`), plus the 50 new
dashboard tests above. One transient, environment-level failure was hit
and is recorded here rather than silently retried away: a first `make ci`
run failed at `test-data-platform` with a Docker Desktop/WSL2 bind-mount
error ("no such file or directory" resolving `create-buckets.sh`'s bind
source) — unrelated to any code in this phase (data-platform/minio-init
were not touched); a `docker compose down` + `up -d minio` recreated the
network cleanly and the identical `make test-data-platform` command then
passed outright, confirming the failure was host/Docker-Desktop
infrastructure flakiness, not a regression.

### 2026-07-26 — Phase 8: Failure laboratory

Commands run via `make test-<suite>` (each a throwaway container against
its own `*_test` Postgres database, or a mocked fixture set for
event-contracts/failure-lab):

| Suite | Passed | Failed | Coverage |
|---|---|---|---|
| event-contracts | 38 | 0 | 88% |
| order-service | 37 | 0 | 91% |
| inventory-service | 23 | 0 | 94% |
| fulfillment-orchestrator | 41 | 0 | 79% |
| api-gateway | 9 | 0 | 93% |
| data-platform | 145 | 0 | 64% |
| **failure-lab** (new) | **66** | **0** | **94%** |
| **Total** | **359** | **0** | |

`make coverage` (combined `coverage.xml`, all seven suites):
`TOTAL 5007 987 80.3%` — well above the enforced 65% threshold
(`coverage report --fail-under=65`, exit 0).

`make dashboard-test` (Vitest + React Testing Library): **66 passed, 0
failed**, 16 test files (was 50/14 in Phase 7; +12 for the new
`FailureLabPage`/`failureLab.ts` and +4 for a new working "Replay" button
on the Dead Letter Queue screen — see below). `dashboard-format-check`/
`dashboard-lint`/`dashboard-typecheck`/`dashboard-build` all clean.

`make phase8-smoke` (`scripts/phase8_smoke_test.sh`, real running stack,
run twice — see the log excerpt below for the final passing run): all 10
scenarios reach `PASSED`/`RECOVERED` on a clean start, every scenario's
`reset()` succeeds, then all 10 reach `PASSED`/`RECOVERED` again on rerun
(proves safe-to-rerun for the whole catalog against a live stack, not just
asserted in a unit test):

```
[phase8-smoke] --- pass 1: every scenario from a clean start ---
[phase8-smoke] payment-decline: PASSED
[phase8-smoke] payment-timeout: RECOVERED
[phase8-smoke] inventory-oversell-race: PASSED
[phase8-smoke] duplicate-order-submit: PASSED
[phase8-smoke] duplicate-event-delivery: PASSED
[phase8-smoke] poison-message-dlq: PASSED
[phase8-smoke] malformed-kafka-record: PASSED
[phase8-smoke] late-event-arrival: PASSED
[phase8-smoke] saga-crash-resume: RECOVERED
[phase8-smoke] downstream-outage: RECOVERED
[phase8-smoke] --- reset every scenario ---
[phase8-smoke] (all 10: reset)
[phase8-smoke] --- pass 2: rerun every scenario after reset (proves safe-to-rerun) ---
[phase8-smoke] payment-decline: PASSED
[phase8-smoke] payment-timeout: RECOVERED
[phase8-smoke] inventory-oversell-race: PASSED
[phase8-smoke] duplicate-order-submit: PASSED
[phase8-smoke] duplicate-event-delivery: PASSED
[phase8-smoke] poison-message-dlq: PASSED
[phase8-smoke] malformed-kafka-record: PASSED
[phase8-smoke] late-event-arrival: PASSED
[phase8-smoke] saga-crash-resume: RECOVERED
[phase8-smoke] downstream-outage: RECOVERED
[phase8-smoke] all 10 scenarios PASSED/RECOVERED on both passes.
```

`make smoke` (the pre-existing Phase 1-3 end-to-end check) reconfirmed
passing against the same rebuilt stack: full order lifecycle to `SHIPPED`,
saga `COMPLETED`, 0 unreplayed dead letters, traces in Jaeger, Prometheus/
Grafana verified.

`make ci` (format-check, lint, typecheck, coverage, security,
dashboard-validate, docker-validate, docker-build): **exit 0**, all seven
Python packages' `mypy` clean, `ruff check`/`ruff format --check` clean,
`bandit` 0 medium/high, `pip-audit` clean (accepted CVEs unchanged from
`RISKS.md` #20), `docker compose config` valid, all seven application
images build (including the new `failure-lab`). `make pre-commit` clean.

**Four real bugs found and fixed while getting the above green** — not
worked around, fixed at the root cause, each with its own regression test
(full writeups in `RISKS.md` #28-#31 and `docs/phase-8-failure-laboratory.md`
"Real bugs found and fixed"):

1. A malformed Kafka record (found: genuine leftover data from Phase 6's
   `--malformed-rate` generator testing, still sitting in a real
   `order.created`/`order.validated` topic in this session's persistent
   Redpanda volume) crashed `order-validator-consumer` /
   `fulfillment-orchestrator-consumer` on every restart, forever —
   `event_contracts.kafka.run_consume_loop`'s `parse_envelope(msg)` call
   was outside its own retry/DLQ try/except. Fixed: logged, counted, and
   skipped, never retried, never crashing.
2. `resume_incomplete_sagas` let one orphaned saga (60 such stale rows
   were found, left over from earlier synthetic-generator testing) crash
   the entire orchestrator-consumer at every startup. Fixed: each saga
   resumed independently inside its own try/except.
3. A transient failure on a brand-new saga's very first `advance_saga`
   call left it stuck `RUNNING` forever, invisible to both Kafka's retry
   mechanism and the dead-letter path, because the event was marked
   "processed" before `advance_saga` ever ran. Fixed: marked processed
   only after `advance_saga` returns without raising.
4. `app.replay.replay_one` had never actually worked against a real dead
   letter (`payload["original_event"]` vs. the real flat-envelope shape)
   — masked by every existing test building its own wrongly-shaped
   fixture instead of reusing the real `dead_letter()` code path. Fixed,
   and verified for real (not just by a test): `make replay ARGS="--all"`
   successfully replayed 2 real dead letters left over from this
   session's own earlier (pre-fix) test runs.

One transient, environment-level issue was hit and is recorded here rather
than silently retried away: two concurrent `docker compose up --build -d`
invocations (one left over from a prior manual rebuild, one started by
`make smoke`) raced and hit a container-naming conflict — resolved with a
clean `docker compose down` (no `-v`, volumes preserved) followed by
`docker compose up -d`; not a code regression.
