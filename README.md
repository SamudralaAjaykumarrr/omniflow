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

**Phases 1-9 of 13 are done and verified** (Phase 5, Data quality, is also
done — folded into Phase 4). **Phases 11, 13 have not been started**; parts
of 10 and 12 have been pulled forward as a separate engineering-quality
pass, and the Phase 4 streaming data platform has had a hardening pass on
top (see below).

| Done now | Not started yet |
|---|---|
| Core domain (orders, inventory, API gateway) | Load testing, Terraform, career docs |
| Event platform (Redpanda, saga orchestrator, DLQ, replay) | An actual GitHub-hosted CI run (workflow authored + verified locally only) |
| Observability (structured logs, tracing, metrics, Grafana) | |
| Data platform (Spark Bronze/Silver/Gold, data quality, backfill, malformed-event quarantine, Spark job metrics) | |
| Demand forecasting (synthetic history, seasonal-naive baseline, `HistGradientBoostingRegressor` secondary model, chronological evaluation, champion selection, future forecasts) | |
| Measured coverage threshold, security scanning, pre-commit, CI (`docs/phase-5-engineering-quality.md`) | |
| Ops dashboard (React/TypeScript, 10 screens, `docs/phase-7-ops-dashboard.md`) | |
| Failure laboratory (10 deterministic failure scenarios, `docs/phase-8-failure-laboratory.md`) | |
| JWT authentication + role-based authorization (`DECISIONS.md` "Phase 9") | |

Data quality (checks + report) was originally scoped as its own phase but was
folded into Phase 4, since the Spark plumbing it depends on was already in
place. The engineering-quality pass reuses the number "Phase 5" in its
branch name by coincidence — it is not that phase; see
`docs/phase-5-engineering-quality.md` for the naming note. A separate
streaming-data-platform hardening pass similarly reused "Phase 6" in its own
branch name by coincidence — this branch (`phase-6-demand-forecasting`) is
the table's actual Phase 6; see `docs/phase-6-streaming-data-platform.md`
for that unrelated hardening pass and `docs/phase-6-demand-forecasting.md`
for this one. Full phase-by-phase detail: `PROJECT_STATUS.md`.

## Verified proof points

Every number below comes from a command actually run against this repo (see
`TEST_RESULTS.md`; nothing here is estimated) or from a real
`docker compose up` verified in `PROJECT_STATUS.md`:

- **411 tests passing, 0 failing** across seven suites (event-contracts,
  order-service, inventory-service, fulfillment-orchestrator, api-gateway,
  data-platform, failure-lab — including 91 forecasting tests and 52 new
  Phase 9 JWT/RBAC tests: token creation/validation, the 401-vs-403
  authorization boundary, and every negative-token case — expired,
  malformed, missing, wrong-signature, wrong-audience, wrong-issuer,
  insufficient-role)
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
- **Demand forecasting, measured honestly**: on this session's deterministic
  smoke-test run, the secondary model (`HistGradientBoostingRegressor`,
  WAPE 0.154) genuinely beat the seasonal-naive baseline (WAPE 0.298) and
  was selected champion by a documented rule using the measured numbers —
  full detail: `docs/phase-6-demand-forecasting.md`
- **80.9% measured combined test coverage** across all seven Python suites,
  a 65% threshold enforced by `make coverage` and `coverage.xml` generated
  at the repo root; `make security` (bandit + pip-audit) runs clean, with
  every accepted CVE individually justified in `RISKS.md` #20 — full
  detail: `docs/phase-5-engineering-quality.md`
- **82 passing dashboard tests** (Vitest + React Testing Library, 19 files —
  up from 66/16, +16 Phase 9 auth-flow tests: login, logout, session
  restore, route guard, role ranking) for the `services/ops-dashboard`
  React/TypeScript app, plus a clean `eslint`/`prettier --check`/
  `tsc --noEmit`/`vite build` — full detail: `docs/phase-7-ops-dashboard.md`,
  `docs/phase-8-failure-laboratory.md`
- **Failure laboratory: 10 deterministic failure scenarios, each triggered
  through a real backend API** (`services/failure-lab`) and verified twice
  in a row against the real running stack (`make phase8-smoke`) — saga
  compensation, retry/backoff, row-level-lock concurrency, idempotency
  (both request- and event-level), dead-letter routing, Bronze/Silver data
  quality, and saga crash-resume are each demonstrated for real, not
  simulated in the browser — full detail:
  `docs/phase-8-failure-laboratory.md`
- **JWT authentication + role-based authorization (ADR 0009), verified
  against the real running stack, not just unit tests**: logged in as each
  of the three seeded roles (`admin`/`ops`/`viewer`) through api-gateway's
  real `POST /auth/login` (bcrypt-verified against a real Postgres `users`
  table), confirmed a `viewer` token gets `403` creating an order while an
  `ops` token reaches the real order-service proxy, confirmed a missing
  token gets `401`, and confirmed `/healthz`/`/readyz`/`/metrics` stay
  public throughout — full detail: `DECISIONS.md` "Phase 9".

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
- **Sixteen real bugs found and fixed by actually running the system** (Spark
  scheduler starvation, MinIO's bulk-delete rejection, a Structured Streaming
  metadata-visibility gap, a dedup watermark declared on the wrong timestamp
  column silently dropping valid rows, a recursive-forecast row-ordering bug
  caught by a regression test before it ever shipped, a malformed Kafka
  record that could crash any consumer forever, a saga-resume startup crash,
  a dead-letter replay tool that had never actually worked, and more) — full
  writeups in `DECISIONS.md`.

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
Grafana make the request/event path observable; a React + TypeScript ops
dashboard (`services/ops-dashboard`) presents order/inventory/saga/DLQ/
pipeline-health state to an ops user, reverse-proxied by its own nginx —
see `docs/phase-7-ops-dashboard.md`. Full container and sequence diagrams:
`docs/architecture.md`.

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
event-catalog topics into Bronze (immutable raw Parquet, with malformed/
unparseable Kafka records quarantined to their own path rather than
written with null envelope fields), validates and deduplicates into Silver
(rejects and late events routed to their own paths, never dropped
silently), and aggregates into 10 Gold datasets. Also included: a synthetic
event generator with configurable duplicate/late-event/malformed-record
injection, an executable data-quality suite (reconciliation, rejection
rate, duplicate rate, lateness, freshness) with a JSON report, batch
backfill/reprocessing tooling with row-count validation before swapping
into the live path, a MinIO data-lake inspection CLI, and an end-to-end
smoke test (`make phase6-smoke`). Full design: `docs/data-pipeline.md`,
`docs/phase-6-streaming-data-platform.md`.

## Demand forecasting

A pandas/scikit-learn batch pipeline (`services/data-platform/app/
forecasting`, no Spark/JVM needed) over a deterministic synthetic demand
history (SKU x location x date grain — the real event catalog has no
location attribution to build this from yet, and live volume is too small
either way, both confirmed before building anything): feature engineering
with tested leakage safeguards, a seasonal-naive baseline, a
`HistGradientBoostingRegressor` secondary model, chronological (never
random) evaluation with rolling-origin walk-forward folds, MAE/RMSE/WAPE
computed from real predictions, a documented measured champion-selection
rule, recursive multi-step future forecasts, and local model-artifact
persistence. Full CLI (`python -m app.forecasting.cli`), 12
`make forecast-*` targets, and an end-to-end local smoke test
(`make forecast-smoke`, no live MinIO/Kafka needed). Full design:
`docs/phase-6-demand-forecasting.md`, [ADR 0006](docs/adrs/0006-forecasting-scope.md).

## Operations dashboard

A React + TypeScript single-page app (`services/ops-dashboard`, Vite +
`react-router-dom`), served by its own nginx image and reverse-proxying
same-origin to the API Gateway, Inventory Service, Fulfillment Orchestrator,
Failure Laboratory, and Prometheus — no CORS changes needed on any backend.
Ten screens: Overview, Orders (create/cancel/track, status-history
timeline), Inventory & Fulfillment Nodes, Saga Monitor, Dead Letter Queue,
Observability (live Prometheus queries), Data Quality, Data Platform,
Demand Forecasting, and Failure Laboratory (Phase 8 — 10 deterministic
failure scenarios, triggered and reset through a real backend). Seven of
the ten screens are fully live against real running services; the other
three mix real measured numbers with clearly-labeled local fallback data
where no read API exists yet (documented per-screen in
`docs/phase-7-ops-dashboard.md`).

**Real login required as of Phase 9** (ADR 0009): a real login screen
authenticates against api-gateway's `POST /auth/login` (bcrypt-verified
credentials, a real Postgres `users` table), and every session carries a
short-lived JWT. Creating/cancelling an order and triggering/resetting a
Failure Lab scenario are hidden for a `viewer` session (a UI convenience —
the actual boundary is api-gateway's/failure-lab's own 401/403, not the
dashboard hiding a button). 82 passing tests (Vitest + React Testing
Library).

## Authentication & authorization

Self-contained JWT auth + role-based access control
([ADR 0009](docs/adrs/0009-authn-authz.md)) — no external identity provider,
consistent with this project's "no paid services" constraint. api-gateway
owns a `users` table (bcrypt-hashed passwords via `passlib`) and issues
short-lived signed JWTs (`POST /auth/login`); every protected route
verifies signature, issuer, audience, and expiration before checking a
ranked role (`viewer < ops < admin` — `admin` inherits every `ops`
permission, not a separately-maintained list). Enforced on api-gateway's
customer-facing proxy routes (`POST/GET /api/orders*`, `GET
/api/inventory/stock/*`) and failure-lab's scenario trigger/reset routes —
the two surfaces ADR 0009 itself names; `/healthz`/`/readyz`/`/metrics`
stay public everywhere. Three demo accounts are seeded idempotently at
every api-gateway startup (`admin@omniflow.local`/`ops@omniflow.local`/
`viewer@omniflow.local`, dev-only passwords documented in
`.env.example`) plus a scoped `ops`-role service account failure-lab's own
scenario runner authenticates as for its machine-to-machine calls against
the gateway. Deliberately **not** extended to order-service/
inventory-service/fulfillment-orchestrator's own HTTP routes — those are
called directly by the real saga orchestrator and failure-lab with no user
JWT to present, and protecting them would need a second, broader
service-to-service auth layer outside this phase's documented scope; see
`RISKS.md` #25/#34 and `DECISIONS.md` "Phase 9" for the full reasoning.
52 new backend tests cover the token lifecycle and the 401-vs-403
boundary, including every negative-token case (expired, malformed,
missing, wrong-signature, wrong-audience, wrong-issuer, insufficient-role).

## Observability

Structured JSON logs with `correlation_id` on every line; OpenTelemetry
tracing pushed to Jaeger, with trace context carried across the Kafka
boundary in the event envelope itself; Prometheus metrics pulled from every
FastAPI service, every background worker, and every Spark bronze/silver/
gold job (`data_platform_batch_rows_total`/`data_platform_batch_duration_seconds`);
a provisioned Grafana dashboard (request rate/latency, Kafka lag/retries/
DLQ, saga duration, DB pool).

## Verified test and environment evidence

Host: Docker 29.6.2 + Compose v5.3.1, 8 CPUs, 15Gi RAM, ~950G disk. No host
Python/Node/Java/Terraform — every build, test, and lint command runs inside
a container.

| Suite | Passed | Failed |
|---|---|---|
| event-contracts | 38 | 0 |
| order-service | 37 | 0 |
| inventory-service | 23 | 0 |
| fulfillment-orchestrator | 41 | 0 |
| api-gateway | 9 | 0 |
| data-platform | 145 | 0 |
| failure-lab | 66 | 0 |
| **Total** | **359** | **0** |

data-platform's 145 includes 91 forecasting tests (`tests/forecasting/`) —
unit tests for synthetic-data determinism, feature/leakage correctness,
data-quality checks, chronological splits, both models, metrics, champion
selection, and artifact persistence, plus pipeline tests for dataset
preparation and a full end-to-end CLI run.

Also verified against a real, freshly-started `docker compose up`: the full
order lifecycle end to end (including the payment-decline/compensation
path), traces landing in Jaeger, all Prometheus scrape targets up with real
samples, the Grafana dashboard provisioned, (Phase 4) real Bronze/
Silver/Gold Parquet plus a passing data-quality report, and (Phase 8) all
10 failure-lab scenarios reaching PASSED/RECOVERED twice in a row against
the live stack (`make phase8-smoke`). `mypy` passes clean across all seven
packages; `ruff check`/`ruff format --check` pass clean. Full detail,
including every bug found and fixed while producing these numbers:
`TEST_RESULTS.md`.

**Engineering quality** (`make ci`, exit 0): combined coverage 80.3%
(threshold 65%, `coverage.xml` generated), `bandit` 0 medium/high,
`pip-audit` clean after fixing 5 CVEs outright and individually accepting 9
with a written, verified reason each (`RISKS.md` #20), `docker compose
config` valid, all six application images build. Full detail:
`docs/phase-5-engineering-quality.md`.

## Quick-start instructions

Requires only Docker + Docker Compose — no paid services, no host Python/
Node/Java/Terraform.

```bash
cp .env.example .env
make demo        # docker compose up --build, then prints the service URLs
```

Other useful targets:

```bash
make test         # all seven service test suites, each against its own *_test database
make typecheck    # mypy, per service
make lint         # ruff check
make format       # ruff format
make migrate      # apply Alembic migrations
make smoke        # end-to-end order lifecycle + observability verification
make generate     # run the synthetic event generator against the live stack
make dq-report    # run the data-quality report against live MinIO data
make backfill     # Silver/Gold backfill and reprocessing tooling
make phase6-smoke # end-to-end data-platform smoke test (generate -> bronze -> silver -> gold -> dq-report)
make inspect-bronze / inspect-silver / inspect-gold / inspect-bronze-rejects / inspect-silver-rejects / inspect-late-events
                  # inspect MinIO data-lake prefixes from the command line
make forecast-run     # full demand-forecasting pipeline: generate -> prepare -> train both models -> evaluate -> select -> forecast
make forecast-smoke   # end-to-end forecasting smoke test, entirely local (no live MinIO/Kafka needed)
make forecast-inspect ARGS="forecast"  # inspect forecast output / metrics / selection / dataset
make test-failure-lab # the failure-lab service's own unit/API test suite
make phase8-smoke     # trigger all 10 failure-lab scenarios against the live stack, twice
make replay ARGS="--all"  # replay unreplayed dead letters (CLI, also a dashboard button since Phase 8)
make reset        # tear down containers and volumes for a clean slate
make logs         # tail all service logs

make setup-dev    # build the shared devtools image (once, or after editing it)
make coverage     # all seven suites w/ coverage, combined coverage.xml, threshold-enforced
make security     # bandit (SAST) + pip-audit (dependency CVEs)
make pre-commit   # pre-commit hooks against the whole tree
make docker-validate  # docker compose config
make docker-build     # build all six application images (incl. ops-dashboard, failure-lab)
make ci           # the full local gate: format-check, lint, typecheck, coverage, security, dashboard, docker

make dashboard-install / dashboard-lint / dashboard-format / dashboard-format-check
                  # ops dashboard: npm install / eslint / prettier --write / prettier --check
make dashboard-typecheck / dashboard-test / dashboard-build
                  # ops dashboard: tsc --noEmit / vitest run / production build
make dashboard-validate  # all of the above, in fail-fast order
make help         # list every target with its description
```

## Project Screenshots

![Grafana dashboard](docs/images/grafana-dashboard.png)

![Jaeger trace](docs/images/jaeger-trace.png)

![Swagger API](docs/images/swagger-api.png)

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
| Ops Dashboard | http://localhost:3001 |
| Failure Laboratory API (direct) | http://localhost:8004/docs |

## Repository structure

```
services/
  api-gateway/            FastAPI edge service (authn/z, rate limiting, proxy)
  order-service/           Order state machine, outbox, validator consumer
  inventory-service/       Stock, reservations, row-level locking
  fulfillment-orchestrator/ Saga engine, node scoring, payment sim, DLQ, replay
  event-contracts/         Shared Kafka helpers, schemas, logging/tracing/metrics setup
  data-platform/            Spark Bronze/Silver/Gold, DQ, generator, backfill, forecasting
  ops-dashboard/            React + TypeScript ops dashboard, nginx reverse proxy (Phase 7)
  failure-lab/              10 deterministic failure scenarios, trigger/reset API (Phase 8)
infra/docker/               Compose service configs (Grafana, Prometheus, MinIO, Redpanda, OTel,
                             devtools — the shared ruff/mypy/pytest/bandit/pip-audit/pre-commit image)
.github/workflows/           ci.yml — GitHub Actions, mirrors `make ci`
docs/                       Architecture, event catalog, data model, data pipeline, ADRs,
                             phase-5-engineering-quality.md, phase-7-ops-dashboard.md,
                             phase-8-failure-laboratory.md
scripts/                    compose_smoke_test.sh (make smoke), phase8_smoke_test.sh (make phase8-smoke)
docker-compose.yml, Makefile, .env.example, .pre-commit-config.yaml, .dockerignore
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
| [0006](docs/adrs/0006-forecasting-scope.md) | Demand forecasting: baseline first, lightweight secondary model |
| [0007](docs/adrs/0007-terraform-not-applied.md) | Terraform authored + validated, never applied |
| [0009](docs/adrs/0009-authn-authz.md) | Self-contained JWT + RBAC over a third-party IdP |
| [0010](docs/adrs/0010-node-scoring-and-saga-orchestration.md) | Node-scoring formula, direct-REST saga coordination |

Full index of all 10 ADRs: `docs/adrs/README.md`.

## Known limitations

- **Saga resume gap**: a crash between a successful remote reservation and
  the saga's local commit of that step leaves no local record — fails loudly
  rather than double-reserving or guessing. Accepted, not solved (`RISKS.md` #11).
- **`--once` mode's final Silver micro-batch can leave a real,
  non-self-healing reconciliation gap** (verified: doesn't clear even after
  25+ minutes past the watermark) — `Trigger.AvailableNow()` gives no
  guaranteed flush cycle for a watermark-gated stateful operator's last
  batch. Not source data loss (Bronze/Kafka still have it); recovered via
  `app.backfill silver --apply` (`RISKS.md` #22).
- **Single-instance-only gateway**: in-process rate limiting and per-process
  DB pooling, would not survive horizontal scaling without a shared backing
  store (`RISKS.md` #13).
- **Grafana and worker `/metrics` are unauthenticated** — fine for a local
  demo, first thing to change before any shared deployment (`RISKS.md` #14).
- **Custom saga orchestrator, not a proven framework** — less battle-tested
  than Temporal; a deliberate scope tradeoff (`RISKS.md` #8).
- **9 dependency CVEs accepted, not fixed** — mostly `starlette` (pulled in
  transitively by `fastapi==0.115.0`); the real fix needs a coordinated
  `fastapi`/`starlette` major-version upgrade across all four HTTP services,
  verified incompatible with the current pin and scoped as its own
  follow-up rather than a same-pass bump (`RISKS.md` #20).
- **Coverage is statement-only, not branch**, despite `pyproject.toml`
  declaring branch coverage on — each service's own test container lacks
  the repo-root `pyproject.toml` at collection time
  (`docs/phase-5-engineering-quality.md`).
- **Demand forecasting is bounded by synthetic data's realism**, and its
  recursive multi-step future-forecast rollout has no native multi-horizon
  head — step-to-step prediction error can compound across the horizon.
  Both documented, not glossed over (`docs/phase-6-demand-forecasting.md`
  'Limitations').
- **Ops dashboard now requires login** (Phase 9), but two of its four
  proxied backends — inventory-service and fulfillment-orchestrator — still
  accept unauthenticated requests directly, since those routes are also
  called by the real saga orchestrator/failure-lab with no user JWT to
  present; a real fix needs a second, broader service-to-service auth
  layer, out of this phase's documented (ADR 0009) scope (`RISKS.md`
  #25/#34). **Order listing is client-curated, not server-listed** (Order
  Service has no list-all endpoint), and three of the ten screens (Data
  Quality, Data Platform, part of Demand Forecasting) show clearly-labeled
  local mock data pending a real MinIO read API. All named, not glossed
  over, in `docs/phase-7-ops-dashboard.md` 'Limitations'. (DLQ replay is a
  working button as of Phase 8 — see below.)
- **No refresh-token rotation** — a JWT expires after 30 minutes and the
  user has to log in again; a deliberate simplification named in ADR
  0009's own consequences, not an oversight.
- **Failure lab's downstream-outage scenario simulates the outage
  in-process rather than actually stopping the container** (a real
  `docker compose stop` would affect every concurrent user of a shared dev
  environment) — the gateway's `/readyz` and the resulting dead-letter are
  still genuinely observed, not mocked (`RISKS.md` #32,
  `docs/phase-8-failure-laboratory.md`).

Full risk register, with status and mitigation for each: `RISKS.md`.

## Remaining roadmap

Phases 11 and 13 not yet started: AWS infrastructure in Terraform
(authored/validated only, per
[ADR 0007](docs/adrs/0007-terraform-not-applied.md)) and final
documentation/career deliverables. Phases 10 and 12 are partially done — a
coverage threshold landed in `docs/phase-5-engineering-quality.md`, but
load testing and an actual GitHub-hosted CI run remain open. Phase 7
(React/TypeScript ops dashboard) and Phase 8 (Failure laboratory) are done
— see `docs/phase-7-ops-dashboard.md`/`docs/phase-8-failure-laboratory.md`.
Phase 9 (Security hardening — dependency/SAST scanning plus JWT/RBAC) is
now fully done — see `DECISIONS.md` "Phase 9". Full scope per phase:
`PROJECT_STATUS.md`.

## License status

No `LICENSE` file exists yet. One is planned alongside the rest of the
documentation set in Phase 13.
