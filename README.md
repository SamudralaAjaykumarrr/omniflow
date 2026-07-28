# OmniFlow

[![CI](https://github.com/SamudralaAjaykumarrr/omniflow/actions/workflows/ci.yml/badge.svg)](https://github.com/SamudralaAjaykumarrr/omniflow/actions/workflows/ci.yml)

An event-driven retail order/inventory/fulfillment platform demonstrating
production-oriented distributed-systems and data-engineering practice —
safe concurrency, saga orchestration, a real event bus, and a
Bronze/Silver/Gold data pipeline — running entirely on a single machine
with no paid cloud services.

This is an original design, built solo as a portfolio project. It is not a
clone of, and does not use any proprietary design, branding, or business
information from, any real retailer, and it has never been deployed to AWS
or any other cloud (see "AWS infrastructure" below).

## Current implementation status

**All 13 roadmap phases are done and verified.** Phase 12's GitHub-hosted
CI run and Phase 13's documentation/career deliverables — the two items
that were still open as of Phase 11 — are both now complete; see "GitHub
Actions CI evidence" below and `PROJECT_STATUS.md` for the full phase-by-
phase log.

| Area | Status |
|---|---|
| Core domain (orders, inventory, API gateway) | Done |
| Event platform (Redpanda, saga orchestrator, DLQ, replay) | Done |
| Observability (structured logs, tracing, metrics, Grafana) | Done |
| Data platform (Spark Bronze/Silver/Gold, data quality, backfill) | Done |
| Demand forecasting (baseline + secondary model, measured comparison) | Done |
| Engineering quality (coverage threshold, security scanning, pre-commit) | Done |
| Ops dashboard (React/TypeScript, 10 screens) | Done |
| Failure laboratory (10 deterministic failure scenarios) | Done |
| JWT authentication + role-based authorization | Done |
| Load testing (k6, 5 profiles, real measured results) | Done |
| AWS infrastructure (Terraform, authored + validated, never applied) | Done |
| GitHub-hosted CI (real hosted run, not just local) | Done |
| Documentation, portfolio, and career deliverables (this pass) | Done |

Full phase-by-phase build log, including two branches that reused an
earlier phase number by coincidence (an engineering-quality pass and a
streaming-data-platform hardening pass — neither is the phase whose number
their branch name reused): `PROJECT_STATUS.md`.

## Verified proof points

Every number below comes from a command actually run against this repo
(`TEST_RESULTS.md`, `docs/project-evidence.md`) — nothing here is
estimated.

- **411 backend tests passing, 0 failing** across 7 suites (event-contracts,
  order-service, inventory-service, fulfillment-orchestrator, api-gateway,
  data-platform, failure-lab).
- **82 dashboard tests passing, 0 failing** (Vitest + React Testing
  Library, 19 files).
- **80.9% combined test coverage** across all 7 Python suites, against a
  65% enforced threshold.
- **0% HTTP-level failure rate** across all 5 k6 load-test profiles, up to
  68 combined peak virtual users.
- **33 hosted GitHub Actions runs**, including a genuine hosted-only
  failure caught and fixed, verified against GitHub's public API this
  session.
- **`terraform validate`: zero warnings** across all 13 modules + 2
  environments — authored and validated only, never applied.
- **23 containers** running concurrently on one 8-CPU/15Gi host without OOM.
- **10 deterministic failure scenarios**, each triggered through a real
  backend API and verified twice in a row against the live stack.

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
([ADR 0005](docs/adrs/0005-spark-local-mode.md)); a Failure Laboratory
service exercises 10 deterministic failure scenarios against the real
stack; Jaeger, Prometheus, and Grafana make the request/event path
observable; a React + TypeScript ops dashboard presents order/inventory/
saga/DLQ/pipeline-health state to an authenticated ops user. Full container,
sequence, failure-recovery, and AWS-mapping diagrams: `docs/architecture.md`;
external system view: `docs/system-context.md`.

## Service & technology map

| Service | Technology | Responsibility |
|---|---|---|
| `api-gateway` | FastAPI, JWT/RBAC | AuthN/Z, rate limiting, request proxy, OpenAPI |
| `order-service` | FastAPI, SQLAlchemy, Alembic, Postgres | Order state machine, idempotency, outbox |
| `inventory-service` | FastAPI, SQLAlchemy, Postgres | Stock, reservations, row-level locking |
| `fulfillment-orchestrator` | Python, Kafka consumer | Saga engine, node scoring, payment sim, DLQ, replay |
| `event-contracts` | Python (shared package) | Kafka helpers, schemas, logging/tracing/metrics setup |
| `data-platform` | PySpark, pandas, scikit-learn | Bronze/Silver/Gold pipeline, data quality, forecasting |
| `ops-dashboard` | React 19, TypeScript, Vite, nginx | Operator UI, 10 screens |
| `failure-lab` | FastAPI, Postgres | 10 deterministic failure scenarios, trigger/reset API |
| Redpanda | Kafka-protocol broker | Domain event bus + dead-letter topic |
| MinIO | S3-compatible object store | Bronze/Silver/Gold Parquet |
| Jaeger / Prometheus / Grafana | OpenTelemetry / TSDB / dashboards | Distributed tracing, metrics, visualization |
| Terraform | AWS provider | Authored + validated AWS target, never applied |

## Major engineering capabilities

- **Order lifecycle state machine** (`CREATED → VALIDATED →
  INVENTORY_PENDING → INVENTORY_RESERVED → FULFILLMENT_ASSIGNED →
  PROCESSING → SHIPPED`, plus `CANCELLED`/`FAILED`) with idempotent
  creation (`Idempotency-Key`) and optimistic-versioned transitions.
- **Row-locked inventory reservation** with a stock-check endpoint and
  fulfillment-node scoring — verified live: 10 threads racing for the last
  unit of stock, exactly 1 succeeds.
- **A custom saga orchestrator**: node scoring, deterministic payment
  simulation, compensation on failure, retry with backoff+jitter,
  dead-letter routing, and a replay CLI. A live compose run forcing a
  payment decline confirmed the released inventory reservation was
  actually restored in Postgres, not just marked failed.
- **Transactional outbox** on every event-producing service, so an event
  is never published without the state change that caused it having
  already committed ([ADR 0003](docs/adrs/0003-transactional-outbox.md)).
- **Two deliberate concurrency strategies** by contention profile: row-
  level locking for hot `inventory_stock` rows, optimistic `version`
  columns for low-contention `orders`
  ([ADR 0002](docs/adrs/0002-inventory-concurrency-control.md)).
- **Tracing that survives the Kafka boundary**: one Jaeger trace covers a
  single order across the gateway, order service, and every asynchronous
  saga step.
- **Sixteen real bugs found and fixed by actually running the system** —
  Spark scheduler starvation, a Structured Streaming metadata-visibility
  gap, a dedup watermark declared on the wrong timestamp column silently
  dropping valid rows, a recursive-forecast row-ordering bug caught by a
  regression test before it shipped, a malformed Kafka record that could
  crash any consumer forever, a saga-resume startup crash, a dead-letter
  replay tool that had never actually worked, and more — full writeups in
  `DECISIONS.md`.

## Data platform and forecasting

PySpark Structured Streaming (`local[*]`, single-node) reads all 11
event-catalog topics into Bronze (immutable raw Parquet, malformed records
quarantined rather than written with null fields), validates and
deduplicates into Silver (rejects and late events routed to their own
paths, never dropped silently), and aggregates into 10 Gold datasets. A
pandas/scikit-learn forecasting pipeline (no Spark/JVM needed) evaluates a
`HistGradientBoostingRegressor` secondary model against a seasonal-naive
baseline on a deterministic synthetic demand history, using chronological
(never random) evaluation — the secondary model genuinely beat the
baseline on this session's smoke run (WAPE 0.154 vs. 0.298) and was
selected champion by a documented rule. Also included: an executable
data-quality suite (reconciliation, rejection rate, duplicate rate,
lateness, freshness) with a JSON report, batch backfill/reprocessing
tooling with row-count validation, and a MinIO data-lake inspection CLI.
Full design: `docs/data-pipeline.md`, `docs/phase-6-streaming-data-platform.md`,
`docs/phase-6-demand-forecasting.md`,
[ADR 0006](docs/adrs/0006-forecasting-scope.md).

## Security model

Self-contained JWT auth + role-based access control
([ADR 0009](docs/adrs/0009-authn-authz.md)) — no external identity
provider. api-gateway owns a `users` table (bcrypt-hashed passwords) and
issues short-lived signed JWTs (`POST /auth/login`); every protected route
verifies signature, issuer, audience, and expiration before checking a
ranked role (`viewer < ops < admin`). Enforced on api-gateway's
customer-facing proxy routes and failure-lab's trigger/reset routes — the
two surfaces ADR 0009 names; `/healthz`/`/readyz`/`/metrics` stay public
everywhere. Three demo accounts are seeded idempotently at every
api-gateway startup (dev-only passwords in `.env.example`). Deliberately
**not** extended to inventory-service/fulfillment-orchestrator's own
routes — see `RISKS.md` #25/#34. 52 backend tests cover the token
lifecycle and the 401-vs-403 boundary, including every negative-token case.

## Reliability and failure-laboratory summary

10 deterministic failure scenarios (`services/failure-lab`), each
triggered through a real backend API and exercised against the real
running stack — never simulated only in the browser — covering saga
compensation, retry/backoff, row-level-lock concurrency, request- and
event-level idempotency, dead-letter routing, Bronze/Silver data quality,
and saga crash-resume. Verified twice in a row against the live stack
(`make phase8-smoke`). Trigger/observe/reset flow diagram:
`docs/architecture.md`. Known, accepted gap: the saga resume gap between a
successful remote reservation and its local commit (`RISKS.md` #11).

## Observability summary

Structured JSON logs with `correlation_id` on every line; OpenTelemetry
tracing pushed to Jaeger with trace context carried across the Kafka
boundary in the event envelope itself; Prometheus metrics pulled from
every FastAPI service, every background worker, and every Spark
bronze/silver/gold job; a provisioned Grafana dashboard (request rate/
latency, Kafka lag/retries/DLQ, saga duration, DB pool).

## Test and quality evidence

| Suite | Passed | Failed |
|---|---|---|
| event-contracts | 59 | 0 |
| order-service | 37 | 0 |
| inventory-service | 23 | 0 |
| fulfillment-orchestrator | 41 | 0 |
| api-gateway | 30 | 0 |
| data-platform | 145 | 0 |
| failure-lab | 76 | 0 |
| **Backend total** | **411** | **0** |
| Dashboard (Vitest, 19 files) | 82 | 0 |

Combined coverage **80.9%** (`coverage.xml`, 65% threshold enforced);
`mypy` passes clean across all 7 packages; `ruff check`/`ruff format
--check` pass clean; `bandit` 0 medium/high; `pip-audit` clean after fixing
5 CVEs outright and individually justifying 9 accepted ones (`RISKS.md`
#20). Full detail, including every bug found while producing these
numbers: `TEST_RESULTS.md`.

## Load-testing evidence

k6 (`k6/`) against the real `api-gateway` container, five profiles —
smoke, baseline, load, stress, spike — each with explicit, enforced
thresholds for error rate and p95/p99 latency, real JWT login, and a real
end-to-end order → fulfillment-saga workflow polled to `SHIPPED`. All five
passed for real: **0% HTTP-level failure rate at every scale tested**;
`load` profile sustained 28.70 req/s (1,520 requests, p95 292.9ms);
`stress` reached 68 combined peak VUs (2,106 requests, p95 699.0ms) with
0% failures. The honest finding, not hidden: end-to-end saga completion
degrades under real backlog pressure (100% at smoke/baseline/load, 75% at
stress, 50% at spike) — the measured single-instance saga-consumer
throughput ceiling, well before any HTTP-level failure appears. Full
detail: `docs/phase-10-load-testing.md`, `docs/project-evidence.md`.

## GitHub Actions CI evidence

`.github/workflows/ci.yml` (job `quality-gate`) mirrors `make ci`
job-for-job on a free `ubuntu-latest` runner. Verified against GitHub's
public Actions API this session: **33 total hosted runs**, going back to
Phase 5. The Phase 12 hardening branch shows a genuine hosted-only failure
(runs #29/#30 on commit `7fdd9ec`) caught and fixed within that same
branch (runs #31/#32 on commit `375ea9e`), and the merge to `main`
(`e402f37`, run #33) is green. Full run table: `TEST_RESULTS.md`.

## AWS infrastructure (Terraform)

Per [ADR 0007](docs/adrs/0007-terraform-not-applied.md): realistic,
modular Terraform under `infra/terraform/` (13 modules + `dev`/`prod`
environments) mapping the running stack onto ECS Fargate (all 13
application deployables), RDS PostgreSQL, MSK (managed Kafka, IAM auth),
S3 (replacing MinIO, same prefix layout), EMR Serverless (Spark
bronze/silver/gold), ElastiCache Redis (modeled, not yet consumed by app
code), an ALB with host-based routing, least-privilege IAM per service,
Secrets Manager for every credential, and CloudWatch for logs/metrics/
alarms — **authored and validated only**: `terraform fmt -check
-recursive`, `terraform init -backend=false`, and `terraform validate` all
pass with **zero warnings**, run through the official `hashicorp/
terraform` Docker image. **No AWS credentials were used, no AWS API was
called, and nothing here has ever been planned, applied, or paid for.**
Full architecture and every documented limitation: `infra/terraform/README.md`.

## Quick-start instructions

Requires only Docker + Docker Compose — no paid services, no host Python/
Node/Java/Terraform.

```bash
cp .env.example .env
make demo        # docker compose up --build, then prints the service URLs
```

A curated list of every other `make` target (tests, data platform,
forecasting, load testing, Terraform validation, dashboard tooling) is
available via `make help`, and is unchanged in scope from prior phases —
see `PROJECT_STATUS.md` for the full history of when each target was added.

## Demo workflow

For a time-boxed, reliable walkthrough (5-minute and 15-minute paths,
demo accounts, troubleshooting, and an explicit "never run" list): see
`docs/demo-guide.md`.

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
  ops-dashboard/            React + TypeScript ops dashboard, nginx reverse proxy
  failure-lab/              10 deterministic failure scenarios, trigger/reset API
k6/                         Load-test scripts — scenarios.js + lib/{config,auth,ids,profiles}.js
infra/docker/               Compose service configs (Grafana, Prometheus, MinIO, Redpanda, OTel,
                             devtools — the shared ruff/mypy/pytest/bandit/pip-audit/pre-commit image)
infra/terraform/            AWS infrastructure — 13 modules (networking, security, ecr, iam,
                             secrets, rds, elasticache, msk, s3, alb, ecs, emr, observability) +
                             dev/prod environments; authored + validated only, never applied (ADR 0007)
.github/workflows/           ci.yml — GitHub Actions, mirrors `make ci`, real hosted run history
docs/                       Architecture, event catalog, data model, data pipeline, ADRs,
                             portfolio-case-study.md, demo-guide.md, interview-guide.md,
                             career-deliverables.md, project-evidence.md, phase-*.md
scripts/                    compose_smoke_test.sh, phase8_smoke_test.sh, load_test_setup.sh
docker-compose.yml, Makefile, .env.example, .pre-commit-config.yaml, .dockerignore, LICENSE
PROJECT_STATUS.md, RISKS.md, DECISIONS.md, TEST_RESULTS.md, CONTRIBUTING.md
```

## Key design decisions

| ADR | Decision |
|---|---|
| [0001](docs/adrs/0001-redpanda-over-kafka.md) | Redpanda over Apache Kafka |
| [0002](docs/adrs/0002-inventory-concurrency-control.md) | Row-locking vs. optimistic versioning, by contention profile |
| [0003](docs/adrs/0003-transactional-outbox.md) | Transactional outbox over CDC/Debezium |
| [0004](docs/adrs/0004-custom-saga-orchestrator.md) | Custom lightweight saga orchestrator over Temporal/Airflow |
| [0005](docs/adrs/0005-spark-local-mode.md) | PySpark Structured Streaming, single-node `local[*]` |
| [0006](docs/adrs/0006-forecasting-scope.md) | Demand forecasting: baseline first, lightweight secondary model |
| [0007](docs/adrs/0007-terraform-not-applied.md) | Terraform authored + validated, never applied |
| [0008](docs/adrs/0008-monorepo-layout.md) | Monorepo layout and service boundaries |
| [0009](docs/adrs/0009-authn-authz.md) | Self-contained JWT + RBAC over a third-party IdP |
| [0010](docs/adrs/0010-node-scoring-and-saga-orchestration.md) | Node-scoring formula, direct-REST saga coordination |

Full index of all 10 ADRs: `docs/adrs/README.md`. Deeper narrative on
trade-offs and hardest problems: `docs/portfolio-case-study.md`.

## Known limitations

- **Saga resume gap**: a crash between a successful remote reservation and
  the saga's local commit of that step leaves no local record — fails
  loudly rather than double-reserving or guessing (`RISKS.md` #11).
- **Single-instance-only gateway**: in-process rate limiting and
  per-process DB pooling, would not survive horizontal scaling without a
  shared backing store (`RISKS.md` #13).
- **Grafana and worker `/metrics` are unauthenticated** — fine for a local
  demo, first thing to change before any shared deployment (`RISKS.md` #14).
- **Custom saga orchestrator, not a proven framework** — less
  battle-tested than Temporal; a deliberate scope trade-off (`RISKS.md` #8).
- **9 dependency CVEs accepted, not fixed** — mostly `starlette`; the real
  fix needs a coordinated `fastapi`/`starlette` major-version upgrade,
  scoped as its own follow-up (`RISKS.md` #20).
- **Coverage is statement-only, not branch**, despite `pyproject.toml`
  declaring branch coverage on (`docs/phase-5-engineering-quality.md`).
- **Demand forecasting is bounded by synthetic data's realism**, and its
  recursive rollout has no native multi-horizon head
  (`docs/phase-6-demand-forecasting.md` "Limitations").
- **Two of the dashboard's proxied backends** (inventory-service,
  fulfillment-orchestrator) still accept unauthenticated requests directly
  — a real fix needs a second, broader service-to-service auth layer
  (`RISKS.md` #25/#34). Three of ten dashboard screens show clearly-
  labeled local mock data pending a real MinIO read API.
- **No refresh-token rotation** — a deliberate simplification, not an
  oversight (ADR 0009).
- **Failure lab's `downstream-outage` scenario simulates the outage
  in-process** rather than stopping the real container (`RISKS.md` #32).
- **Load-test numbers are laptop/Docker-Desktop measurements**, not a
  cloud-scale capacity claim (`RISKS.md` #36-#38).
- **Terraform has never been applied** — authored and validated only.
  Deploying it for real would additionally need an out-of-band ACM
  certificate + DNS, a manual per-service-database bootstrap step, an
  nginx DNS-resolver change, an S3 IAM-role auth fallback, and a
  distributed tracing backend (`RISKS.md` #39-#43,
  `infra/terraform/README.md`).

Full risk register, with status and mitigation for each: `RISKS.md`.

## Future production-readiness work

The concrete next steps named throughout this project's own risk register:
close the saga resume gap with reservation idempotency keys, horizontally
scale the saga consumer, move rate limiting/connection pooling to a shared
backing store, complete the `fastapi`/`starlette` upgrade, extend
authentication to the two remaining internal services, and actually deploy
the Terraform after closing its named AWS-specific gaps. Full list:
`docs/portfolio-case-study.md` "What would change for a real production
deployment".

Separately, and **not yet started**: an optional future capstone,
"OmniFlow Verifiable Production Readiness Lab" — possible scope includes
OpenTelemetry end-to-end tracing, resilience certification, policy as
code, software supply-chain security, and automated production-readiness
evidence reports. This is documented here as a possible future direction
only; none of it exists in this repository today.

## Documentation index

| Doc | Covers |
|---|---|
| `CONTRIBUTING.md` | Environment setup, standing project rules, engineering conventions |
| `PROJECT_STATUS.md` | Phase-by-phase build log — what exists, what's next |
| `RISKS.md` | Full risk register with status and mitigation |
| `DECISIONS.md` | Chronological decisions log, newest first |
| `TEST_RESULTS.md` | Raw test/coverage/load/CI/Terraform command output |
| `docs/architecture.md` | Container, sequence, failure-recovery, and AWS-mapping diagrams |
| `docs/system-context.md` | External system-context view |
| `docs/event-catalog.md` | All 11 event types, schema versioning rules |
| `docs/data-model.md` | Database schema, cross-service reference integrity |
| `docs/data-pipeline.md` | Bronze/Silver/Gold design, watermarks, backfill |
| `docs/product-requirements.md` | Business scenario, functional/non-functional requirements |
| `docs/adrs/` | All 10 architecture decision records |
| `docs/phase-*.md` | Phase-specific deep detail (engineering quality, forecasting, streaming, dashboard, failure lab, load testing) |
| `docs/portfolio-case-study.md` | Engineering case study — problem, trade-offs, hardest problems, lessons |
| `docs/demo-guide.md` | Time-boxed recruiter/interviewer demo walkthrough |
| `docs/interview-guide.md` | Talking points at multiple depths, anticipated questions |
| `docs/career-deliverables.md` | Résumé bullets, recruiter/LinkedIn copy, skills keywords |
| `docs/project-evidence.md` | Traceable capability → validation → result table |
| `infra/terraform/README.md` | AWS architecture, validation evidence, limitations |

## License

MIT — see `LICENSE`.
