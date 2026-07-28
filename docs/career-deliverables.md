# Career Deliverables

Résumé, recruiter, and profile copy for OmniFlow — an individual portfolio
project. Every number below is sourced from `TEST_RESULTS.md`/
`docs/project-evidence.md` and was produced by a command actually run
against this repository. No fabricated percentages, user counts, revenue,
latency reductions, uptime, or cloud-scale claims appear anywhere below.

## One-line project description

An event-driven retail order/inventory/fulfillment platform demonstrating
saga orchestration, transactional outboxes, a Bronze/Silver/Gold data
pipeline, and AWS infrastructure-as-code, built solo and verified end to end
against a real running stack.

## Two-line GitHub description

Event-driven order/inventory/fulfillment platform with saga orchestration,
a Kafka-protocol event bus, a Spark data pipeline, JWT/RBAC, and k6 load
testing. AWS infrastructure authored in Terraform (validated, never
applied); 411 backend tests, 82 dashboard tests, all passing.

## LinkedIn project description

**OmniFlow — Event-Driven Order Fulfillment Platform**

Solo-built, 13-phase distributed system demonstrating production-oriented
engineering practice: a saga orchestrator coordinating order, inventory,
and payment steps with compensation on failure; a transactional outbox on
every event-producing service; idempotent Kafka consumers (Redpanda);
row-level and optimistic concurrency control chosen by contention profile;
a PySpark Structured Streaming Bronze/Silver/Gold data pipeline with
executable data-quality checks; a demand-forecasting pipeline with a
measured baseline comparison; JWT authentication with role-based access
control; a React/TypeScript operations dashboard; a failure-injection lab
with 10 deterministic, API-triggered scenarios; k6 load testing across five
profiles; and AWS infrastructure authored and validated in Terraform
(never applied — no real cloud spend). 411 backend tests and 82 dashboard
tests passing, 80.9% combined test coverage, verified on GitHub-hosted CI.

## Recruiter-facing summary

OmniFlow is a self-directed, portfolio-scale distributed system built to
demonstrate the engineering practices that matter for backend, platform,
and data engineering roles: event-driven architecture, saga-based
distributed transactions, concurrency control, observability, security,
automated testing, and infrastructure-as-code. It's not a tutorial project
or a CRUD app with extra services bolted on — every claim in its
documentation (test counts, coverage, load-test throughput, CI results) is
backed by a command that was actually run and is reproducible from the
repository. The build log (`DECISIONS.md`) and risk register (`RISKS.md`)
document real bugs found and fixed by running the system, not just written
against it.

## Résumé bullets

### Concise (3 bullets)

- Designed and built an event-driven order-fulfillment platform (7 backend
  services, React/TypeScript dashboard) with a custom saga orchestrator
  providing compensating transactions across order, inventory, and payment
  steps.
- Implemented a PySpark Structured Streaming data pipeline (Bronze/Silver/
  Gold) processing an 11-event Kafka-protocol catalog into 10 aggregated
  datasets, with executable data-quality checks and backfill tooling.
- Authored and validated AWS infrastructure as code in Terraform (13
  modules, dev/prod environments) and verified a GitHub Actions CI pipeline
  across 411 backend and 82 frontend tests, both passing.

### Standard (5 bullets)

- Architected an event-driven order/inventory/fulfillment platform on
  Redpanda (Kafka-protocol), with a transactional outbox on every
  event-producing service and idempotent consumers guaranteeing safe
  at-least-once processing.
- Built a custom saga orchestrator coordinating inventory reservation,
  fulfillment-node scoring, and payment simulation, with compensation on
  failure and a persisted, crash-resumable saga state machine.
- Implemented dual concurrency-control strategies chosen by measured
  contention profile — row-level locking for hot inventory rows, optimistic
  versioning for low-contention orders — verified correct under concurrent
  load.
- Developed a PySpark Structured Streaming Bronze/Silver/Gold data pipeline
  with schema validation, deduplication, late-event handling, and a
  demand-forecasting model evaluated against a measured baseline.
- Delivered JWT authentication with role-based access control, a k6
  load-testing suite (five profiles, 0% HTTP failure rate up to 68
  concurrent virtual users), and AWS infrastructure authored and validated
  in Terraform, all verified through a GitHub Actions CI pipeline.

### Detailed (7 bullets)

- Architected and built OmniFlow, a 13-phase event-driven order/inventory/
  fulfillment platform spanning 7 backend services and a React/TypeScript
  operations dashboard, run entirely via Docker Compose.
- Designed a custom saga orchestrator (not a third-party workflow engine)
  coordinating inventory reservation, fulfillment-node scoring, and
  simulated payment authorization, with compensating transactions on
  failure and Postgres-persisted, crash-resumable saga state.
- Implemented a transactional outbox on every event-producing service and
  idempotent Kafka consumers (Redpanda, Kafka-protocol) deduping by
  event ID, guaranteeing safe at-least-once event processing across an
  11-event schema-versioned catalog.
- Applied two concurrency-control strategies by measured contention
  profile — row-level locking for hot inventory rows, optimistic
  versioning for low-contention orders — verified correct under concurrent
  load testing.
- Built a PySpark Structured Streaming Bronze/Silver/Gold data pipeline
  producing 10 aggregated datasets with executable data-quality checks,
  backfill/reprocessing tooling, and a demand-forecasting pipeline whose
  secondary model was evaluated against, and selected over, a measured
  seasonal-naive baseline.
- Implemented JWT authentication with role-ranked authorization, an
  API-triggered failure-injection lab covering 10 deterministic failure
  scenarios, and OpenTelemetry distributed tracing that follows a request
  across the Kafka boundary into Jaeger.
- Authored and validated AWS infrastructure as code in Terraform (13
  modules, dev/prod environments — ECS Fargate, RDS, MSK, S3, EMR
  Serverless) and verified a GitHub Actions CI pipeline (33 hosted runs)
  gating 411 backend tests, 82 frontend tests, and 80.9% combined test
  coverage.

## Role-specific emphasis variants

### Python backend / software engineer

Emphasize: the saga orchestrator's state-machine design, the transactional
outbox pattern, dual concurrency-control strategies (row locking vs.
optimistic versioning), idempotent consumer design, JWT/RBAC
implementation, and the 411-test backend suite with 80.9% coverage. Lead
with the "custom saga orchestrator vs. Temporal" trade-off as a
system-design talking point.

### Platform / cloud engineer

Emphasize: the Terraform-authored AWS architecture (13 modules mapping ECS
Fargate, RDS, MSK, S3, EMR Serverless, ElastiCache, least-privilege IAM),
the Docker Compose local-development environment, the GitHub Actions CI
pipeline (verified on real hosted runners, 33 runs), and the observability
stack (Prometheus/Grafana/Jaeger, OpenTelemetry). Be explicit that
Terraform was validated but never applied — frame it as infrastructure
design and IaC discipline (`fmt`/`init`/`validate` all clean, zero
warnings), not a deployed environment.

### Data engineer

Emphasize: the PySpark Structured Streaming Bronze/Silver/Gold pipeline,
schema evolution and contract testing across an 11-event catalog,
deduplication and late-event handling, executable data-quality checks
(reconciliation, rejection rate, duplicate rate, freshness), backfill/
reprocessing tooling with row-count validation, and the demand-forecasting
pipeline (feature engineering with leakage safeguards, chronological
evaluation, a measured baseline comparison).

## Skills / keywords

Grounded in what's actually in this repository — no keyword stuffing:

**Languages & frameworks**: Python, TypeScript, FastAPI, SQLAlchemy,
Alembic, Pydantic, React, Vite.

**Data & streaming**: Apache Kafka protocol (Redpanda), PySpark Structured
Streaming, Parquet, MinIO (S3-compatible object storage), pandas,
scikit-learn.

**Infrastructure & DevOps**: Docker, Docker Compose, Terraform, AWS (ECS
Fargate, RDS, MSK, S3, EMR Serverless, ElastiCache, ALB, IAM, Secrets
Manager, CloudWatch — as authored/validated infrastructure), GitHub
Actions CI/CD.

**Observability**: OpenTelemetry, distributed tracing, Prometheus,
Grafana, Jaeger, structured logging.

**Testing & quality**: pytest, Vitest, React Testing Library, k6 load
testing, mypy, ruff, bandit, pip-audit, pre-commit.

**Architecture & patterns**: event-driven architecture, saga pattern,
transactional outbox, idempotent consumers, optimistic and pessimistic
concurrency control, role-based access control (JWT/RBAC), CQRS-adjacent
read APIs, distributed-systems failure testing.

## Individual ownership

OmniFlow was designed, built, and validated by one individual as a
self-directed portfolio project — it is not commercial or employer work,
and no part of this repository or its documentation should be read as
implying production usage at a company, a customer base, or team
ownership. Every phase of the build, every architectural decision
(`docs/adrs/`), and every verification command was carried out and recorded
by the same individual, working solo, specifically to produce a credible,
traceable body of evidence for technical interviews and portfolio review.
