# Project Status

Last updated: 2026-07-24 (Phase 2 complete).

## Current phase

**Phase 2 (Event platform) complete and verified.** Phase 3 (Observability)
not yet started.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0. Planning artifacts | Done | Product requirements, architecture, event catalog, data model, data pipeline design, 9 ADRs, tracking files, README/CLAUDE.md |
| 1. Core domain | **Done** | Postgres + Alembic, Order Service, Inventory Service, API Gateway — see `TEST_RESULTS.md` |
| 2. Event platform | **Done** | Redpanda, outbox relays, event-contracts Kafka helpers, order-service validator consumer, fulfillment-orchestrator saga (node scoring, payment sim, compensation, retry+jitter, DLQ, replay) — see below and `TEST_RESULTS.md` |
| 3. Observability | Not started | Structured logs, OTel, Prometheus, Grafana, Jaeger |
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
  `docs/architecture.md` (updated Phase 2 sequence/flow diagrams to match
  what was actually built), `docs/event-catalog.md`, `docs/data-model.md`,
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
- 107 passing tests across five suites (event-contracts, order-service,
  inventory-service, fulfillment-orchestrator, api-gateway) — see
  `TEST_RESULTS.md` for the full breakdown.

## Environment notes (relevant to every future phase)

Host has Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No
host-installed Python packages (pip absent), no Node/npm, no Java, no
Terraform — all builds/tests/lint run inside containers. See ADRs 0001, 0005,
0007 for how this shaped the design. Confirmed workable again in Phase 2:
Redpanda (single broker, `--smp=1 --memory=512M`) plus Postgres plus 4
FastAPI services plus 5 background workers (2 outbox relays, 1 validator
consumer, 1 saga consumer, 1 orchestrator outbox relay) all ran concurrently
on this host without resource issues.

## Next action

Begin Phase 3: Observability (structured JSON logging with correlation IDs
across all services, OpenTelemetry traces, Prometheus metrics, Grafana
dashboards, Jaeger, health/readiness endpoints already exist and should be
wired into the trace/metric pipeline), per `docs/architecture.md`'s
observability-flow diagram and the approved plan's Phase 3 acceptance
criteria.
