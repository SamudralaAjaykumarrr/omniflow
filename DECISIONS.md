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
