# Decisions Log

Running log of decisions made during the build, newest first. Major
architectural decisions get a full ADR under `docs/adrs/`; this log also
captures smaller in-flight calls that don't warrant a standalone ADR, plus
pointers to the ADRs when they do.

## 2026-07-23 — Planning stage

- Chose Redpanda over Apache Kafka for the event platform. See
  [ADR 0001](docs/adrs/0001-redpanda-over-kafka.md).
- Chose row-level locking for inventory reservations + optimistic
  `version`-column concurrency for order state transitions (two different
  strategies for two different contention profiles, both required by the
  spec). See [ADR 0002](docs/adrs/0002-inventory-concurrency-control.md).
- Chose transactional outbox over CDC/Debezium for reliable event publish.
  See [ADR 0003](docs/adrs/0003-transactional-outbox.md).
- Chose a custom lightweight saga orchestrator over Temporal/Airflow. See
  [ADR 0004](docs/adrs/0004-custom-saga-orchestrator.md).
- Chose PySpark Structured Streaming in single-node `local[*]` mode for the
  local demo, cluster deployment described only in the (unapplied) Terraform/
  architecture docs. See [ADR 0005](docs/adrs/0005-spark-local-mode.md).
- Chose baseline-first forecasting (seasonal-naive/moving-average) with a
  lightweight scikit-learn/statsmodels secondary model, deferring Prophet/
  XGBoost to a documented future upgrade. See
  [ADR 0006](docs/adrs/0006-forecasting-scope.md).
- Chose to author and validate Terraform (`fmt`/`validate` in a container)
  and never apply it — no AWS credentials exist in this session and none
  will be requested. See [ADR 0007](docs/adrs/0007-terraform-not-applied.md).
- Finalized the monorepo layout (`/services`, `/data-platform`, `/frontend`,
  `/infra`, `/observability`, `/docs`, `/scripts`). See
  [ADR 0008](docs/adrs/0008-monorepo-layout.md).
- Chose self-contained JWT + RBAC auth (bcrypt password hashing) over a
  third-party IdP, to keep local evaluation free of paid services. See
  [ADR 0009](docs/adrs/0009-authn-authz.md).
- Verified host toolchain via direct inspection: Docker + Compose present;
  no host pip/node/java/terraform. Decision: all builds, tests, and lint runs
  go through Docker containers rather than assuming/installing a host
  toolchain, consistent with the "no paid services, one-command local demo"
  requirement.
- Decided to run the full 13-phase build additively, each phase leaving the
  system runnable via `docker compose up`, rather than attempting uniform
  "finished" depth across all 16 spec sections simultaneously — recorded as
  the primary scope-management decision for this project (see `RISKS.md`,
  "Scope vs. depth").

## 2026-07-23 — Phase 1: Core domain

- Built `event-contracts`, `order-service`, `inventory-service`, and
  `api-gateway` per the plan; wired them together with `docker-compose.yml`,
  per-service Dockerfiles, a Postgres init script creating one database per
  service (plus a `*_test` twin), a `Makefile`, and `.env.example`.
- Two per-service databases share one Postgres container in local dev
  (`omniflow_orders`, `omniflow_inventory`, and their `_test` twins) rather
  than one database per service in separate containers — keeps the local
  resource footprint down while still enforcing the "no live cross-service
  FKs" boundary from ADR 0008 (they're genuinely separate databases, not
  just separate schemas in one).
- Gateway rate limiting is a simple in-process fixed-window counter (not
  Redis-backed) — correct and testable for a single-instance local demo,
  explicitly not a multi-instance-safe design; documented in the middleware
  docstring and `docs/reliability.md` will restate it when that doc lands.
- **Real bugs found while verifying Phase 1's own test suite, fixed before
  trusting any result** (see `TEST_RESULTS.md` for the full list; recorded
  here for the *why*, since these are the kind of mistake worth remembering):
  - `entrypoint.sh` (both stateful services) ran `alembic upgrade head` then
    unconditionally `exec uvicorn ...`, ignoring any command passed to
    `docker compose run`/`docker run`. A `docker compose run --rm
    order-service sh -c "pytest ..."` therefore silently started the API
    server instead of running tests — no error, just a container that sat
    there "healthy" forever. Fixed by having the entrypoint `exec "$@"` when
    given arguments, only defaulting to serving when given none. This is
    the kind of bug that produces a false-green (or in this case, a
    false-nothing) result if you don't notice the command never actually
    ran — always check that a "passing" test run actually printed test
    output, not just a clean exit.
  - The concurrency test spawned threads that each read `seeded_node.id` off
    a single ORM object bound to the main thread's DB session —
    SQLAlchemy sessions aren't thread-safe, so concurrent lazy-loads on the
    same object under-counted the expected number of rejections. Fixed by
    reading the plain UUID once, before spawning threads, and passing that
    value in instead of the ORM object.
  - The gateway's proxy layer copied the inbound `X-Correlation-ID` header
    into a plain dict *and* separately set the same header under a
    different-case key, producing two dict entries that httpx sent as two
    header lines — which the receiving side joined into one
    comma-separated, duplicated value. Fixed by excluding the correlation
    header from the copied set before adding it back once.
  - Two gateway tests were order-dependent on shared state: an
    `os.environ.setdefault` for dummy upstream URLs was silently a no-op
    because `docker compose run` already injects the real (reachable)
    service URLs as actual environment variables; and a rate-limit test's
    lowered threshold tripped on hits left over from earlier tests sharing
    the same in-process counter. Fixed by overriding the env vars
    unconditionally, and by making the rate-limit counter live on
    `app.state` so a test can explicitly reset it.

## 2026-07-24 — Phase 2: Event platform

- Redpanda added as a single-broker Compose service (`--smp=1 --memory=512M
  --overprovisioned`) plus a one-shot `redpanda-topics` job creating all 11
  event-catalog topics idempotently (`rpk topic create` per topic, skipping
  ones that already exist).
- Added `event_contracts.kafka`: thin `build_producer`/`publish_envelope`/
  `build_consumer` wrappers plus a generic `run_consume_loop(consumer,
  process, on_dead_letter, ...)` that retries with backoff+jitter and routes
  to a caller-supplied dead-letter callback on exhaustion, always committing
  the offset afterward either way. This one function is reused by both
  order-service's validator consumer and the orchestrator's saga consumer —
  legitimate shared infra (not business logic), consistent with ADR 0008's
  carve-out for `event-contracts` as the one shared package.
- **Order Service auto-validates asynchronously, not inline in
  `create_order`.** Considered inlining `CREATED -> VALIDATED` directly into
  order creation (simpler), but that would have changed `POST /orders`'s
  response from Phase 1 (`status: CREATED`) and broken a working, already-
  passing Phase 1 test — explicitly out of bounds per this phase's
  instructions. Instead, Order Service gained its own tiny Kafka consumer
  (`app/validator_consumer.py`) that consumes its own `order.created` event,
  performs a (currently placeholder, always-passes) validation, and emits
  `order.validated`. This also means the idempotent-consumer pattern is now
  demonstrated in two independent services, not just the orchestrator.
- **Saga coordination is direct synchronous REST, not a second async
  round-trip.** The orchestrator's real Kafka consumption
  (`order.validated`, `order.cancelled`) starts/aborts a saga; every
  subsequent step (reserve, check stock, transition order status, release on
  compensation) is a direct REST call to Order Service / Inventory Service.
  Both services still publish their full event catalog via their own
  outboxes for the data platform. Full reasoning, the node-scoring formula,
  and the alternatives considered are in
  [ADR 0010](docs/adrs/0010-node-scoring-and-saga-orchestration.md).
  `docs/architecture.md`'s sequence/flow diagrams were updated to match this
  reality rather than the earlier, more choreography-flavored Phase 0 sketch.
- Payment simulation is a deterministic, stateless, in-process module keyed
  by marker SKUs (`SKU-PAYMENT-DECLINE`, `SKU-PAYMENT-TIMEOUT-RECOVER`,
  `SKU-PAYMENT-TIMEOUT-PERSISTENT`) rather than randomized outcomes — so
  saga tests (and later the Phase 8 failure lab) can deterministically
  reproduce every outcome (hard decline, transient-then-recovers,
  transient-exhausts) without flakiness.
- Saga durability: each step commits `saga_instances.current_step` and a
  JSON `context` scratchpad before returning, and `resume_incomplete_sagas`
  re-enters any row still `RUNNING` from that step on orchestrator startup.
  A narrow, explicitly accepted resume gap is documented in `RISKS.md`
  rather than solved: a crash strictly between a successful remote
  reservation and this step's local commit leaves no local record of that
  reservation, and the saga fails loudly instead of guessing or
  double-reserving.
- **Real bugs found while verifying Phase 2's test suite, fixed before
  trusting any result** (full detail in `TEST_RESULTS.md`):
  - The node-scoring formula's distance/delivery normalization divided each
    candidate's value by the set's max — which is always 1.0 for a lone or
    all-tied candidate, making `1 - 1.0 = 0.0` (worst) instead of `1.0`
    (best, trivially, being the only option). Fixed with proper min-max
    normalization; caught by a dedicated single-candidate test before it
    shipped.
  - Phase 1's test fixtures managed schema via `Base.metadata.drop_all`/
    `create_all`, bypassing Alembic entirely, while Phase 1's entrypoint fix
    made `alembic upgrade head` run unconditionally before every test
    invocation. The two together desynced `alembic_version` (claiming
    migration `0001` applied) from actual table state (dropped by the prior
    test session's teardown), so Phase 2's new migration failed trying to
    alter a table that didn't exist. Fixed by dropping `drop_all` from every
    service's test fixtures (truncate, never touch Alembic's bookkeeping)
    and manually repairing the already-desynced test databases once. This
    is the kind of cross-phase interaction that's easy to miss when each
    phase's tests pass in isolation — worth remembering for any future
    schema-affecting change.
  - `api-gateway` had no Docker healthcheck since Phase 1 — invisible until
    this phase's compose smoke test's health-wait loop timed out on a
    service that was actually fine. Added the same healthcheck pattern the
    other three services already use.

## 2026-07-24 — Phase 3: Observability

- **Traces are push (OTLP -> Collector -> Jaeger), metrics are pull
  (Prometheus scrapes `/metrics` directly)** — not both funneled through
  the OTel Collector. `docs/architecture.md`'s original Phase 0 sketch
  showed the collector forwarding metrics to Prometheus too; that was
  never built that way, since Prometheus's own pull model is simpler here
  and needs no metrics-specific collector pipeline config. The
  observability-flow diagram was corrected to match what's actually
  running, not the earlier plan.
- **Every FastAPI service serves `/metrics` on its normal port; every
  background worker runs a standalone `prometheus_client` HTTP server on
  its own `METRICS_PORT`.** Workers (outbox relays, the validator
  consumer, the saga consumer) have no ASGI app to hang a route off of, so
  `prometheus_client.start_http_server(port)` is the natural fit — same
  registry, same metric objects, just a different transport. Each worker
  gets a distinct port (9101–9105) set per `docker-compose.yml` service so
  Prometheus can scrape them all independently.
- **Trace context crosses the Kafka boundary through the event envelope's
  own `trace_context.traceparent` field** (W3C Trace Context), not a
  side-channel or Kafka header. Captured at `stage_event` time via
  `current_traceparent()`, re-extracted by both the outbox relay's publish
  span and `run_consume_loop`'s consumer span via
  `context_from_traceparent()`. This is what makes one order's HTTP
  request, its outbox publish, and every saga step a Kafka event triggers
  land in the *same* Jaeger trace — verified for real in this phase's
  compose smoke test (see `TEST_RESULTS.md`), not just asserted in a unit
  test with an in-memory span exporter.
- **The outbox relay's own publish step gets a tracing span**, not just
  the producer/consumer either side of it. Considered leaving the relay
  untraced (it's thin, easy to skip), but its poll-then-publish latency is
  exactly the kind of hop a real on-call engineer would want visible
  between "API handled the request" and "the saga consumer picked it up" —
  skipping it would have left a blind gap in every cross-service trace.
- **`event_contracts.kafka.run_consume_loop` owns correlation-ID-setting,
  span-starting, and retry/dead-letter metric increments for every
  consumer**, the same function already shared for retry+backoff+DLQ
  logic since Phase 2. Consistent with that phase's precedent of putting
  genuinely cross-cutting infra (not business logic) in the one shared
  package, rather than duplicating this wiring into
  `order-service/app/validator_consumer.py` and
  `fulfillment-orchestrator/app/consumer.py` separately.
- **Added `make typecheck` (mypy) as this project's first static type
  checking pass**, run per-service (`order-service/app`,
  `inventory-service/app`, etc. each checked as its own root) rather than
  once across the whole repo, because every service's application package
  is named `app` — checking them together makes mypy treat identically
  named packages across different services as a duplicate module. This
  mirrors the isolation Docker/pytest already give each service; it is
  not a workaround, it's the correct unit boundary for a monorepo of
  independently-deployable services that happen to share an internal
  package name.
- Scoped `make typecheck` to non-strict (`--ignore-missing-imports`,
  default settings otherwise) rather than adopting a strict mypy config
  retroactively — this codebase never ran a type checker before Phase 3,
  and demanding fully-annotated strict-mode compliance from Phase 1/2 code
  written without that constraint would mean either a large unrelated
  reformatting pass (out of this phase's scope) or quietly disabling rules
  until it passed (worse than not having the tool). What it does check —
  the type hints CLAUDE.md's conventions already call for — passes clean.
- **Grafana runs with anonymous admin access** (`GF_AUTH_ANONYMOUS_ENABLED`),
  matching this project's "no paid services, single-command local demo,
  nothing here guards real data" posture (see ADR 0009's authn/authz
  scoping) — a real login system for a throwaway local Grafana instance
  would be friction with no corresponding benefit.
- **`scripts/compose_smoke_test.sh` was extended, not replaced**, to also
  assert traces landed in Jaeger, every Prometheus target is up with real
  samples, and Grafana's datasource/dashboard are provisioned —
  consistent with Phase 2's precedent that a phase closes with something
  that verifies its own claims against the real running stack, not just
  unit tests with fakes.
- **Real bugs found and fixed during this phase's verification** (full
  detail in `TEST_RESULTS.md`):
  - A custom `prometheus_client.registry.Collector` subclass
    (`DBPoolCollector`) didn't formally inherit from the library's
    `Collector` ABC — worked at runtime, caught by the first real mypy
    pass this project has run.
  - `scripts/compose_smoke_test.sh`'s hardcoded fulfillment-node name and
    customer email collided with real unique constraints on any re-run
    against a persistent dev DB volume (as opposed to a fresh
    `docker compose up -v` volume) — a latent Phase 2 bug, invisible until
    this phase's iterative re-testing actually re-ran `make smoke` more
    than once against the same volume. Fixed the same way the script
    already handled `customer_id`/`Idempotency-Key`: a random per-run
    suffix.
  - `event-contracts`' test suite depended on `httpx` (transitively, via
    `starlette.testclient`) without declaring it anywhere, passing only by
    accident on hosts where it happened to already be installed.
