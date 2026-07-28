# OmniFlow: Engineering Case Study

An individual portfolio project — not commercial or employer work. This
document walks through the problem, the architecture, the hardest technical
problems encountered, and what would change before this became a real
production system. For a fast orientation instead, see `README.md`; for a
traceable evidence table, see `docs/project-evidence.md`.

## Problem statement

Retail order/inventory/fulfillment systems are a well-known hard problem in
distributed systems: a single customer order touches inventory reservation,
payment authorization, fulfillment-node selection, and downstream analytics,
across services that fail independently and deliver messages at least once,
not exactly once. Getting this right — no overselling, no lost orders, no
silently dropped events, with failures that compensate cleanly instead of
corrupting state — is the property OmniFlow exists to demonstrate, end to
end, against a real running stack rather than in slides.

## Engineering goals

- Correctness over throughput: no overselling, no lost orders, even under
  simulated failure.
- At-least-once processing, explicitly — every consumer idempotent, no
  exactly-once claim anywhere.
- Local-first: the entire system runs on one machine, one command, no paid
  cloud services.
- Explainability: every non-trivial decision documented with its tradeoffs
  (`docs/adrs/`), not just implemented silently.
- Bounded blast radius for the ML component: forecasting is offline,
  downstream, and non-blocking.

## Scope and constraints

Built solo, staged across 13 phases, each required to leave the system
runnable via `docker compose up` before the next began. Host constraints
were real, not hypothetical: 8 CPUs, 15Gi RAM, no host-installed Python,
Node, Java, or Terraform — every build/test/lint command runs inside a
container. Terraform was authored and validated only; it was never planned
or applied against a real AWS account, and no AWS credentials were used at
any point (ADR 0007) — a hard, non-negotiable boundary for this project, not
a judgment call made per-phase.

## Architecture selected

An API Gateway fronts an Order Service and Inventory Service (Postgres-
backed); a Fulfillment Orchestrator runs the order saga by consuming events
off Redpanda (a Kafka-protocol broker, ADR 0001) and calling Order/Inventory
directly over synchronous REST for each step (ADR 0010) rather than a second
event round-trip — the Kafka consumption starts and resumes the saga, but
every subsequent step is a direct call. A PySpark Structured Streaming
pipeline turns the same event catalog into Bronze/Silver/Gold datasets in
MinIO (ADR 0005). Jaeger, Prometheus, and Grafana make the request/event
path observable. A React + TypeScript ops dashboard presents the whole
system to an operator. Full diagrams: `docs/architecture.md`.

## Major implementation phases

1. **Core domain** — Order/Inventory services, API Gateway, Postgres +
   Alembic.
2. **Event platform** — Redpanda, transactional outbox, the saga
   orchestrator (node scoring, payment simulation, compensation, retry,
   dead-letter queue, replay).
3. **Observability** — structured logs, OpenTelemetry tracing across the
   Kafka boundary, Prometheus/Grafana.
4. **Data engineering platform** — Bronze/Silver/Gold Structured Streaming,
   data quality checks, synthetic generator, backfill tooling.
5–6. **Engineering quality + demand forecasting** — coverage threshold,
   security scanning, pre-commit, CI; a pandas/scikit-learn forecasting
   pipeline with a measured baseline comparison.
7. **Ops dashboard** — React + TypeScript, 10 screens.
8. **Failure laboratory** — 10 deterministic, API-triggered failure
   scenarios against the real running stack.
9. **JWT authentication + RBAC**.
10. **Load testing** — k6, 5 profiles, real measured results.
11. **AWS infrastructure in Terraform** — authored and validated, never
    applied.
12. **GitHub-hosted CI** — the workflow authored in Phase 5 confirmed
    running correctly on GitHub's own hosted runners.
13. **This documentation and career-deliverable pass.**

## Difficult technical problems

**The saga resume gap.** If the orchestrator process crashes strictly
between a reservation succeeding over REST and the saga step's local commit,
there is no local record of that reservation. Closing this properly needs
idempotency keys on Inventory Service's reservation endpoint tied to
`(order_id, sku, saga_step)` — not built in this pass. The current behavior
fails loudly with a clear `last_error` instead of silently double-reserving
or guessing. This is the single limitation named most consistently across
this project's own docs (`RISKS.md` #11, `docs/interview-guide.md`) as the
first thing that would change for genuine enterprise scale.

**Two startup-crash bugs found by actually running the failure lab.**
`resume_incomplete_sagas` (called once at every orchestrator-consumer
startup) had no exception handling around `advance_saga` — one unresumable
saga (60 real orphaned rows were found in this session's own dev database)
crashed the whole process on every restart. Separately, a saga's very first
`advance_saga` call was marked "processed" before it ran, so a transient
failure on that first call left the saga stuck `RUNNING` forever with no
retry and no dead letter — found by running the `downstream-outage`
scenario against a live stack, the exact path it was designed to exercise.
Both fixed with regression tests (`RISKS.md` #29/#30). Neither was visible
from reading the code; both only surfaced from running the system for real.

**A dead-letter replay tool that had never actually worked.** `replay_one`
read `dead_letter.payload["original_event"]`, but the consumer that creates
dead letters stores the flat envelope directly, with no wrapper key. Every
real dead letter this consumer ever created made replay raise `KeyError` —
masked because every existing test built its own (wrongly-shaped) fixture
instead of reusing the real code path. Found running a live scenario, fixed,
then verified for real by replaying two dead letters left over from earlier
test runs (`RISKS.md` #31).

**A dedup watermark declared on the wrong timestamp column.** Silver's
`dropDuplicatesWithinWatermark` watermark was declared on the event's
business timestamp, not ingestion time — a generator that legitimately
models a shipping delay could advance Spark's watermark far enough to
silently drop a different, valid, lower-latency event processed afterward.
Not a duplicate-detection bug; a correct-data-loss bug, hit for real running
the Phase 6 smoke test (~44% reconciliation mismatch on one event type in
one run). Fixed by moving the watermark to ingestion time; ~64 already-
dropped rows recovered via backfill (`RISKS.md` #21).

## Meaningful design trade-offs

- **Custom saga orchestrator vs. Temporal** (ADR 0004): Temporal is the
  stronger production answer for durable workflows, but it would hide the
  exact retry/compensation/persistence mechanics this project exists to
  demonstrate behind its own runtime, and it's a second stateful system to
  operate. The trade-off is explicit, not hidden: this does not scale to
  hundreds of saga types or long-running workflows as gracefully as Temporal
  would.
- **Row-level locking vs. optimistic versioning, by contention profile**
  (ADR 0002): `inventory_stock` uses `SELECT ... FOR UPDATE` (hot rows,
  worth the lock contention); `orders` uses an optimistic `version` column
  (low contention, no reason to pay for a lock). Two strategies in one
  codebase is intentional, not inconsistent.
- **Transactional outbox over CDC/Debezium** (ADR 0003): atomic
  DB-write-plus-publish without a second infrastructure dependency or
  two-phase commit.
- **Redpanda over Apache Kafka** (ADR 0001): Kafka-protocol compatible,
  without ZooKeeper/JVM overhead on a shared 8-CPU host.
- **Single-node PySpark (`local[*]`) over a real cluster** (ADR 0005): the
  Structured Streaming code (checkpointing, watermarks, `foreachBatch`) is
  identical to what would run against a real EMR/Kubernetes cluster — only
  the `--master` config differs. Verified for real: 11 concurrent Silver
  queries plus 9 concurrent Gold queries on too few Spark cores actually did
  starve individual queries under real load (not just in theory) until
  `spark.scheduler.mode=FAIR` was set (`RISKS.md` #16).

## Reliability patterns

At-least-once delivery, idempotent consumers everywhere (dedupe by
`event_id`), a transactional outbox on every producer, retry with
backoff+jitter, dead-letter routing with a working replay path, and a
Failure Laboratory that exercises all of this against the real stack rather
than asserting it in isolation. See `docs/architecture.md`'s
"Failure laboratory: trigger / observe / reset flow" diagram.

## Data consistency strategy

No live cross-service foreign keys between Order and Inventory's separate
schemas — referential integrity is enforced by application-level checks at
write time and a Bronze-vs-Silver-vs-Gold reconciliation data-quality check
that runs against real Parquet data and is verified `PASS`. The system never
claims exactly-once delivery; every consumer is built to be safely
re-invoked with the same message.

## Security strategy

Self-contained JWT authentication (PyJWT, HS256, issuer/audience/expiry/
signature all verified) plus role-ranked RBAC (`viewer < ops < admin`) — no
external identity provider, matching the "no paid services" constraint.
Enforced on api-gateway's customer-facing routes and failure-lab's
trigger/reset routes, the two surfaces ADR 0009 names. Deliberately not
extended to inventory-service/fulfillment-orchestrator's own routes, since
those are called directly by the real saga machinery with no user JWT to
present — protecting them needs a second, broader service-to-service auth
layer, named as open scope rather than silently left unauthenticated
(`RISKS.md` #25/#34).

## Observability strategy

Structured JSON logs with `correlation_id` on every line; OpenTelemetry
traces that survive the Kafka boundary via the event envelope's own
`trace_context.traceparent` field, so one order's HTTP request, its outbox
publish, and every saga step it triggers land in the same Jaeger trace;
Prometheus metrics pulled from every service, worker, and Spark job.

## Testing strategy

411 backend tests across 7 suites (0 failed), 82 dashboard tests (0 failed),
combined 80.9% statement coverage against a 65% threshold. Every phase
closed with real commands run against the live stack — a compose smoke
test, a data-platform smoke test, a failure-lab smoke test run twice in a
row — not just unit tests with fakes. Exact counts: `TEST_RESULTS.md`.

## Load-testing findings

Five k6 profiles (smoke/baseline/load/stress/spike) against the live stack:
0% HTTP-level failure rate at every scale tested, up to 68 combined peak
VUs. The honest finding, not hidden: end-to-end saga completion
(`e2e_workflow_success`) degrades gracefully under real backlog pressure —
100% at smoke/baseline/load, 75% at stress, 50% at spike — reflecting the
single sequential saga-consumer's real, measured throughput ceiling, well
before any HTTP-level failure appears. Full numbers: `docs/project-evidence.md`,
`docs/phase-10-load-testing.md`.

## CI/CD strategy

`.github/workflows/ci.yml` mirrors `make ci` job-for-job on a free
`ubuntu-latest` runner. Verified both locally throughout the build and, in
Phase 12, against GitHub's own hosted runners: 33 total hosted runs exist
for this repository, including a genuine hosted-only failure on the Phase
12 branch (caught and fixed within that same branch) and a green run on the
final merge to `main`.

## Terraform approach

Realistic, modular Terraform (13 modules + dev/prod environments) mapping
the running stack onto ECS Fargate, RDS, MSK, S3, EMR Serverless,
ElastiCache, an ALB, least-privilege IAM, and Secrets Manager — authored and
validated (`fmt`/`init -backend=false`/`validate`, zero warnings) only.
Never planned or applied against a real account; no AWS credentials used at
any point (ADR 0007). Named, not hidden: several gaps exist between "this
validates" and "this would actually run in AWS" — a manual per-service-
database bootstrap step, an nginx DNS-resolver change, an S3 IAM-role
auth fallback, and no distributed-tracing backend wired up (`RISKS.md`
#39–#43).

## Limitations

The full risk register (`RISKS.md`) is the authoritative list; the ones
most worth surfacing here: the saga resume gap, single-instance-only
gateway rate limiting/DB pooling, unauthenticated Grafana/worker metrics
(local-demo-only posture), 9 accepted dependency CVEs pending a coordinated
`fastapi`/`starlette` major-version bump, and Terraform that has never been
applied.

## What would change for a real production deployment

1. Close the saga resume gap with reservation idempotency keys.
2. Horizontally scale the saga consumer (multiple partitions/consumer-group
   members) — currently a single sequential process.
3. Move rate limiting and connection pooling to a shared backing store
   (Redis, PgBouncer) instead of in-process/per-process state.
4. Add authentication to Grafana and every worker's `/metrics` endpoint.
5. Complete the coordinated `fastapi`/`starlette` upgrade to clear the
   remaining accepted CVEs.
6. Extend authentication to inventory-service and fulfillment-orchestrator's
   own routes via a proper service-to-service auth layer.
7. Actually deploy the Terraform, closing the named AWS-specific gaps
   first (per-service database bootstrap, nginx resolver, S3 IAM auth,
   a real tracing backend).

## Key lessons

The bugs that mattered most in this project were never found by reading
code — they were found by running the real system and watching it fail:
a stale malformed Kafka record from earlier testing crashing a consumer on
every restart, a dedup watermark silently dropping valid rows only under a
specific timing pattern, an nginx proxy that worked standalone but 404'd
against real upstreams. The recurring pattern across this build was that
"looks correct" and "verified against the running system" are different
claims, and only the second one is worth trusting.
