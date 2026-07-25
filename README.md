# OmniFlow

An event-driven retail order/inventory/fulfillment platform demonstrating
production-caliber distributed-systems and data-engineering practice — safe
concurrency, saga orchestration, a real event bus, and a Bronze/Silver/Gold
data pipeline — running entirely on a single machine with no paid cloud
services.

This is an original design. It is not a clone of, and does not use any
proprietary design, branding, or business information from, any real
retailer.

## Current implementation status

**Phases 1-4 of 13 are done and verified** (Phase 5, Data quality, is also
done — folded into Phase 4). **Phases 6-13 have not been started.**

| Done now | Not started yet |
|---|---|
| Core domain (orders, inventory, API gateway) | Demand forecasting |
| Event platform (Redpanda, saga orchestrator, DLQ, replay) | Ops dashboard (React/TypeScript) |
| Observability (structured logs, tracing, metrics, Grafana) | Failure laboratory |
| Data platform (Spark Bronze/Silver/Gold, data quality, backfill) | Security hardening, load testing, CI/CD, Terraform, career docs |

Data quality (checks + report) was originally scoped as its own phase but was
folded into Phase 4, since the Spark plumbing it depends on was already in
place. Full phase-by-phase detail: `PROJECT_STATUS.md`.

## Verified proof points

Every number below comes from a command actually run against this repo (see
`TEST_RESULTS.md`; nothing here is estimated) or from a real
`docker compose up` verified in `PROJECT_STATUS.md`:

- **167 tests passing, 0 failing** across six suites (event-contracts,
  order-service, inventory-service, fulfillment-orchestrator, api-gateway,
  data-platform)
- **23 containers** (full app stack + Redpanda + MinIO + Spark + observability
  stack) running concurrently on one host without OOM
- **11 event types** in the event catalog, each with a schema and a consumer
  idempotency guarantee
- **10 Gold datasets** (9 Spark streaming aggregations + 1 directly-polled
  consumer-lag dataset)
- **Real Kafka → Bronze → Silver → Gold flow verified end-to-end**: synthetic
  traffic generated onto real topics, real Parquet observed at every layer,
  a data-quality report run against live MinIO data (overall PASS), and all
  10 Gold datasets successfully backfilled from real Silver data

## Verified engineering highlights

- **Idempotent APIs**: every consumer dedupes by `event_id`
  (`processed_events`); `POST /api/orders` safely retries via an
  `Idempotency-Key` header — proven with a real duplicate-request test.
- **Two deliberate concurrency strategies** by contention profile: row-level
  locking for hot `inventory_stock` rows, optimistic `version` columns for
  low-contention `orders` ([ADR 0002](docs/adrs/0002-inventory-concurrency-control.md)).
  Verified live: 10 threads racing for 1 unit of stock, exactly 1 succeeds.
- **Real saga compensation**: a live compose run forced a payment decline and
  confirmed the released inventory reservation was actually restored in
  Postgres, not just marked failed.
- **Tracing that survives the Kafka boundary**: one Jaeger trace, manually
  inspected, covers a single order across the gateway, order service, and
  orchestrator's async saga steps.
- **Nine real bugs found and fixed by actually running the system** (Spark
  scheduler starvation, MinIO's bulk-delete rejection, a Structured Streaming
  metadata-visibility gap, and more) — full writeups in `DECISIONS.md`.

## Architecture overview

An API Gateway fronts an Order Service and Inventory Service
(Postgres-backed); a Fulfillment Orchestrator runs the order saga by
consuming events off a Redpanda (Kafka-protocol) event bus and calling
Order/Inventory directly over REST for each step
([ADR 0001](docs/adrs/0001-redpanda-over-kafka.md),
[ADR 0004](docs/adrs/0004-custom-saga-orchestrator.md),
[ADR 0010](docs/adrs/0010-node-scoring-and-saga-orchestration.md)); a PySpark
Structured Streaming pipeline turns the same event catalog into
Bronze/Silver/Gold datasets in MinIO
([ADR 0005](docs/adrs/0005-spark-local-mode.md)); Jaeger, Prometheus, and
Grafana make the request/event path observable. Full container and sequence
diagrams (including the target-state ops dashboard and forecasting job, not
yet built): `docs/architecture.md`.

## Implemented capabilities

- Order lifecycle state machine (`CREATED → VALIDATED → INVENTORY_PENDING →
  INVENTORY_RESERVED → FULFILLMENT_ASSIGNED → PROCESSING → SHIPPED`, plus
  `CANCELLED`/`FAILED`) with idempotent creation and optimistic-versioned
  transitions.
- Row-locked inventory reservation with a stock-check endpoint and
  fulfillment-node scoring.
- A custom saga orchestrator: node scoring, deterministic payment simulation,
  compensation on failure, retry with backoff+jitter, dead-letter routing,
  and a replay CLI for reprocessing dead letters after a fix.
- Transactional outbox on every event-producing service, so an event is never
  published without the state change that caused it having already committed
  ([ADR 0003](docs/adrs/0003-transactional-outbox.md)).

## Data platform

PySpark Structured Streaming (`local[*]`, single-node) reads all 11
event-catalog topics into Bronze (immutable raw Parquet), validates and
deduplicates into Silver (rejects and late events routed to their own paths,
never dropped silently), and aggregates into 10 Gold datasets. Also
included: a synthetic event generator with configurable duplicate/late-event
injection, an executable data-quality suite (reconciliation, rejection rate,
duplicate rate, lateness, freshness) with a JSON report, and batch
backfill/reprocessing tooling with row-count validation before swapping into
the live path. Full design: `docs/data-pipeline.md`.

## Observability

Structured JSON logs with `correlation_id` on every line; OpenTelemetry
tracing pushed to Jaeger, with trace context carried across the Kafka
boundary in the event envelope itself; Prometheus metrics pulled from every
FastAPI service and background worker; a provisioned Grafana dashboard
(request rate/latency, Kafka lag/retries/DLQ, saga duration, DB pool). The
Spark data-platform services do not yet export metrics — see Known
limitations.

## Verified test and environment evidence

Host: Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No host
Python/Node/Java/Terraform — every build, test, and lint command runs inside
a container.

| Suite | Passed | Failed |
|---|---|---|
| event-contracts | 37 | 0 |
| order-service | 34 | 0 |
| inventory-service | 18 | 0 |
| fulfillment-orchestrator | 29 | 0 |
| api-gateway | 9 | 0 |
| data-platform | 40 | 0 |
| **Total** | **167** | **0** |

Also verified against a real, freshly-started `docker compose up`: the full
order lifecycle end to end (including the payment-decline/compensation
path), traces landing in Jaeger, all Prometheus scrape targets up with real
samples, the Grafana dashboard provisioned, and (Phase 4) real Bronze/
Silver/Gold Parquet plus a passing data-quality report. `mypy` passes clean
across all six packages; `ruff check`/`ruff format --check` pass clean. Full
detail, including every bug found and fixed while producing these numbers:
`TEST_RESULTS.md`.

## Quick-start instructions

Requires only Docker + Docker Compose — no paid services, no host Python/
Node/Java/Terraform.

```bash
cp .env.example .env
make demo        # docker compose up --build, then prints the service URLs
```

Other useful targets:

```bash
make test         # all six service test suites, each against its own *_test database
make typecheck    # mypy, per service
make lint         # ruff check
make format       # ruff format
make migrate      # apply Alembic migrations
make smoke        # end-to-end order lifecycle + observability verification
make generate     # run the synthetic event generator against the live stack
make dq-report    # run the data-quality report against live MinIO data
make backfill     # Silver/Gold backfill and reprocessing tooling
make reset        # tear down containers and volumes for a clean slate
make logs         # tail all service logs
```

## Important service URLs

Available once `make demo` reports all services healthy:

| Service | URL |
|---|---|
| API Gateway (start here) | http://localhost:8080/docs |
| Order Service (direct) | http://localhost:8001/docs |
| Inventory Service (direct) | http://localhost:8002/docs |
| Fulfillment Orchestrator (direct) | http://localhost:8003/docs |
| Jaeger (distributed traces) | http://localhost:16686 |
| Prometheus (metrics) | http://localhost:9090 |
| Grafana (dashboards, anonymous admin access) | http://localhost:3000 |
| MinIO Console (bronze/silver/gold browser) | http://localhost:9001 |

## Repository structure

```
services/
  api-gateway/            FastAPI edge service (authn/z, rate limiting, proxy)
  order-service/           Order state machine, outbox, validator consumer
  inventory-service/       Stock, reservations, row-level locking
  fulfillment-orchestrator/ Saga engine, node scoring, payment sim, DLQ, replay
  event-contracts/         Shared Kafka helpers, schemas, logging/tracing/metrics setup
  data-platform/            Spark Bronze/Silver/Gold, DQ, generator, backfill
infra/docker/               Compose service configs (Grafana, Prometheus, MinIO, Redpanda, OTel)
docs/                       Architecture, event catalog, data model, data pipeline, ADRs
scripts/                    compose_smoke_test.sh (make smoke)
docker-compose.yml, Makefile, .env.example
PROJECT_STATUS.md, RISKS.md, DECISIONS.md, TEST_RESULTS.md
```

## Architecture decisions worth reviewing

| ADR | Decision |
|---|---|
| [0001](docs/adrs/0001-redpanda-over-kafka.md) | Redpanda over Apache Kafka |
| [0002](docs/adrs/0002-inventory-concurrency-control.md) | Row-locking vs. optimistic versioning, by contention profile |
| [0003](docs/adrs/0003-transactional-outbox.md) | Transactional outbox over CDC/Debezium |
| [0004](docs/adrs/0004-custom-saga-orchestrator.md) | Custom lightweight saga orchestrator over Temporal/Airflow |
| [0005](docs/adrs/0005-spark-local-mode.md) | PySpark Structured Streaming, single-node `local[*]` |
| [0007](docs/adrs/0007-terraform-not-applied.md) | Terraform authored + validated, never applied |
| [0010](docs/adrs/0010-node-scoring-and-saga-orchestration.md) | Node-scoring formula, direct-REST saga coordination |

Full index of all 10 ADRs: `docs/adrs/README.md`.

## Known limitations

- **Saga resume gap**: a crash between a successful remote reservation and
  the saga's local commit of that step leaves no local record — fails loudly
  rather than double-reserving or guessing. Accepted, not solved (`RISKS.md` #11).
- **Data platform has no metrics visibility yet**: ports are declared but no
  Spark service starts a Prometheus exporter or gets scraped — a stalled job
  is only visible via `docker compose logs` (`RISKS.md` #19).
- **Single-instance-only gateway**: in-process rate limiting and per-process
  DB pooling, would not survive horizontal scaling without a shared backing
  store (`RISKS.md` #13).
- **Grafana and worker `/metrics` are unauthenticated** — fine for a local
  demo, first thing to change before any shared deployment (`RISKS.md` #14).
- **Custom saga orchestrator, not a proven framework** — less battle-tested
  than Temporal; a deliberate scope tradeoff (`RISKS.md` #8).

Full risk register, with status and mitigation for each: `RISKS.md`.

## Remaining roadmap

Phases 6-13, not yet started: demand forecasting, a React/TypeScript ops
dashboard, a failure laboratory (10 deterministic scenarios), security
hardening, load testing, AWS infrastructure in Terraform (authored/validated
only, per [ADR 0007](docs/adrs/0007-terraform-not-applied.md)), CI/CD, and
final documentation/career deliverables. Full scope per phase:
`PROJECT_STATUS.md`.

## License status

No `LICENSE` file exists yet. One is planned alongside the rest of the
documentation set in Phase 13.
