# Project Evidence

A traceable record of what was built, how each capability was validated, and
what the validation actually showed — every figure below comes from a
command run against this repository, not an estimate. Full narrative detail
lives in the phase-specific docs linked from each row; this table exists so a
reviewer can check a claim without reading all of them.

Cross-reference: `TEST_RESULTS.md` (raw command output), `RISKS.md`
(limitations in full), `PROJECT_STATUS.md` (phase-by-phase build log).

## Backend services

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| Order lifecycle state machine | `services/order-service/app` | `make test-order` | 37 passed, 0 failed | — |
| Inventory reservation, row-level locking | `services/inventory-service/app` | `make test-inventory`; live 10-thread race test | 23 passed, 0 failed; exactly 1 of 10 concurrent requests for the last unit succeeded | Row locking, not distributed-lock-safe across multiple DB instances (single Postgres instance only) |
| Saga orchestration (node scoring, payment sim, compensation, retry, DLQ, replay) | `services/fulfillment-orchestrator/app` | `make test-orchestrator`; live payment-decline compose run | 41 passed, 0 failed; compensation verified against real Postgres state, not just asserted in a test | Saga resume gap between a successful remote reservation and its local commit — `RISKS.md` #11, accepted not solved |
| API Gateway (authN/Z, rate limiting, proxy) | `services/api-gateway/app` | `make test-gateway` | 30 passed, 0 failed | Rate limiting and connection pooling are single-instance only — `RISKS.md` #13 |
| Shared Kafka/schema/logging/tracing/metrics helpers | `services/event-contracts` | `make test-contracts` | 59 passed, 0 failed | — |
| Transactional outbox (every event-producing service) | `app/outbox.py` + `app/outbox_relay.py` per service | Code review + integration tests; ADR 0003 | Outbox rows only removed after confirmed Kafka publish | At-least-once delivery, not exactly-once — deliberate, documented everywhere |

## Dashboard

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| React/TypeScript ops dashboard, 10 screens | `services/ops-dashboard` | `make dashboard-validate` (eslint, prettier, tsc, vitest, vite build) | 82 tests passed, 0 failed, 19 test files; clean lint/format/typecheck/build | 3 of 10 screens (Data Quality, Data Platform, forecast curve) show clearly-labeled local mock data pending a real MinIO read API — `RISKS.md` #26 |
| JWT login, role-aware UI | `src/auth/`, `src/pages/LoginPage.tsx` | Included in the 82-test suite; manual login as each seeded role against the live stack | Session persists across reload, route guard redirects unauthenticated users, role-gated buttons hide correctly | Client-side hide/disable is UI convenience only — the real boundary is the backend's 401/403 |

## Event-driven workflows

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| 11-topic domain event catalog, schema-versioned | `docs/event-catalog.md`, `services/event-contracts/event_contracts/schemas` | Contract tests (`services/event-contracts/tests/`) | Producer payloads validate against the last two published schema versions | — |
| Idempotent consumers (dedupe by `event_id`) | `processed_events` table per service | Duplicate-delivery tests per suite | Redelivery is a no-op, not a re-applied side effect | — |
| Dead-letter routing + replay | `app.consumer.dead_letter`, `app.replay` | `make replay ARGS="--all"` against real dead letters | Successfully replayed real dead letters left over from load-test DNS hiccups (`RISKS.md` #37) | — |

## Security

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| JWT auth (issuer/audience/expiry/signature verified) | `services/event-contracts/event_contracts/auth.py`, `services/api-gateway/app/security.py` | Automated tests + live login as `admin`/`ops`/`viewer` | Every negative-token case covered (expired, malformed, missing, wrong-signature, wrong-audience, wrong-issuer, insufficient-role); 401 vs. 403 verified against the real running stack | — |
| Role-ranked RBAC (`viewer < ops < admin`) | Same modules, `build_require_role_dependency` | Same tests | Enforced on api-gateway's customer-facing routes and failure-lab's trigger/reset routes — the two surfaces ADR 0009 names | inventory-service and fulfillment-orchestrator's own HTTP routes remain unauthenticated by deliberate scope decision — `RISKS.md` #25/#34 |
| Dependency/SAST scanning | `make security` (bandit + pip-audit) | Run as part of `make ci` | bandit: 0 medium/high; pip-audit: 5 CVEs fixed outright, 9 individually justified and accepted | `starlette` CVEs need a coordinated `fastapi` major-version bump, scoped as future work — `RISKS.md` #20 |

## Reliability

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| 10 deterministic failure scenarios | `services/failure-lab` | `make phase8-smoke` (all 10, twice in a row, against the live stack) | All 10 reach `PASSED`/`RECOVERED`, both runs | `downstream-outage` simulates the outage in-process rather than stopping the real container — `RISKS.md` #32 |
| Saga crash-resume | `app.saga.resume_incomplete_sagas` | `saga-crash-resume` scenario + dedicated regression tests | Orphaned sagas resume independently; one failing saga no longer crashes the whole consumer | Documented resume gap remains for the specific window described above |
| Real bugs found and fixed via live-stack testing | Various — see `RISKS.md` #21, #23, #27–#31 | Root-caused with regression tests added for each | 4 Phase 8 startup/consumer bugs, 1 Phase 6 dedup-watermark bug, 1 Phase 6 forecast row-ordering bug, 3 Phase 7 nginx/Docker bugs — all `Closed` in `RISKS.md` | — |

## Data platform

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| Bronze/Silver/Gold Structured Streaming pipeline | `services/data-platform/app/{bronze,silver,gold}.py` | `make phase6-smoke`; `make test-data-platform` | Real Parquet observed at every layer; data-quality report `overall: PASS` | `Trigger.AvailableNow()` can leave a non-self-healing gap in the final micro-batch — recoverable via `app.backfill`, `RISKS.md` #22 |
| Data quality checks | `app.dq.checks`/`app.dq.report` | `make dq-report` against live MinIO data | Reconciliation, rejection-rate, duplicate-rate, lateness, freshness checks all passing | — |
| Backfill/reprocessing | `app.backfill` | Used for real to recover ~64 rows dropped by the Phase 6 watermark bug | Row-count validated before swap into the live path | — |

## Forecasting

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| Seasonal-naive baseline + `HistGradientBoostingRegressor` secondary model | `services/data-platform/app/forecasting` | `make forecast-smoke`; `tests/forecasting/` | Secondary model (WAPE 0.154) beat baseline (WAPE 0.298) on this session's deterministic smoke run; selected champion by a documented rule | Bounded by synthetic data's realism (no live location attribution exists yet); recursive rollout has no native multi-horizon head |

## Observability

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| Distributed tracing across the Kafka boundary | `event_contracts.tracing_setup`, OTel Collector, Jaeger | Manual trace inspection in Jaeger against a live order | One order's HTTP request, outbox publish, and every saga step land in the same trace | — |
| Prometheus metrics (every service + worker + Spark job) | `event_contracts.metrics_setup`, `app.metrics` per data-platform job | `scripts/compose_smoke_test.sh` scrape-target check | All scrape targets up with real samples | Grafana and worker `/metrics` are unauthenticated — local-demo-only posture, `RISKS.md` #14 |

## Failure laboratory

See "Reliability" above — same evidence, this row exists for direct
traceability to the spec's own category list.

## Load testing

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| k6, 5 profiles against the live stack | `k6/scenarios.js` + `k6/lib/*.js` | `make load-smoke`/`load-baseline`/`load-test`/`load-stress`/`load-spike` | 0% HTTP-level failure rate across all 5 profiles; `load` profile: 28.70 req/s, 1,520 requests, p95 292.9ms; `stress` profile: 68 combined peak VUs, 2,106 requests, p95 699.0ms; `e2e_workflow_success` = 100% at smoke/baseline/load, 75% at stress, 50% at spike | Laptop/Docker-Desktop measurement, not a cloud-scale claim; e2e degradation under stress/spike reflects the single sequential saga consumer's real throughput ceiling — `RISKS.md` #36–#38 |

## Terraform validation

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| AWS infrastructure, authored + validated only | `infra/terraform/` (13 modules + dev/prod environments) | `make tf-validate-all` (`fmt -check`, `init -backend=false`, `validate`, via the official `hashicorp/terraform:1.9` Docker image) | `terraform fmt -check -recursive` clean; `terraform init` succeeded for all 15 directories; `terraform validate` passed with **zero warnings** for all 15 | Never planned or applied against a real AWS account; no AWS credentials used at any point (ADR 0007). Named gaps: RDS creates 1 of 5 databases at creation time, ops-dashboard's nginx DNS resolver needs an AWS-specific change, S3 auth needs an IAM-role fallback, no tracing backend wired up, EMR image compatibility unverified — `RISKS.md` #39–#43 |

## GitHub-hosted CI

| Capability | Implementation | Validation method | Result | Limitations |
|---|---|---|---|---|
| Hosted CI run on GitHub Actions | `.github/workflows/ci.yml` (`quality-gate` job) | Queried GitHub's public REST API for the real run history this session | 33 total hosted runs; Phase 12 branch shows a genuine hosted-only failure (runs #29/#30, commit `7fdd9ec`) caught and fixed (runs #31/#32, commit `375ea9e`); merge to `main` (run #33, commit `e402f37`) green | Free `ubuntu-latest` runner only — no self-hosted runner, no deployment step (this workflow validates, it does not deploy) |
