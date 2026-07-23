# Project Status

Last updated: 2026-07-23 (Phase 1 complete).

## Current phase

**Phase 1 (Core domain) complete and verified.** Phase 2 (Event platform) not
yet started.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0. Planning artifacts | Done | Product requirements, architecture, event catalog, data model, data pipeline design, 9 ADRs, tracking files, README/CLAUDE.md |
| 1. Core domain | **Done** | Postgres + Alembic, Order Service, Inventory Service, API Gateway — see below and `TEST_RESULTS.md` |
| 2. Event platform | Not started | Redpanda, outbox relay, event-contracts, orchestrator saga, DLQ, replay |
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
  `docs/architecture.md`, `docs/event-catalog.md`, `docs/data-model.md`,
  `docs/data-pipeline.md`
- `docs/adrs/0001`–`0009` + index
- `README.md`, `CLAUDE.md`
- `PROJECT_STATUS.md`, `DECISIONS.md`, `RISKS.md`, `TEST_RESULTS.md` (this set)
- **Phase 1 application code:**
  - `services/event-contracts` — shared event envelope + event-type constants
  - `services/order-service` — order state machine, idempotency keys,
    transactional outbox, Alembic migrations, FastAPI routes
  - `services/inventory-service` — stock/reservation model, row-level-locked
    reservation logic, reservation expiry, Alembic migrations, FastAPI routes
  - `services/api-gateway` — correlation IDs, rate limiting, structured
    errors, request logging, proxying to order/inventory services
  - `docker-compose.yml`, per-service `Dockerfile`/`entrypoint.sh`,
    `infra/docker/postgres/init-databases.sql`, `Makefile`, `.env.example`,
    root `pyproject.toml` (ruff config)
- 39 passing tests across the three services (96%/95%/93% coverage) — see
  `TEST_RESULTS.md` for the full breakdown, including the two concurrency
  tests that back ADR 0002's no-oversell claim.

## Environment notes (relevant to every future phase)

Host has Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No
host-installed Python packages (pip absent), no Node/npm, no Java, no
Terraform — all builds/tests/lint run inside containers. See ADRs 0001, 0005,
0007 for how this shaped the design. Confirmed workable in practice during
Phase 1: all three services build, test, and lint entirely through
`docker compose` / throwaway `docker run` containers, no host toolchain
needed.

## Next action

Begin Phase 2: Event platform (Redpanda, outbox relay publisher,
event-contracts compatibility tests, fulfillment orchestrator saga, DLQ,
replay tooling), per `docs/architecture.md` and the approved plan's Phase 2
acceptance criteria.
