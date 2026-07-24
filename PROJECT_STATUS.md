# Project Status

Last updated: 2026-07-24 (Phase 3 complete).

## Current phase

**Phase 3 (Observability) complete and verified.** Phase 4 (Data engineering
platform) not yet started.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0. Planning artifacts | Done | Product requirements, architecture, event catalog, data model, data pipeline design, 9 ADRs, tracking files, README/CLAUDE.md |
| 1. Core domain | **Done** | Postgres + Alembic, Order Service, Inventory Service, API Gateway — see `TEST_RESULTS.md` |
| 2. Event platform | **Done** | Redpanda, outbox relays, event-contracts Kafka helpers, order-service validator consumer, fulfillment-orchestrator saga (node scoring, payment sim, compensation, retry+jitter, DLQ, replay) — see below and `TEST_RESULTS.md` |
| 3. Observability | **Done** | Structured JSON logs w/ correlation IDs, OpenTelemetry distributed tracing (Jaeger, cross-Kafka-hop trace propagation), Prometheus metrics (every service + every background worker), Grafana dashboard, mypy type checking — see below and `TEST_RESULTS.md` |
| 4. Data engineering platform | Not started | Spark bronze/silver/gold into MinIO |
| 5. Data quality | Not started | Executable checks + report |
| 6. Demand forecasting | Not started | Synthetic data, baseline + secondary model |
| 7. Ops dashboard | Not started | React + TypeScript, 10 screens |
| 8. Failure laboratory | Not started | 10 deterministic failure scenarios |
| 9. Security hardening | Not started | JWT/RBAC finalization, scanning configs, audit events |
| 10. Testing completion + load test | Not started | Coverage threshold, load test tooling |
| 11. AWS infrastructure (Terraform) | Not started | Authored + validated, never applied |
| 12. CI/CD | Not started | GitHub Actions workflows |
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
- 127 passing tests across five suites (event-contracts, order-service,
  inventory-service, fulfillment-orchestrator, api-gateway) — see
  `TEST_RESULTS.md` for the full breakdown.

## Environment notes (relevant to every future phase)

Host has Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No
host-installed Python packages (pip absent), no Node/npm, no Java, no
Terraform — all builds/tests/lint run inside containers. See ADRs 0001, 0005,
0007 for how this shaped the design. Confirmed workable again in Phase 3:
Redpanda plus Postgres plus 4 FastAPI services plus 5 background workers
plus the full observability stack (Jaeger, OTel Collector, Prometheus,
Grafana) — 17 containers total — all ran concurrently on this host without
resource issues (`docker compose ps` all healthy, real end-to-end smoke
test passed).

## Next action

Begin Phase 4: Data engineering platform (Spark Structured Streaming
bronze/silver/gold pipeline into MinIO), per `docs/data-pipeline.md` and
ADR 0005 (single-node `local[*]` Spark).
