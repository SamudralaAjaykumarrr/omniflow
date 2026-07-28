# Interview Guide

Talking points for explaining OmniFlow in an interview, at several depths.
This is an individual portfolio project — the framing below never implies
employer or commercial production experience; it's presented as
production-oriented design practiced end to end on a self-directed build.

## 30-second explanation

"OmniFlow is an event-driven order/inventory/fulfillment platform I built
solo to demonstrate distributed-systems and data-engineering practice —
saga orchestration, transactional outboxes, idempotent consumers, a
Bronze/Silver/Gold data pipeline, JWT/RBAC, and load testing, all running
locally with real measured results, plus AWS infrastructure authored and
validated in Terraform."

## 90-second explanation

"It's a retail order-fulfillment system: a customer order has to reserve
inventory, pick a fulfillment node, simulate a payment, and update multiple
downstream systems — all while services fail independently and messages can
be delivered more than once. I built it in 13 staged phases: core services
first, then an event bus with a custom saga orchestrator, observability,
a Spark-based data platform, a forecasting model, a React dashboard, a
failure-injection lab with 10 deterministic scenarios, JWT auth, k6 load
testing, and AWS infrastructure in Terraform — authored and validated, never
applied, since I didn't want to spend real money on a demo project. Every
number I can quote — test counts, coverage, load-test throughput — came from
a command I actually ran, not an estimate."

## 3-minute technical walkthrough

Start with the request path: API Gateway validates and authenticates, then
calls Order Service, which persists the order and writes an outbox row in
the same transaction. An outbox relay polls that table and publishes to
Redpanda (Kafka-protocol). The Fulfillment Orchestrator consumes
`order.validated`, and from there runs the saga as direct, synchronous REST
calls to Order/Inventory — reserve inventory (row-locked for the hot rows),
score fulfillment nodes on a documented formula, simulate payment
authorization, and transition the order through its state machine. If
anything fails, the orchestrator compensates: releases the reservation and
marks the order failed, not stuck. Every step's saga state is persisted to
Postgres, so a crashed orchestrator process resumes in-flight sagas on
restart. The same event catalog also flows into a PySpark Structured
Streaming pipeline (Bronze/Silver/Gold in MinIO) for data quality and
forecasting, and into a React dashboard for operators.

## 8–10 minute system-design walkthrough

Cover, in order: (1) the business problem and why correctness-over-
throughput was the design's organizing constraint; (2) the two concurrency
strategies and why they differ (row locking for hot inventory rows,
optimistic versioning for low-contention orders); (3) the outbox pattern and
why it avoids a distributed transaction; (4) why the saga orchestrator is
custom rather than Temporal, and what that trade-off costs; (5) idempotency
end to end — API-level (`Idempotency-Key`), consumer-level (`processed_events`),
and the one place it's *not* fully closed (the saga resume gap, below);
(6) the data platform's Bronze/Silver/Gold layering and why the dedup
watermark bug happened; (7) JWT/RBAC and its deliberately bounded scope;
(8) load-testing methodology and what the results actually show; (9) the
Terraform boundary and why nothing was ever applied; (10) what you'd change
first for real production scale.

## The most difficult problem solved

The saga resume gap: if the orchestrator crashes strictly between a
reservation succeeding over REST and the saga step's local Postgres commit,
there's no local record of that reservation to resume from. I didn't solve
this — I made it fail loudly instead of silently double-reserving or
guessing, and documented exactly what closing it for real would need
(idempotency keys on the reservation endpoint tied to
`(order_id, sku, saga_step)`). I'd lead with this in an interview because
it's the honest "what's still open" answer, and being able to name the
precise fix rather than hand-wave at it is the actual signal.

## Reliability and idempotency

Every consumer dedupes by `event_id` against a `processed_events` table, so
Kafka's at-least-once redelivery is a safe no-op, not a bug. The system
never claims exactly-once delivery — that claim would be false, and this
project is explicit about not making it anywhere.

## Transactional outbox

An event is never published without the state change that caused it having
already committed: the same database transaction that updates an order also
inserts a row into `outbox_events`; a separate relay process polls that
table and publishes to Kafka, only removing the row after a confirmed
publish. This avoids both "the DB write succeeded but the event never
went out" and needing a two-phase commit across Postgres and Kafka.

## Saga / orchestration design

A single orchestrator service persists saga progress (current step, status,
attempt count, last error) to Postgres and drives each step via direct REST
calls to Order/Inventory rather than a second event round-trip — chosen so
that "what step is this order on and what happens on failure" is visible in
one place, not implicit across services reacting to each other's events
(the choreography alternative). The trade-off, named explicitly: this
doesn't scale to hundreds of saga types or long-running workflows as
gracefully as a framework like Temporal would.

## Database and consistency decisions

Two concurrency strategies, chosen by contention profile, not by accident:
`SELECT ... FOR UPDATE` row locking on `inventory_stock` (genuinely hot
rows, worth the lock contention — verified live, 10 threads racing for the
last unit, exactly 1 succeeds), and an optimistic `version` column on
`orders` (low contention, no reason to pay for a lock). No live foreign
keys between Order's and Inventory's separate schemas — referential
integrity is checked at write time and reconciled by a data-quality job
against the Gold layer.

## Kafka / event-streaming decisions

Redpanda instead of Kafka — Kafka-protocol compatible, avoids running
ZooKeeper and a separate JVM broker on a shared 8-CPU host. 11 event types
in the catalog, each schema-versioned; contract tests assert a producer's
current payload still validates against the last two published schema
versions, so a breaking change is caught before it ships, not in
production.

## Security / JWT / RBAC explanation

Self-contained JWT (PyJWT, HS256) with issuer/audience/expiry/signature all
verified, plus a ranked role model (`viewer < ops < admin`). Deliberately
scoped to the two surfaces that needed it (the gateway's customer-facing
routes and the failure lab's trigger/reset routes) rather than every
service — inventory-service and the orchestrator's own routes are called
directly by trusted internal machinery with no user JWT to present, and
protecting them would need a second, broader service-to-service auth layer
I scoped out explicitly rather than silently leaving unauthenticated
without saying so.

## Data platform explanation

PySpark Structured Streaming in `local[*]` mode — the same checkpointing/
watermark/`foreachBatch` code that would run against a real EMR or
Kubernetes cluster, just with a different `--master` config. Bronze is raw
immutable Parquet; Silver validates, deduplicates, and quarantines
malformed/late records instead of dropping them; Gold aggregates into 10
business datasets. A dedup-watermark bug (declared on business time instead
of ingestion time) silently dropped valid rows under a specific timing
pattern — found running the pipeline for real, fixed, and the dropped rows
recovered via backfill.

## Testing and CI explanation

411 backend tests across 7 suites, 82 dashboard tests, all passing;
combined 80.9% statement coverage against a 65% threshold enforced in CI.
`.github/workflows/ci.yml` mirrors the local `make ci` gate and has a real
hosted run history on GitHub Actions — including a genuine hosted-only
failure on one branch, caught and fixed within that branch, distinct from
anything a purely local run could have caught (hosted runners exercise a
cold environment and GitHub's own network path that a locally-cached run
doesn't).

## Load-testing explanation

k6 against the real running stack, five profiles from smoke to spike. The
headline result is 0% HTTP-level failure rate at every scale tested up to
68 combined peak virtual users. The more interesting result is what
degrades: end-to-end saga completion drops to 75% under stress and 50%
under spike — not because anything errors, but because the single
sequential saga-consumer process has a real, measured throughput ceiling,
and requests queue behind it under sustained backlog. I'd rather show that
honest degradation curve than a stack that "never fails" because the load
test never actually stressed the bottleneck.

## Terraform / AWS explanation

Realistic, modular Terraform for the same architecture on AWS (ECS Fargate,
RDS, MSK, S3, EMR Serverless, ElastiCache, an ALB, least-privilege IAM,
Secrets Manager) — but authored and validated only. `terraform fmt`,
`init -backend=false`, and `validate` all pass with zero warnings, run
through the official Terraform Docker image with no AWS credentials
anywhere in the environment. It was never planned or applied against a real
account, on purpose — I didn't want a demo project accumulating real cloud
cost or needing real credentials during the build. I can walk
through exactly what's modeled and exactly what named gaps remain before it
would actually run (a manual per-service-database bootstrap step, an nginx
DNS-resolver change for AWS's VPC resolver, an IAM-role S3 auth fallback, no
tracing backend wired up yet).

## Honest limitations

The saga resume gap (above); single-instance-only gateway rate limiting and
DB connection pooling; unauthenticated Grafana and worker metrics endpoints
(fine for a local demo, first thing to change before any shared deployment);
9 accepted dependency CVEs (mostly `starlette`, pending a coordinated
`fastapi` major-version bump); coverage measured as statement-only, not
branch; forecasting bounded by synthetic data's realism; Terraform never
applied. None of these are hidden — they're all named with a status in
`RISKS.md`.

## Likely interviewer questions

**"Why not just use Temporal for the saga?"** — Considered and rejected for
this project specifically because it would hide the retry/compensation/
persistence mechanics I wanted visible in my own code, and because it's a
second stateful system to operate. I'd use Temporal for a real production
system at meaningful scale; the trade-off is documented, not avoided.

**"What happens if two requests race for the last unit of stock?"** — Row-
level lock via `SELECT ... FOR UPDATE` on the inventory row; verified live
with 10 concurrent threads, exactly one succeeds, the rest see the
post-decrement state and reject cleanly.

**"How do you handle duplicate message delivery?"** — Every consumer checks
a `processed_events` table keyed by `(consumer_name, event_id)` before
acting; redelivery becomes a no-op insert conflict, not a re-applied side
effect. At-least-once, made safe by idempotency — never claimed as
exactly-once.

**"What would break first at 10x your load-test scale?"** — The single
sequential saga-consumer process, based on the measured stress/spike
degradation curve — that's the honest, evidence-based answer, not a guess.

**"Why didn't you deploy this to AWS for real?"** — Deliberate constraint
for this project: no real AWS credentials, no paid cloud spend, on a solo
build. The Terraform is authored and validated to the same bar as the rest
of the codebase; applying it was explicitly out of scope, not something I
ran out of time for.

**"What's the biggest thing you'd change before calling this production-
ready?"** — Close the saga resume gap with reservation idempotency keys,
and move the gateway's rate limiting/connection pooling to a shared backing
store so it survives horizontal scaling — both named explicitly as the
concrete next steps, not afterthoughts.
