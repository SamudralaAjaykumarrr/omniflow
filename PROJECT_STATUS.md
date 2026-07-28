# Project Status

Last updated: 2026-07-27 (Phase 13, final documentation/portfolio/career
deliverables, complete — see notes below). **All 13 roadmap phases are
now done.**

## Current phase

**Phase 13 (final documentation, portfolio, and career deliverables)
complete.** Closed the documentation staleness left over from Phase 11
(this document, `RISKS.md`, `DECISIONS.md`, `TEST_RESULTS.md`, and
`README.md` had not been updated since Phase 11, so they still described
Phase 12's CI as local-only even after it was verified on GitHub-hosted
runners), fixed six broken relative doc links (`docs/reliability.md` and
`docs/testing-strategy.md` were referenced from several files but never
existed — redirected to `RISKS.md`, `docs/data-pipeline.md`, and
`TEST_RESULTS.md`, whichever actually held that content), added the
`failure-lab`/`lag_poller` containers and a failure/recovery-flow diagram
to `docs/architecture.md` (both were real, running services the container
diagram had never been updated to include, since Phase 8/4), added a root
`LICENSE` (MIT), and created five new documents: `docs/portfolio-case-
study.md`, `docs/demo-guide.md`, `docs/interview-guide.md`,
`docs/career-deliverables.md`, and `docs/project-evidence.md`. `README.md`
was restructured for a recruiter-first opening while keeping every
existing verified claim. No application/service code was touched — this
phase is documentation-only, per its own scope. Closes `RISKS.md` #6
(cross-document consistency drift).

**Phase 12 (CI/CD) complete and verified — a real GitHub-hosted CI run
confirmed.** `.github/workflows/ci.yml`'s single `quality-gate` job
(checkout, `make format-check`, `lint`, `typecheck`, `setup-dev`,
`coverage`, `pre-commit`, `security`, `dashboard-validate`,
`docker-validate`, `docker-build` — job-for-job identical to `make ci`) has
a real hosted run history on GitHub Actions: 33 total runs as of this
session, going back to Phase 5. The `phase-12-github-hosted-ci` branch
itself surfaced two genuine hosted-only failures — runs #29/#30 on commit
`7fdd9ec` (`conclusion: failure`) — fixed by commit `375ea9e` (runs
#31/#32, `conclusion: success`), and the merge to `main` (commit `e402f37`,
run #33) is green. Verified directly against GitHub's public Actions API
in this session, not assumed from the PR having merged. Full detail:
`docs/phase-5-engineering-quality.md` (workflow authorship), `TEST_RESULTS.md`.

**Phase 11 (AWS infrastructure, Terraform) complete and verified — authored
and validated only, never applied (ADR 0007).** Realistic, modular
Terraform under `infra/terraform/` (13 modules + `dev`/`prod` environments)
mapping the full running stack onto ECS Fargate (all 13 application
deployables), RDS PostgreSQL, MSK (IAM-auth managed Kafka), S3, EMR
Serverless (Spark bronze/silver/gold, per ADR 0005's own named cloud
target), ElastiCache Redis (modeled, not yet consumed by app code — see
`RISKS.md` #13), an ALB, least-privilege IAM, Secrets Manager, and
CloudWatch observability. `terraform fmt -check -recursive`,
`terraform init -backend=false`, and `terraform validate` all pass with
zero warnings, run through the official `hashicorp/terraform` Docker image
— no AWS credentials used, no AWS API called, nothing planned/applied/
destroyed. Full detail: `infra/terraform/README.md`.

**Phase 10 (load testing) complete and verified.** k6 load/performance
testing (branch `phase-10-load-testing`) against the real running stack:
real login through `POST /auth/login`, real order creation/retrieval, real
inventory lookups, real concurrent order submissions, and a real end-to-end
order → fulfillment-saga workflow (poll to `SHIPPED` through the real
gateway) — five profiles (smoke/baseline/load/stress/spike), each with
explicit, enforced thresholds (error rate, p95/p99 latency, throughput),
all passing for real against this session's live `docker compose` stack.
Full detail: `docs/phase-10-load-testing.md`.

**Phase 9 (JWT/RBAC finalization) complete and verified.** Self-contained
JWT authentication + role-based authorization (ADR 0009): a real `users`
table (bcrypt-hashed passwords) in a new api-gateway database, short-lived
signed JWTs with issuer/audience/expiry/signature all verified, and
`viewer`/`ops`/`admin` role enforcement (401 vs. 403, correctly
distinguished) on api-gateway's customer-facing proxy routes and
failure-lab's scenario trigger/reset routes — the two surfaces ADR 0009
itself names. The ops dashboard gained a real login screen and role-aware
UI. Dependency/SAST scanning, the other slice of Phase 9's original scope,
already landed in Phase 5. Full detail: `DECISIONS.md` "Phase 9".

Phase 8 (Failure laboratory) complete and verified. Ten deterministic
failure scenarios, each triggerable through a real backend API
(`services/failure-lab`, a new service) and exercised against the real
running stack — no scenario is a UI-only simulation. Replaces the Phase 7
inert preview screen with a working control panel. Full detail:
`docs/phase-8-failure-laboratory.md`.

Phase 7 (Ops dashboard) complete and verified. React + TypeScript
single-page app (`services/ops-dashboard`), 10 screens, served by nginx as
a new `ops-dashboard` Compose service. Full detail:
`docs/phase-7-ops-dashboard.md`.

Phase 6 (Demand forecasting) complete and verified. Data quality
checks/reporting (originally slotted as a separate Phase 5) were folded into
Phase 4 — see below.

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
name reused "Phase 6" from the table below by coincidence — the platform
this branch hardens was built in Phase 4, not this branch. Full detail:
`docs/phase-6-streaming-data-platform.md`.

**Demand forecasting** (branch `phase-6-demand-forecasting`) — **this is
the table's actual Phase 6** — has landed: a deterministic synthetic
demand-history generator (SKU x location x date grain), feature
engineering with tested leakage safeguards, a seasonal-naive baseline, a
`HistGradientBoostingRegressor` secondary model, chronological (never
random) train/validation splitting plus rolling-origin walk-forward folds,
MAE/RMSE/WAPE computed from real predictions, a documented measured
champion-selection rule, recursive multi-step future forecasts, local
model-artifact persistence (bind-mounted across separate container runs),
a full CLI (`python -m app.forecasting.cli`), 12 new `make forecast-*`
targets, 91 new tests, and an end-to-end local smoke test
(`make forecast-smoke`) needing no live MinIO/Kafka. Full detail:
`docs/phase-6-demand-forecasting.md`.

## Phase progress

| Phase | Status | Notes |
|---|---|---|
| 0. Planning artifacts | Done | Product requirements, architecture, event catalog, data model, data pipeline design, 9 ADRs, tracking files, README/CONTRIBUTING.md |
| 1. Core domain | **Done** | Postgres + Alembic, Order Service, Inventory Service, API Gateway — see `TEST_RESULTS.md` |
| 2. Event platform | **Done** | Redpanda, outbox relays, event-contracts Kafka helpers, order-service validator consumer, fulfillment-orchestrator saga (node scoring, payment sim, compensation, retry+jitter, DLQ, replay) — see below and `TEST_RESULTS.md` |
| 3. Observability | **Done** | Structured JSON logs w/ correlation IDs, OpenTelemetry distributed tracing (Jaeger, cross-Kafka-hop trace propagation), Prometheus metrics (every service + every background worker), Grafana dashboard, mypy type checking — see below and `TEST_RESULTS.md` |
| 4. Data engineering platform | **Done** | Spark bronze/silver/gold into MinIO, synthetic generator, backfill/reprocessing tooling — see below and `TEST_RESULTS.md` |
| 5. Data quality | **Done** | Executable checks + report — folded into Phase 4 (`app.dq`), see below |
| 6. Demand forecasting | **Done** | Synthetic data, seasonal-naive baseline, `HistGradientBoostingRegressor` secondary model, chronological evaluation, champion selection, future forecasts — see below and `TEST_RESULTS.md` |
| 7. Ops dashboard | **Done** | React + TypeScript, 10 screens, nginx reverse proxy, no backend changes — see below and `docs/phase-7-ops-dashboard.md` |
| 8. Failure laboratory | **Done** | 10 deterministic failure scenarios, new `failure-lab` service, dashboard control panel — see below and `docs/phase-8-failure-laboratory.md` |
| 9. Security hardening | **Done** | Dependency/SAST scanning (bandit + pip-audit) — see `docs/phase-5-engineering-quality.md`; JWT/RBAC (users table, bcrypt, role-ranked authorization, 401/403 boundary) — see below and `DECISIONS.md` "Phase 9" |
| 10. Testing completion + load test | **Done** | Coverage threshold (65%, measured 71.6%) + `coverage.xml` — see `docs/phase-5-engineering-quality.md`; k6 load testing (5 profiles, real measured results) — see below and `docs/phase-10-load-testing.md` |
| 11. AWS infrastructure (Terraform) | **Done** | Authored + validated (`fmt`/`init -backend=false`/`validate`, zero warnings), never applied — see below and `infra/terraform/README.md` |
| 12. CI/CD | **Done** | `.github/workflows/ci.yml` (job `quality-gate`) verified both locally (`make ci`) and by a real GitHub-hosted run — 33 total runs, Phase 12 branch shows a hosted-only failure caught and fixed, final merge to `main` green — see above and `docs/phase-5-engineering-quality.md` |
| 13. Documentation & career deliverables | **Done** | README rewrite, portfolio case study, demo guide, interview guide, career deliverables, project evidence, LICENSE, architecture-doc consistency pass — see above |

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
- `README.md`, `CONTRIBUTING.md`
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
- **Phase 6 application code** (branch `phase-6-demand-forecasting`, see
  `docs/phase-6-demand-forecasting.md` for full detail):
  - `services/data-platform/app/forecasting/` — **new package**: a
    pandas/scikit-learn batch pipeline (no Spark/JVM needed), grain SKU x
    location x date:
    - `synthetic.py` — deterministic seeded generator (trend, weekly/annual
      seasonality, promos, stockouts, intermittent demand, rare anomalies,
      a small generic holiday calendar)
    - `features.py`/`quality.py` — calendar/lag/rolling feature engineering
      with tested leakage safeguards, plus data-quality checks (grain
      duplicates, missing/negative target, insufficient history, gaps,
      all-zero series, split ordering, feature-leakage safeguard)
    - `splits.py` — chronological single-cutoff split + expanding-window
      rolling-origin walk-forward folds (never a random shuffle split)
    - `baseline.py` (`SeasonalNaiveModel`) / `secondary_model.py`
      (`HistGradientBoostingRegressor` wrapper) — same `fit`/`predict`
      interface, evaluated uniformly
    - `metrics.py` — MAE/RMSE/WAPE (WAPE chosen over MAPE for this
      dataset's genuine zero-demand rows); `evaluate.py` — overall/by-SKU/
      by-location/by-horizon breakdowns
    - `select.py` — documented, measured champion-selection rule
    - `forecast.py` — recursive multi-step future-forecast rollout (a real
      row-ordering bug found by a dedicated regression test and fixed
      before shipping — `RISKS.md` #23)
    - `artifacts.py` — local joblib model + JSON metadata persistence
      (training range, feature list, run ID)
    - `io.py`/`paths.py` — local-or-MinIO Parquet/JSON I/O and the stable
      `forecasting/` MinIO path layout
    - `cli.py` — `generate-history`/`prepare`/`train-baseline`/
      `train-secondary`/`evaluate`/`select`/`forecast`/`validate`/
      `inspect`/`run` subcommands
  - `app/config.py` — `forecasting_path` property added
  - `infra/docker/minio/create-buckets.sh` — `forecasting` prefix added
  - `docker-compose.yml` — `spark-gold` gained a bind-mounted
    `forecasting_artifacts` volume (local model artifacts must survive
    across separate `docker compose run` invocations of the granular
    `make forecast-*` targets — verified directly, not assumed)
  - `services/data-platform/requirements.txt` — `pandas`, `numpy`,
    `scikit-learn`, `joblib` added (ADR 0006: pure-Python-wheel, no
    compiled-system-toolchain dependencies)
  - `scripts/forecast_smoke_test.sh` — **new**: every forecasting CLI
    subcommand run in sequence against a small deterministic config,
    redirected to a local scratch dir — no live Redpanda/MinIO/Postgres
    needed, unlike `phase6_smoke_test.sh`
  - `Makefile` — `forecast-generate-data`, `forecast-prepare`,
    `forecast-train-baseline`, `forecast-train-model`, `forecast-evaluate`,
    `forecast-select`, `forecast-run`, `forecast-inspect`, `forecast-test`,
    `forecast-smoke`, `forecast-clean-safe`, `forecast-validate` targets
    added; `typecheck` extended with `pandas`/`numpy`/`scikit-learn`/
    `joblib` (a real gap found running it: mypy resolved a different,
    unpinned transitive numpy version without this, producing 7 spurious
    errors)
  - 272 passing tests across six suites (data-platform grew from 54 to
    145 — 91 new forecasting tests) — see `TEST_RESULTS.md` for the full
    breakdown; combined coverage rose from 71.1% to 73.4%

- **Phase 7 application code** (branch `phase-7-ops-dashboard`, see
  `docs/phase-7-ops-dashboard.md` for full detail):
  - `services/ops-dashboard` — **new service**: Vite + React 19 + TypeScript
    single-page app, `react-router-dom` v7 (plain client-side mode — no
    RSC/SSR/data-router loaders), 10 screens (Overview, Orders + detail,
    Inventory & Fulfillment Nodes, Saga Monitor, Dead Letter Queue,
    Observability, Data Quality, Data Platform, Demand Forecasting, Failure
    Laboratory preview)
  - `src/api/` — typed client (`client.ts`'s `get`/`post` + `ApiError`/
    `NetworkError`) hand-mirroring the real Pydantic response models from
    order-service/inventory-service/fulfillment-orchestrator; `metrics.ts`
    wraps Prometheus's own HTTP query API; `mock/` holds clearly-labeled
    fallback fixtures (DQ report, Gold datasets, forecast curve, failure-lab
    catalog) for the three screens with no browser-facing read API yet
  - `src/hooks/useAsync.ts` — shared loading/error/success/polling hook used
    by every screen; `useTrackedOrders.ts` — localStorage-backed order-ID
    tracking (Order Service has no list-all endpoint, confirmed before
    building anything — see `docs/phase-7-ops-dashboard.md`)
  - `src/components/` — layout (`AppShell`/`Sidebar`/`TopBar`), common
    (`StatCard`, `StatusBadge`, `DataTable`, `LoadingState`/`EmptyState`/
    `ErrorState`, `MockDataNotice`, hand-rolled SVG `BarChart`/`LineChart`
    per the dataviz-skill palette/marks/interaction rules), forms
    (`CreateOrderForm`, `CancelOrderForm`, `StockCheckForm`)
  - `nginx.conf`/`proxy_params.conf` — reverse-proxies `/gw/`,
    `/inventory-api/`, `/orchestrator-api/`, `/prom-api/` to the real
    containers on the Compose network, same-origin (no backend CORS
    changes needed); proxy targets resolved via Docker's embedded DNS at
    **request time** (`resolver 127.0.0.11` + a `set $upstream_x ...`
    variable per location), not once at nginx startup — three real bugs
    found and fixed, the second and third only by actually running the
    full stack: (1) a bare `proxy_pass http://api-gateway:8000/;` makes
    nginx refuse to start at all if that hostname isn't resolvable yet,
    which would take down the static SPA too over one not-yet-ready
    dependency; (2) once live against real upstreams, the variable form
    doesn't auto-strip a location's matched prefix the way a literal one
    does, so every proxied request 404'd until each location got its own
    `rewrite ... break` (ordered *before* `set` — `break` halts every
    later rewrite-phase directive in the same location); (3) with (1) and
    (2) fixed and real traffic flowing, `docker compose ps` still reported
    the container unhealthy — nginx only binds IPv4 but this image's
    `wget` resolves `localhost` to `::1` first, so both the Dockerfile's
    `HEALTHCHECK` and `docker-compose.yml`'s overriding `healthcheck:`
    block needed to query `127.0.0.1` explicitly instead — see
    `docs/phase-7-ops-dashboard.md`/`RISKS.md` #27/`DECISIONS.md` for the
    full writeup
  - `Dockerfile` — multi-stage (`node:22-alpine` build, `nginx:1.27-alpine`
    serve)
  - `docker-compose.yml` — `ops-dashboard` service added, published on
    `3001` (`3000` is Grafana's), healthcheck, depends on
    api-gateway/inventory-service/fulfillment-orchestrator/prometheus all
    healthy
  - Root `.dockerignore` — **new** (excludes `node_modules/`, `dist/`,
    Python cache dirs from every service's build context)
  - `Makefile` — `dashboard-install`/`dashboard-lint`/`dashboard-format`/
    `dashboard-format-check`/`dashboard-typecheck`/`dashboard-test`/
    `dashboard-build`/`dashboard-validate` targets added, run inside
    `node:22-alpine` throwaway containers as the host UID/GID (no host
    Node, no root-owned generated files); `ci` and `docker-build` extended
    to include the dashboard
  - `.github/workflows/ci.yml` — dashboard quality-gate steps added,
    mirroring `make ci`'s new ordering
  - 50 new passing tests (vitest + React Testing Library, 14 files) — see
    `TEST_RESULTS.md`
  - No existing service's application code changed — every table/route/
    schema in Phases 1-6 is untouched; only `docker-compose.yml`,
    `Makefile`, `.github/workflows/ci.yml`, and the new root
    `.dockerignore` were touched outside `services/ops-dashboard/`
- **Phase 8 application code** (see `docs/phase-8-failure-laboratory.md`
  for full detail):
  - `services/failure-lab` — **new service**: FastAPI catalog/trigger/reset
    API (`GET /scenarios`, `POST /scenarios/{id}/trigger`, `GET /scenarios/
    {id}/runs/{run_id}`, `POST /scenarios/{id}/reset`), a background-thread
    runner (`app/runner.py`) with its own Postgres database
    (`omniflow_failure_lab`, `scenario_runs`/`scenario_resets`/
    `failure_lab_dead_letters`), and the 10 deterministic failure scenarios
    (`app/scenarios/`) — the exact catalog `services/ops-dashboard/src/api/
    mock/failureLab.ts` had already documented as the Phase 8 plan:
    payment-decline, payment-timeout, inventory-oversell-race,
    duplicate-order-submit, duplicate-event-delivery, poison-message-dlq,
    malformed-kafka-record, late-event-arrival, saga-crash-resume,
    downstream-outage. A dedicated worker (`app/poison_consumer.py`,
    docker-compose service `failure-lab-poison-consumer`) backs the
    poison-message scenario on its own chaos topic (`failure-lab.poison`,
    added to `infra/docker/redpanda/create-topics.sh`, not part of the
    11-topic domain event catalog).
  - Small, internal-only additions to existing services: order-service
    gained `GET /internal/failure-lab/processed-events/{event_id}`;
    inventory-service gained `app/outage.py` + `SimulatedOutageMiddleware`
    (`POST/GET /internal/failure-lab/outage/*`); fulfillment-orchestrator
    gained `POST /dead-letters/{id}/replay` (dead-letter replay over HTTP,
    not just the CLI) and `POST /internal/failure-lab/saga-crash-resume/
    {order_id}/resume`, plus a `CRASH_SIMULATION_SKU` marker in `app/
    saga.py`'s `advance_saga`.
  - **Four real bugs found and fixed** running this phase's scenarios and
    smoke test against a genuinely live stack (all documented in `RISKS.md`,
    status `Closed`): (1) `event_contracts.kafka.run_consume_loop` crashed
    any consumer forever on one malformed Kafka record (found via stale
    Phase 6 generator test data still sitting in a real topic); (2)
    `resume_incomplete_sagas` let one orphaned saga crash the whole
    orchestrator at every startup; (3) a transient failure on a saga's
    first `advance_saga` call left it stuck forever, invisible to both
    Kafka retry and the dead-letter path; (4) `app.replay.replay_one` had
    never actually worked against a real dead letter (`payload["original_
    event"]` vs. the real flat-envelope shape) — masked until now because
    every existing test built its own (wrongly-shaped) fixture instead of
    reusing the real code path.
  - `services/ops-dashboard` — `src/pages/FailureLabPage.tsx` rewritten to
    fetch the real catalog and trigger/reset scenarios (`src/api/
    failureLab.ts`, new); `src/api/mock/failureLab.ts` (the Phase 7 inert
    preview) deleted; `StatusBadge`'s tone mapping extended for
    `PASSED`/`RECOVERED`/`ERROR`.
  - `docker-compose.yml` — `failure-lab` (port `8004`) and
    `failure-lab-poison-consumer` services added; `infra/docker/postgres/
    init-databases.sql` gained `omniflow_failure_lab`(`_test`).
  - `Makefile` — `test-failure-lab`, `phase8-smoke`, `phase8-validate`,
    `clean-phase8` targets added; `test`/`typecheck`/`security`/
    `docker-build` extended to include `services/failure-lab`.
  - `scripts/phase8_smoke_test.sh` — **new**: triggers all 10 scenarios
    against the real running stack, asserts each reaches `PASSED`/
    `RECOVERED`, resets every scenario, then reruns all 10 a second time
    (proves safe-to-rerun for the whole catalog against a live stack, not
    just asserted in a test).
  - 359 passing backend tests across seven suites (event-contracts,
    order-service, inventory-service, fulfillment-orchestrator,
    api-gateway, data-platform, **failure-lab**) — see `TEST_RESULTS.md`
    for the full breakdown; 66 passing dashboard tests (was 50) — including
    a new working Replay button on the Dead Letter Queue screen (backed by
    the same `POST /dead-letters/{id}/replay` endpoint, closing a Phase 7
    "CLI-only" limitation).
- **Phase 9 application code** (JWT/RBAC finalization, ADR 0009 — see
  `DECISIONS.md` "Phase 9" for the full scope-boundary reasoning):
  - `services/event-contracts/event_contracts/auth.py` — **new shared
    module**: JWT encode/decode (PyJWT, HS256) with issuer/audience/
    expiration/signature all verified, a ranked `Role` (`viewer < ops <
    admin`), and `build_current_user_dependency`/`build_require_role_dependency`
    FastAPI-dependency factories reused by api-gateway and failure-lab —
    same "shared helper, per-service settings" pattern as
    `metrics_setup`/`logging_setup`/`tracing_setup`.
  - `services/api-gateway` — gained its own Postgres database
    (`omniflow_gateway`(`_test`), Alembic-migrated) and a `users` table
    (`app/models.py`, bcrypt-hashed passwords via `passlib`); `app/security.py`
    (password hashing + the gateway's own JWT dependencies); `app/seed.py`
    (idempotent demo-user seeding at startup: `admin`/`ops`/`viewer` +
    a scoped `ops`-role service account); `POST /auth/login`, `GET
    /auth/me` (`app/routes.py`); `POST/GET /api/orders*` now requires
    `ops`/`admin` for mutations, any authenticated role for reads; `GET
    /api/inventory/stock/*` requires any authenticated role.
    `/healthz`/`/readyz`/`/metrics` remain public.
  - `services/failure-lab` — `app/security.py` (JWT dependencies built
    from the same shared secret api-gateway signs with); `POST
    /scenarios/{id}/trigger`/`reset` now require `ops`/`admin`; the
    read-only catalog/run routes require any authenticated role.
    `app/clients.py`'s `GatewayClient` (the only caller of api-gateway's
    now-protected `POST /api/orders`) logs in as the seeded service
    account and caches the resulting token, refreshing it before expiry.
  - `services/ops-dashboard` — `src/pages/LoginPage.tsx` (new),
    `src/auth/` (`AuthContext.tsx`/`useAuth.ts`/`context.ts`/
    `RequireAuth.tsx`, new): sessionStorage-backed session, a route guard
    redirecting unauthenticated users to `/login`, and role-aware
    hide/disable on Create/Cancel Order and Failure Lab trigger/reset
    (client-side UI convenience, not the security boundary — the
    boundary is the backend's own 401/403). `src/api/client.ts` gained
    `Authorization: Bearer` header injection and a 401 handler that logs
    the session out.
  - **Scope boundary, deliberately not expanded**: order-service,
    inventory-service, and fulfillment-orchestrator's own HTTP routes
    remain unauthenticated at the service level — they're called directly
    by the real saga orchestrator and failure-lab's scenario runner with
    no user JWT to present, and protecting them would require a second,
    broader service-to-service auth layer ADR 0009 never scoped. See
    `RISKS.md` #25 (updated) and #34 (new) for the precise, named gap this
    leaves open (the dashboard's `/inventory-api/`/`/orchestrator-api/`
    proxies still reach those two services directly, unauthenticated).
  - `infra/docker/postgres/init-databases.sql` — `omniflow_gateway`(`_test`)
    added. `docker-compose.yml` — api-gateway gained `GATEWAY_DATABASE_URL`,
    `JWT_SECRET_KEY`/`JWT_ISSUER`/`JWT_AUDIENCE` (shared, not
    service-prefixed — symmetric HS256 signing needs the exact same
    secret on both the issuer and every verifier), and
    `GATEWAY_SEED_*_PASSWORD` env vars, all with documented dev-only
    defaults (no code-level fallback for the secret itself — see
    `.env.example`); failure-lab gained the same shared `JWT_SECRET_KEY`
    plus its own service-account login credentials.
  - `Makefile` — `test-gateway` now migrates + tests against
    `omniflow_gateway_test`; `migrate` extended to include api-gateway;
    `typecheck`'s pip-install list gained `pyjwt`/`passlib`/`bcrypt`.
  - 411 passing backend tests across seven suites (up from 359 — +21
    event-contracts, +21 api-gateway, +10 failure-lab) and 82 passing
    dashboard tests (up from 66, +16) — see `TEST_RESULTS.md` for the full
    breakdown, including every negative-token case required (expired,
    malformed, missing, wrong-signature, wrong-audience, wrong-issuer,
    insufficient-role) and the 401-vs-403 boundary verified both by
    automated tests and directly against the real running stack.
- **Phase 10 application code** (load testing — see
  `docs/phase-10-load-testing.md` for full detail):
  - `k6/scenarios.js` + `k6/lib/{config,auth,ids,profiles}.js` — **new**:
    one k6 script reused unchanged across five profiles
    (smoke/baseline/load/stress/spike, selected via a `PROFILE` env var),
    six workloads (auth login, order creation, order retrieval, inventory
    lookup, concurrent order submissions, an end-to-end order →
    fulfillment-saga workflow polled through the real gateway to
    `SHIPPED`), real JWT login via the seeded demo accounts, deterministic
    unique test data (`RUN_ID` + `__VU`/`__ITER`).
  - `scripts/load_test_setup.sh` — **new**: idempotent load-test data seed
    (one fulfillment node, 100 SKUs at 1,000,000 units each), stops the
    unrelated Spark streaming jobs before seeding (found dominating this
    host's CPU during an early run), waits for a previous run's saga
    backlog to drain.
  - `docker-compose.yml` — new `k6` service gated behind a `load-test`
    Compose profile (never starts on a plain `docker compose up`/
    `make demo`).
  - `Makefile` — `load-setup`/`load-smoke`/`load-baseline`/`load-test`/
    `load-stress`/`load-spike`/`load-validate`/`load-clean` targets added;
    every profile raises the gateway's rate limit for that run only
    (already an env-overridable setting), then restores the default.
  - All five profiles run for real against the live stack this session:
    0% HTTP-level failure rate and every declared threshold passed at
    every scale tested, up to 68 combined peak VUs (`stress`) — real
    measured numbers, real findings (a Makefile subshell bug, rate-limiter
    interaction, SKU-pool lock contention, Spark CPU contention, a
    Docker-DNS-hiccup-caused pair of dead letters recovered via the
    existing replay tooling), all documented in
    `docs/phase-10-load-testing.md`/`DECISIONS.md`/`RISKS.md` #36-#38.
  - No Phase 1-9 application code was touched.
- **Phase 11 application code** (AWS infrastructure, Terraform — see
  `infra/terraform/README.md` for full detail):
  - `infra/terraform/modules/` — **13 new modules**: `networking` (VPC, 2+
    AZ public/private subnets, NAT gateway(s), S3 gateway endpoint,
    ECR/Secrets Manager/CloudWatch Logs interface endpoints), `security`
    (security groups, ingress always scoped to a source SG, never a CIDR,
    except the ALB's own listener), `ecr` (7 repos, one per
    `services/<name>` image), `iam` (shared ECS task-execution role + one
    task role per logical service group, MSK IAM-auth permissions only for
    Kafka-touching services, S3 permissions only for `lag-poller`),
    `secrets` (Secrets Manager: JWT signing secret, seeded demo-user
    passwords, RDS master password, all Terraform-`random`-generated),
    `rds` (single PostgreSQL instance, Multi-AZ toggle, encrypted,
    automated backups), `elasticache` (Redis — modeled for `RISKS.md` #13's
    documented next step, not yet consumed by app code), `msk` (managed
    Kafka, IAM auth, replacing Redpanda), `s3` (data-lake bucket, same
    bronze/bronze_rejects/silver/silver_rejects/late_events/gold/
    checkpoints/dq-reports/forecasting prefixes as
    `infra/docker/minio/create-buckets.sh`), `alb` (host-based routing:
    default Host -> api-gateway, `dashboard_hostname` -> ops-dashboard —
    order-service/inventory-service/fulfillment-orchestrator/failure-lab
    stay internal-only, same posture as `RISKS.md` #25/#34), `ecs`
    (Fargate cluster, Cloud Map private DNS namespace, one task
    definition + service per deployable — 13 total, CPU-target-tracking
    autoscaling), `emr` (EMR Serverless application for Spark
    bronze/silver/gold, per ADR 0005's own named cloud target — never
    invoked, only the persistent application is provisioned),
    `observability` (CloudWatch alarms: ALB 5xx, ECS CPU/memory, RDS
    CPU/free storage, MSK broker disk; one dashboard; an SNS topic).
  - `infra/terraform/environments/{dev,prod}` — each with its own
    `main.tf` wiring every module, `services.tf` (the 13-deployable ECS
    map, mirroring `docker-compose.yml`'s own service list — workers reuse
    their parent service's image with a different `command`, exactly like
    Compose's own `command:` overrides), `database_secrets.tf` (composes
    one `DATABASE_URL` secret per service database from the single RDS
    master user/password, matching each service's existing single-env-var
    contract unchanged), `variables.tf`, `terraform.tfvars.example` (no
    real secrets), a local-only `backend.tf` (remote S3+DynamoDB backend
    documented, commented out, never created).
  - `Makefile` — `tf-fmt-check`/`tf-fmt`/`tf-init`/`tf-validate`/
    `tf-validate-all` targets added, all running the official
    `hashicorp/terraform:1.9` Docker image (no host Terraform install, no
    AWS credentials, no AWS API calls — `terraform init` does reach
    `registry.terraform.io` to download the `aws`/`random` provider
    plugins, called out plainly per ADR 0007). Deliberately not folded
    into `ci`/`pre-commit` — a new network dependency those targets have
    never had, out of this phase's scope to add.
  - `docs/architecture.md` — the AWS deployment-target diagram (a Phase 0
    sketch) updated to include failure-lab/ops-dashboard/EMR
    Serverless/lag-poller/Cloud Map, matching what actually landed in
    Phases 4-10, not just the original 4-service sketch.
  - **Real validation, run in this session**: `terraform fmt -check
    -recursive` clean; `terraform init -backend=false` succeeded for
    every one of the 13 modules + 2 environments; `terraform validate`
    passed with **zero warnings** for all 15 (one real S3 lifecycle-rule
    schema warning — a `filter`/`prefix` requirement newly enforced by a
    recent provider version — found and fixed during this same session,
    not left in). No `terraform plan` or `terraform apply` was run against
    any account; no AWS credentials exist in this session.
  - **Explicit, named limitations** (not silently assumed solved — full
    detail in `infra/terraform/README.md`): RDS creates only 1 of the 5
    logical databases at instance-creation time (a documented manual
    `psql` bootstrap step for the other 4); `ops-dashboard/nginx.conf`'s
    DNS resolver would need changing from Docker's `127.0.0.11` to the
    AWS VPC resolver `169.254.169.253` to actually proxy correctly in AWS;
    `data-platform/app/s3.py` would need a small fallback to authenticate
    to S3 via an ECS task's IAM role instead of explicit
    `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`; no distributed-tracing
    backend is wired up in AWS (CloudWatch replaces
    Jaeger/Prometheus/Grafana for logs/metrics/alarms only); EMR
    Serverless custom-image compatibility with the existing
    `services/data-platform` image was not verified. None of these are
    application-code changes made in this phase, per its "author
    Terraform only" scope.
  - No Phase 1-10 application code was touched.

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

All 13 roadmap phases are done. There is no further required scope on this
project's original roadmap. Optional, explicitly-not-yet-started future
work is documented separately in `README.md` "Future production-readiness
work" and `docs/portfolio-case-study.md` "What would change for a real
production deployment" — including a possible future capstone,
"OmniFlow Verifiable Production Readiness Lab" (OpenTelemetry end-to-end
tracing, resilience certification, policy as code, software supply-chain
security, automated production-readiness evidence reports), which is named
as a possible direction only and has no code or design in this repository
today.
