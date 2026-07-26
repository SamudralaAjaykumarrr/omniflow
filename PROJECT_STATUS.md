# Project Status

Last updated: 2026-07-26 (Phase 4 complete; Engineering-quality and
streaming-data-platform-hardening work landed on top — see notes below).

## Current phase

**Phase 4 (Data engineering platform) complete and verified.** Data quality
checks/reporting (originally slotted as a separate Phase 5) were folded into
this phase — see below. Phase 6 (Demand forecasting) not yet started.

**Engineering-quality tooling** (branch `phase-5-engineering-quality`) has
also landed: a measured test-coverage threshold + `coverage.xml`, zero-cost
security scanning (bandit + pip-audit), pre-commit hygiene hooks, and a
GitHub Actions CI workflow. This branch's name collides with the table's
existing "Phase 5" below by coincidence — it isn't that phase, and the
table isn't renumbered for it. It's a slice pulled forward from three later
phases' scope (coverage tooling from Phase 10, dependency/SAST scanning
from part of Phase 9, CI from Phase 12) — none of those phases are marked
Done below, since their full scope (JWT/RBAC, load-test tooling, etc.)
isn't covered by this slice. Full detail: `docs/phase-5-engineering-quality.md`.

**Streaming data-platform hardening** (branch
`phase-6-streaming-data-platform`) has also landed: Bronze-level
malformed-JSON quarantine, Prometheus metrics for the Spark bronze/silver/
gold jobs (closes `RISKS.md` #19), a real bug fix in Silver's dedup
watermark found by running the pipeline end-to-end (`RISKS.md` #21), a
data-lake inspection CLI, and an end-to-end Phase 6 smoke test
(`make phase6-smoke`). Same naming-collision note as above: this branch's
name reuses "Phase 6" from the table below by coincidence — the table's
actual Phase 6 (Demand forecasting) is still Not Started; the platform
this branch hardens was built in Phase 4, not this branch. Full detail:
`docs/phase-6-streaming-data-platform.md`.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0. Planning artifacts | Done | Product requirements, architecture, event catalog, data model, data pipeline design, 9 ADRs, tracking files, README/CLAUDE.md |
| 1. Core domain | **Done** | Postgres + Alembic, Order Service, Inventory Service, API Gateway — see `TEST_RESULTS.md` |
| 2. Event platform | **Done** | Redpanda, outbox relays, event-contracts Kafka helpers, order-service validator consumer, fulfillment-orchestrator saga (node scoring, payment sim, compensation, retry+jitter, DLQ, replay) — see below and `TEST_RESULTS.md` |
| 3. Observability | **Done** | Structured JSON logs w/ correlation IDs, OpenTelemetry distributed tracing (Jaeger, cross-Kafka-hop trace propagation), Prometheus metrics (every service + every background worker), Grafana dashboard, mypy type checking — see below and `TEST_RESULTS.md` |
| 4. Data engineering platform | **Done** | Spark bronze/silver/gold into MinIO, synthetic generator, backfill/reprocessing tooling — see below and `TEST_RESULTS.md` |
| 5. Data quality | **Done** | Executable checks + report — folded into Phase 4 (`app.dq`), see below |
| 6. Demand forecasting | Not started | Synthetic data, baseline + secondary model |
| 7. Ops dashboard | Not started | React + TypeScript, 10 screens |
| 8. Failure laboratory | Not started | 10 deterministic failure scenarios |
| 9. Security hardening | Partially pulled forward | Dependency/SAST scanning (bandit + pip-audit) done — see `docs/phase-5-engineering-quality.md`; JWT/RBAC finalization, audit events still not started |
| 10. Testing completion + load test | Partially pulled forward | Coverage threshold (65%, measured 71.6%) + `coverage.xml` done — see `docs/phase-5-engineering-quality.md`; load test tooling still not started |
| 11. AWS infrastructure (Terraform) | Not started | Authored + validated, never applied |
| 12. CI/CD | Partially pulled forward | `.github/workflows/ci.yml` authored and its steps verified locally via `make ci`; not yet exercised by an actual GitHub-hosted run — see `docs/phase-5-engineering-quality.md` |
| 13. Documentation & career deliverables | Not started | Remaining docs, final review |

Full phase scope and acceptance criteria: `docs/architecture.md` (diagrams) and
the phase table originally captured in planning; acceptance criteria are
restated at the top of each phase's own PR/commit as it lands.

## What exists in the repo right now

- `docs/product-requirements.md`, `docs/system-context.md`,
  `docs/architecture.md` (Observability flow diagram updated in Phase 3 to
  match the real pull-metrics/push-traces split actually built), `docs/event-catalog.md`, `docs/data-model.md`,
  `docs/data-pipeline.md`
- `docs/adrs/0001`–`0010` + index (0010: node-scoring formula + saga
  coordination via direct REST)
- `README.md`, `CLAUDE.md`
- `PROJECT_STATUS.md`, `DECISIONS.md`, `RISKS.md`, `TEST_RESULTS.md` (this set)
- **Phase 1 application code:** event-contracts, order-service,
  inventory-service, api-gateway (see prior status entry / `TEST_RESULTS.md`)
- **Phase 2 application code:**
  - `services/event-contracts` — Kafka producer/consumer helpers
    (`build_producer`, `publish_envelope`, `build_consumer`,
    `run_consume_loop` with generic retry+backoff+jitter+DLQ), per-event-type
    schema registry for contract tests
  - `services/order-service` — `app/validator_consumer.py` (own
    `order.created` consumer, self-validates `CREATED -> VALIDATED`),
    `app/outbox_relay.py`, generic `/orders/{id}/transition` endpoint for the
    orchestrator, `processed_events` table
  - `services/inventory-service` — `app/outbox_relay.py`,
    `GET /fulfillment-nodes`, `POST /stock/check` (advisory batch pre-check)
  - `services/fulfillment-orchestrator` — **new service**: saga engine
    (`app/saga.py`), node-scoring formula (`app/scoring.py`), deterministic
    payment simulator (`app/payment.py`), generic backoff+jitter retry
    (`app/retry.py`), REST clients to order/inventory (`app/clients.py`),
    Kafka consumer wiring + DLQ persistence (`app/consumer.py`), replay CLI
    (`app/replay.py`), read-only FastAPI surface (saga instances, dead
    letters), its own outbox relay, Alembic migrations
  - `docker-compose.yml` — Redpanda + topic-init job, both outbox relays,
    order-service's validator consumer, all three orchestrator processes
    (API/consumer/outbox-relay); `api-gateway` gained a Docker healthcheck it
    was missing since Phase 1
  - `scripts/compose_smoke_test.sh` (`make smoke`) — real end-to-end test
    against the live stack
  - `Makefile` — `test-contracts`, `test-orchestrator`, `smoke`, `replay`
    targets added
- **Phase 3 application code:**
  - `services/event-contracts` — `event_contracts/logging_setup.py`
    (`configure_logging`, stdout JSON formatter, process-wide
    `correlation_id_var` contextvar), `event_contracts/tracing_setup.py`
    (`configure_tracing` against an OTLP/HTTP exporter,
    `current_traceparent`/`context_from_traceparent` for carrying trace
    context across the Kafka boundary via the envelope's
    `trace_context.traceparent`), `event_contracts/metrics_setup.py`
    (`MetricsMiddleware`, `metrics_response`, `DBPoolCollector`,
    `kafka_stats_callback` for consumer-lag); `kafka.py`'s
    `run_consume_loop` now sets `correlation_id_var`, opens a tracing span
    resumed from the envelope's stored trace context, and increments
    retry/dead-letter counters — one shared implementation used by every
    consumer, not duplicated per service
  - Every FastAPI service (`api-gateway`, `order-service`,
    `inventory-service`, `fulfillment-orchestrator`) calls
    `configure_logging`/`configure_tracing` at import time, adds
    `MetricsMiddleware` + a `GET /metrics` route, registers
    `FastAPIInstrumentor`/`HTTPXClientInstrumentor`, and registers a
    `DBPoolCollector` against its SQLAlchemy engine
  - Every background worker (both outbox relays × 3 services, the
    order-service validator consumer, the orchestrator's saga consumer)
    calls `configure_logging`/`configure_tracing`, runs a standalone
    `prometheus_client` HTTP server on its own `METRICS_PORT`, and (the two
    consumers) passes `kafka_stats_callback()` into `build_consumer` for
    consumer-lag metrics; the orchestrator's saga consumer also
    instruments its outbound `httpx` REST calls to order/inventory
  - Each outbox relay's publish step now opens a tracing span resumed from
    the row's stored `trace_context.traceparent`, so the relay's own hop
    is visible in Jaeger between "request handled" and "consumer
    processed"
  - `inventory-service/app/metrics.py` (`INVENTORY_RESERVATION_CONFLICTS_TOTAL`),
    `fulfillment-orchestrator/app/metrics.py` (`SAGA_DURATION_SECONDS`) —
    service-specific business metrics, not shared infra
  - `infra/docker/otel/otel-collector-config.yaml` (OTLP receiver ->
    Jaeger's own OTLP receiver, traces only), `infra/docker/prometheus/prometheus.yml`
    (scrapes every FastAPI service + every worker's standalone metrics
    port), `infra/docker/grafana/provisioning/` (Prometheus datasource +
    dashboard provider) and `infra/docker/grafana/dashboards/omniflow-overview.json`
    (request rate/latency, Kafka lag/retries/DLQ, saga duration, inventory
    conflicts, DB pool)
  - `docker-compose.yml` — `jaeger`, `otel-collector`, `prometheus`,
    `grafana` services added; every service/worker gained a Docker
    dependency on `otel-collector`; each worker gained its own
    `METRICS_PORT`
  - `Makefile` — `typecheck` target added (mypy, per-service, throwaway
    container — first static type checking this project has run)
  - `scripts/compose_smoke_test.sh` extended to verify traces actually
    land in Jaeger for every traced service, every Prometheus scrape
    target is up with real samples, and Grafana's datasource/dashboard are
    live — not just the order lifecycle; also fixed two latent
    not-safely-rerunnable bugs (hardcoded fulfillment-node name and
    customer email collided with a previous run's rows on a persistent
    dev DB volume)
- **Phase 4 application code:**
  - `services/data-platform` — **new service** (Spark Structured Streaming,
    `local[*]` per ADR 0005):
    - `app/bronze.py` — Kafka (all 11 event-catalog topics) -> raw Parquet,
      partitioned `event_type`/`date`, loosely-typed payload
    - `app/silver.py`/`app/silver_io.py` — one streaming query per event
      type: schema validation (quarantines to `silver_rejects` with a
      reason), `dropDuplicatesWithinWatermark` dedup, lateness detection
      (routes to `late_events`), each event type writing to its own base
      path (`app/backfill.py`'s Silver reprocessing matches)
    - `app/gold/` — all 10 Gold datasets from `docs/data-pipeline.md`'s
      table: 9 streaming aggregations (`app/gold/queries.py`,
      `app/gold/runner.py`, `foreachBatch` + plain writes) plus consumer-group
      lag (`app/lag_poller.py`, direct Kafka polling, no Spark)
    - `app/dq/checks.py`/`app/dq/report.py` — Bronze-vs-Silver
      reconciliation, schema-rejection-rate, duplicate-rate,
      late-event-rate, and freshness checks, run against one date's real
      Parquet and written as a JSON report to `dq-reports/`
    - `app/generator.py` — synthetic order-lifecycle event generator
      (schema-validated against `event_contracts.schemas`), with
      configurable duplicate/late injection for exercising Silver's
      dedup/late-event paths end-to-end
    - `app/backfill.py` — Silver (from Bronze) / Gold (from Silver) batch
      reprocessing over a bounded date range, side-path + row-count
      validation + swap into the live path
    - `app/s3.py` — shared s3fs/boto3 helpers (`ensure_prefix_exists` for
      Structured Streaming's fresh-environment/partition-discovery
      requirements, `boto3_client` for deletes this MinIO version's bulk
      `DeleteObjects` API rejects)
  - `infra/docker/minio/create-buckets.sh` — idempotent bucket + prefix
    layout (`bronze`/`silver`/`silver_rejects`/`late_events`/`gold`/
    `checkpoints`/`dq-reports`)
  - `docker-compose.yml` — `minio`, `minio-init`, `spark-bronze`,
    `spark-silver`, `spark-gold`, `lag-poller` services added
  - `Makefile` — `test-data-platform`, `generate`, `dq-report`, `backfill`
    targets added; `typecheck` extended to `services/data-platform/app`
- 167 passing tests across six suites (event-contracts, order-service,
  inventory-service, fulfillment-orchestrator, api-gateway, data-platform)
  — see `TEST_RESULTS.md` for the full breakdown.
- **Engineering-quality tooling** (branch `phase-5-engineering-quality`,
  see `docs/phase-5-engineering-quality.md` for full detail):
  - `infra/docker/devtools/Dockerfile` — shared pinned image (ruff, mypy,
    pytest, coverage, bandit, pip-audit, pre-commit), built via
    `make setup-dev`
  - `Makefile` — `help`, `coverage` (combines all six suites' coverage data
    into root `coverage.xml`, enforces `COV_THRESHOLD := 65`, measured
    71.6%), `security` (bandit + pip-audit), `docker-validate`,
    `docker-build`, `pre-commit`, `ci` (runs all of the above in order)
  - `.pre-commit-config.yaml` — hygiene hooks + ruff, validated via
    `make pre-commit`
  - `.github/workflows/ci.yml` — GitHub Actions, standard free
    `ubuntu-latest` runner, mirrors `make ci` job-for-job
  - `RISKS.md` #20 — 14 real CVEs found by `pip-audit`'s first run; 5
    (`pip`) fixed outright (`pip==26.1.2` pinned in every Dockerfile), 9
    accepted with individual justification (`starlette`'s fixes need a
    `fastapi` major-version bump verified incompatible with the current
    pin; `pytest`/`pyarrow`'s don't apply to how this codebase uses them)
- **Streaming data-platform hardening** (branch
  `phase-6-streaming-data-platform`, see
  `docs/phase-6-streaming-data-platform.md` for full detail):
  - `services/data-platform/app/bronze.py` — malformed-JSON quarantine
    (`transform_to_bronze_rejects` -> new `bronze_rejects` MinIO prefix),
    converted from a direct `.writeStream.format("parquet")` sink to
    `foreachBatch` (matches Silver/Gold's existing pattern)
  - `services/data-platform/app/metrics.py` — **new module**:
    `prometheus_client`-backed `start_metrics_server`/`record_rows`/
    `track_batch_duration`, wired into `app/bronze.py`/`app/silver.py`/
    `app/gold/common.py`'s `main()`s and batch writers — closes `RISKS.md` #19
  - `services/data-platform/app/silver.py` — **real bug fixed**: dedup
    watermark moved from `occurred_at_ts` to `ingested_at` (see `RISKS.md`
    #21/`DECISIONS.md` for the full root-cause writeup); ~64 historically-
    dropped rows recovered via `app.backfill --apply` with explicit
    confirmation
  - `services/data-platform/app/dq/report.py` — Bronze read changed to
    per-`event_type=` subdirectory (`app.bronze.read_bronze_batch`, unioned),
    never the Bronze root — avoids a `_spark_metadata`-poisoned-root read
    (same failure class as `RISKS.md` #18)
  - `services/data-platform/app/inspect.py` — **new module**: MinIO
    data-lake prefix inspection CLI (object count/bytes by partition,
    sample keys), backs `make inspect-*`
  - `services/data-platform/app/generator.py` — `--malformed-rate` added
    (opt-in, default 0)
  - `infra/docker/minio/create-buckets.sh` — `bronze_rejects` prefix added
  - `infra/docker/prometheus/prometheus.yml` — `spark-bronze`/
    `spark-silver`/`spark-gold` scrape targets added
  - `scripts/phase6_smoke_test.sh` — **new**: end-to-end synthetic traffic
    -> Bronze (twice, restart check) -> Silver -> Gold -> DQ report
  - `Makefile` — `streaming-up`/`streaming-down`, `inspect-bronze`/
    `inspect-bronze-rejects`/`inspect-silver`/`inspect-silver-rejects`/
    `inspect-late-events`/`inspect-gold`, `phase6-smoke`, `phase6-validate`,
    `clean-phase6` targets added
  - 181 passing tests across six suites (data-platform grew from 40 to 54)
    — see `TEST_RESULTS.md` for the full breakdown

## Environment notes (relevant to every future phase)

Host has Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No
host-installed Python packages (pip absent), no Node/npm, no Java, no
Terraform — all builds/tests/lint run inside containers. See ADRs 0001, 0005,
0007 for how this shaped the design. Confirmed workable again in Phase 4:
the full Phase 1-3 stack plus MinIO plus Bronze/Silver/Gold/lag-poller — 23
containers total — ran concurrently on this host without OOM
(`docker compose ps` all healthy, real end-to-end smoke test and Phase 4
generator/DQ/backfill verification both passed against a genuinely fresh
`docker compose up`). Running Silver's 11 and Gold's 9 concurrent Structured
Streaming queries did need a real fix (`local[*]` + `spark.scheduler.mode=
FAIR`, see `RISKS.md` #16) — under-provisioned Spark parallelism starved
individual queries outright, not just slowed them down.

## Next action

Begin Phase 6: Demand forecasting (synthetic data, baseline + secondary
model), per ADR 0006. Phase 5 (Data quality) is done, folded into Phase 4.
Engineering-quality tooling (this document's separate note above) is also
done for the slice it covers; JWT/RBAC (rest of Phase 9), load-test tooling
(rest of Phase 10), an actual GitHub-hosted CI run (rest of Phase 12), and
Terraform (Phase 11) remain untouched.
