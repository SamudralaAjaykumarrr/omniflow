# Decisions Log

Running log of decisions made during the build, newest first. Major
architectural decisions get a full ADR under `docs/adrs/`; this log also
captures smaller in-flight calls that don't warrant a standalone ADR, plus
pointers to the ADRs when they do.

## 2026-07-26 — Phase 6: Demand forecasting (the actual roadmap phase)

- **This is the `PROJECT_STATUS.md` phase table's real Phase 6** — distinct
  from the `phase-6-streaming-data-platform` branch above, which reused the
  number by coincidence (that branch hardened Phase 4's platform). See
  [ADR 0006](docs/adrs/0006-forecasting-scope.md) for the scope decision
  (baseline first, lightweight secondary model) made before this landed.
- **Synthetic history, not real event-catalog data, is the primary
  dataset** — `order.created`'s real item payload (`OrderItemData`) has no
  location field at all (confirmed by re-reading `app.gold.queries`'s
  module docstring and `docs/event-catalog.md` before building anything),
  so a SKU x location x date grain cannot be derived from what the system
  actually produces yet, and this repo's live data volume is whatever a
  smoke test happened to generate — nowhere near enough to evaluate a model
  meaningfully either way. A deterministic seeded generator
  (`app.forecasting.synthetic`) stands in, exactly as the phase spec
  anticipates for this situation, and is documented as synthetic throughout
  — never dressed up as real.
- **`HistGradientBoostingRegressor` over `GradientBoostingRegressor`/
  `RandomForestRegressor`** specifically for native missing-value support:
  every SKU x location series' first `max(lag_days)` rows are legitimately
  `NaN` (there's no history yet), and `HistGradientBoostingRegressor`
  handles that without an imputer step — a real, concrete reason for the
  choice, not just "it's the newer one."
- **WAPE, not MAPE, as the scale-aware business metric.** The synthetic
  generator deliberately includes intermittent-demand SKUs with genuine
  zero-demand days (section B's spec requirement); MAPE's per-row division
  by a zero actual is undefined for those rows, while WAPE aggregates
  numerator and denominator across the whole group before dividing. MAPE
  is not reported at all, per the phase spec's own instruction to only
  include it when zero-handling is "explicitly correct and documented" —
  it isn't, here, so it's omitted rather than special-cased.
- **A real ordering bug, found by a test written specifically to catch it,
  not by inspection**: the recursive multi-step future-forecast rollout
  (`app.forecasting.forecast.generate_future_forecast`) initially wrote
  each step's predictions back into the working series by *position*,
  assuming two independently-sorted DataFrames shared the same row order.
  They don't, in general. Fixed by keying predictions to `(sku,
  location_id)` explicitly. Full writeup: `RISKS.md` #23.
- **Local model artifacts need a bind-mounted volume, not just a relative
  path, to survive across the separate `make forecast-train-baseline` /
  `make forecast-evaluate` container invocations** — each `docker compose
  run --rm` is a fresh container, so a path relative to the image's own
  filesystem (no volume) would vanish with the container that wrote it.
  `docker-compose.yml`'s `spark-gold` service now bind-mounts
  `./services/data-platform/forecasting_artifacts` to that same path.
  Verified directly: trained a baseline and secondary model in two
  separate `docker compose run` invocations, then loaded and evaluated
  both in two more, in a fourth invocation — real cross-container
  persistence, not assumed.
- **Both models trained and evaluated in this session's own validation run**
  (small deterministic smoke-test config, seed 99, 4 SKUs x 2 locations):
  seasonal-naive baseline WAPE 0.298, `HistGradientBoostingRegressor` WAPE
  0.154 — the secondary model won honestly on this run's data, not by
  assumption; champion selection reported it with the measured numbers,
  not a hardcoded "the fancier model wins."

## 2026-07-26 — Phase 6: Streaming data-platform hardening

- **This branch's name reuses "Phase 6", but its scope is not the
  `PROJECT_STATUS.md` phase table's Phase 6 (Demand forecasting, not
  started) — same naming collision as the `phase-5-engineering-quality`
  branch.** The entire Bronze/Silver/Gold/DQ/generator/backfill platform
  this branch hardens was already built and verified in Phase 4. Documented
  as its own initiative (`docs/phase-6-streaming-data-platform.md`);
  `PROJECT_STATUS.md`'s phase table is not renumbered.
- **A real bug, found by actually running the pipeline, not by inspection:
  Silver's dedup watermark was on the wrong timestamp column.**
  `app.silver.build_type_query` declared `dropDuplicatesWithinWatermark`'s
  watermark on `occurred_at_ts` (the event's own business timestamp).
  `app.generator.generate_order_lifecycle` legitimately sets `order.shipped`'s
  `occurred_at` up to 60 minutes after `order.created`'s (a simulated
  shipping delay — real test data, not a generator bug; the
  `fulfillment_latency`/`late_order_rate` Gold datasets need non-trivial
  latency to be meaningful). Running the Phase 6 smoke test
  (`scripts/phase6_smoke_test.sh`) against real Kafka/MinIO data at real
  volume surfaced this: `app.dq.report`'s Bronze-vs-Silver reconciliation
  check failed for `order.shipped` specifically, off by as much as ~44% in
  one run. Root cause: Spark's watermark for a stateful operator advances
  to `max(event time seen) − threshold`; **any** row (not just a
  duplicate) whose watermark-column value trails that already-advanced
  watermark is dropped by Spark itself, upstream of the sink — never
  quarantined, never counted late, just silently gone. One high-latency
  shipment's far-future `occurred_at_ts` could advance the watermark far
  enough to drop a different, valid, lower-latency shipment processed
  afterward. Fixed by watermarking on `ingested_at` (Bronze's ingestion
  wall-clock time) instead — it only moves forward with real processing
  time, so a business-modeled delay can't push it ahead of itself. Added a
  regression test reproducing the exact failure mode with two synthetic
  micro-batches. See `RISKS.md` #21, `docs/phase-6-streaming-data-platform.md`
  section D.
- **Recovered already-lost historical data with the existing backfill tool,
  with explicit confirmation before the destructive step, not a checkpoint
  reset.** This session's persistent MinIO volume had ~64 rows across 4
  event types already silently dropped by the pre-fix code. `app.backfill`'s
  `reprocess_silver` deduplicates with a plain `dropDuplicates` and no
  watermark at all (a watermark on a batch DataFrame is a documented Spark
  no-op), so it was never subject to the bug above and could recover the
  lost rows exactly. Ran a dry-run first (no `--apply`) to confirm full
  reconciliation (`bronze_distinct_event_ids == on_time + late + rejected`)
  for each affected event type, then asked before running `--apply` (which
  deletes-and-replaces the live Silver partition for that event-type/date —
  an existing, documented, sanctioned recovery mechanism, but still a
  destructive action on existing data, and the task's hard restrictions
  require confirmation before that). `app.dq.report` reached
  `overall: PASS` afterward.
- **A second, related finding — verified empirically, not assumed:
  `--once`/`Trigger.AvailableNow()`'s final micro-batch can leave a real,
  non-self-healing reconciliation gap, not just a transient one.** First
  suspected this was ordinary watermark-pending staleness that would clear
  once `DEDUP_WATERMARK` (10 minutes) elapsed; tested that directly by
  waiting 25+ minutes with no new traffic and re-running `silver --once`
  in between (which found nothing new to process) — the gap was
  unchanged. This rules out "just needs time"; it appears Structured
  Streaming gives no guaranteed subsequent trigger to flush a
  watermark-gated stateful operator's pending output once `availableNow`
  decides there's no more source data. Not re-architected this pass
  (would mean changing `--once`'s stop condition for stateful queries) —
  recovered the same way as the historical rows above, via
  `app.backfill silver --apply`, applied twice during this branch's own
  validation to reach a genuine `app.dq.report overall: PASS`. See
  `RISKS.md` #22.
- **Bronze converted from a direct `.writeStream.format("parquet")` sink to
  `foreachBatch`, matching Silver/Gold's already-established pattern —
  needed to add the malformed-JSON quarantine split, and incidentally fixes
  a latent inconsistency.** The original direct-sink approach maintains a
  `_spark_metadata` commit log at the Bronze root (Structured Streaming's
  `FileStreamSink`); `app.dq.report`'s original `_read_layer_for_date`
  helper read that root directly via a plain `spark.read.parquet(path)` —
  which auto-detects `_spark_metadata` when present and silently scopes the
  read to *only* the files that log recorded, hiding every file written
  since by a different mechanism. Once Bronze started writing via
  `foreachBatch` (no `_spark_metadata`) while old `_spark_metadata` from a
  prior session's runs still sat at the Bronze root, `app.dq.report`'s
  Bronze reconciliation read zero rows for real, freshly-written data —
  caught immediately (a completely-failing reconciliation, obviously
  wrong, not a subtle undercounting). Fixed by having `app.dq.report` read
  Bronze the same way `app.backfill` already does: per `event_type=`
  subdirectory (`app.bronze.read_bronze_batch`, unioned across all topics),
  never the poisoned root. This is the same failure class `RISKS.md` #18
  already named for Gold; Bronze was the one remaining layer still using
  the vulnerable pattern.

## 2026-07-25 — Phase 5: Engineering quality

- **This branch's name reuses "Phase 5", but its scope is not the
  `PROJECT_STATUS.md` phase table's Phase 5 (Data quality, already done,
  folded into Phase 4).** Rather than renumber the established 0-13 table —
  which every other doc (README, RISKS, ADRs) cross-references by number —
  this work is documented as its own cross-cutting initiative
  (`docs/phase-5-engineering-quality.md`) that pulls a slice of three later
  phases' scope forward: coverage tooling/threshold (Phase 10), dependency/
  SAST security scanning (part of Phase 9 — JWT/RBAC finalization is not in
  this slice), and CI (Phase 12 — pipeline exists now, but hasn't run in
  GitHub's own hosted environment yet since this repo has no verified
  Actions run at time of writing). `PROJECT_STATUS.md`'s phase table itself
  is not renumbered.
- **A shared `infra/docker/devtools` image, not per-target `pip install`,
  for the new tooling.** Existing targets (`lint`/`format`/`typecheck`)
  already install their own deps ad hoc per invocation — fine when it's one
  tool. `coverage`/`security`/`pre-commit` each need several tools at once
  (coverage+combine, bandit+pip-audit, pre-commit+git), so a single pinned
  image built once via `make setup-dev` and reused is both faster and keeps
  version pins in one place instead of three.
- **Coverage combine reconciles two different absolute roots via
  `[tool.coverage.paths]`, not a rewritten test-collection setup.** Every
  service's own container records absolute paths under `/app/services/<name>`
  (that service's own Dockerfile `WORKDIR`); `event-contracts` alone records
  under `/repo/services/event-contracts` (`make test-contracts` bind-mounts
  the repo at `/repo`, not `/app`). Rather than changing five working
  Dockerfiles' `WORKDIR` or `test-contracts`' mount point to unify these,
  the combine step in `make coverage` bind-mounts the repo at *both* `/app`
  and `/repo` and lets `pyproject.toml`'s `[tool.coverage.paths]` alias
  section fold the two into one relative path per file.
- **Coverage is statement-only, not branch, despite `pyproject.toml`
  declaring `[tool.coverage.run] branch = true`.** Each service's own
  container runs `pytest --cov=app` from a directory that doesn't contain
  the repo-root `pyproject.toml` (only the service's own code is `COPY`'d
  into the image), so pytest-cov never sees `branch = true` at the moment
  it matters — collection time, not report time. Fixing this properly means
  either copying `pyproject.toml` into every service image or passing
  `--cov-branch` explicitly on every `pytest` invocation; deferred as a
  known limitation (`TEST_RESULTS.md`'s Phase 5 entry) rather than done
  speculatively, since it would touch five working Dockerfiles/Makefile
  targets for a coverage-shape change with no immediate threshold impact
  (the current 65% threshold is set against the statement-only number that's
  actually being measured).
- **`COV_THRESHOLD := 65`, measured, not assumed.** `make coverage`'s first
  real combined run (167 tests, six suites) reported 71.6% before any
  threshold existed to pass or fail against. 65 was chosen after seeing that
  number — a few points under it, not at it, so one new untested branch
  doesn't fail CI outright — not picked in advance and then hit by
  adjusting scope to match (`RISKS.md` #4's fabrication-risk mitigation
  extends to this number too).
- **`pip-audit` findings are suppressed by explicit, individually-justified
  `--ignore-vuln` ID, never by a blanket `|| true` or disabling the target.**
  9 of 14 real CVEs found in the first `make security` run are accepted
  risks (documented in full in `RISKS.md` #20): `starlette`'s fixes need a
  `fastapi` major-version bump this codebase can't safely take in this same
  pass (verified: `pip install fastapi==0.115.0 starlette==0.40.0` →
  `ResolutionImpossible`), and `pytest`/`pyarrow`'s are inapplicable to how
  this codebase actually uses them (a test-only dependency's local-tmpdir
  collision in a single-user container; a C++ API pyarrow's own advisory
  says isn't reachable from Python bindings). The other 5 (`pip` itself)
  were fixed outright by pinning `pip==26.1.2` in every Dockerfile, not
  added to the ignore list — ignoring is for what's genuinely accepted, not
  a shortcut around fixing what's fixable.

## 2026-07-25 — Phase 4: Data engineering platform

- Completed the Bronze/Silver/Gold pipeline that was already in progress
  (uncommitted working tree at the start of this phase): all 10 Gold
  datasets, `app.dq` (checks + report), `app.generator` (synthetic event
  generator), and `app.backfill` (Silver/Gold reprocessing tooling) —
  scoping DQ checks/reporting into this phase rather than a separate one,
  since the working tree already had the Spark plumbing in place to build
  on directly.
- **Lateness is measured once, at Silver, not per-Gold-dataset.** Structured
  Streaming doesn't expose a per-row "this was dropped for being late"
  event from inside a windowed aggregation, so a valid row whose Bronze
  `ingested_at` lagged its own `occurred_at` by more than 600s (matching
  Silver's own dedup watermark) is routed to `late_events` instead of
  Silver. This is deliberately not synced to each Gold dataset's own
  watermark (10-30 minutes) — always at least as strict as the narrowest
  one, so it can flag a row "late" that a wider-watermark dataset would
  still have windowed successfully, but never the reverse. See
  `docs/data-pipeline.md`'s "Watermarks and late data".
- **Each Silver query writes to its own base path
  (`silver_path/event_type=<X>`), not a shared path dynamically partitioned
  by `event_type`.** 11 concurrent per-event-type streaming queries writing
  to one shared output path hit a real `_temporary`-staging collision
  against S3A/MinIO's non-atomic rename (`RemoteFileChangedException`,
  killing the query) — caught running this for real against MinIO with
  real generated traffic, not in unit tests, which only ever exercise one
  query at a time. Gold's 9 datasets already had this property (each writes
  to `gold_path/<name>`); Silver and Silver's own batch reprocessing
  (`app.backfill.reprocess_silver`) were changed to match.
- **Gold's live streaming queries write via `foreachBatch` + a plain
  `DataFrame.write` call, not `.writeStream.format("parquet")` directly**
  (a mid-phase change from how it was originally written). The latter uses
  Structured Streaming's `FileStreamSink`, which maintains its own
  `_spark_metadata` commit log — any metadata-aware batch reader (including
  a plain `spark.read.parquet()`) only sees files recorded in that log, so
  `app.backfill`'s swap step (which writes real Parquet files directly via
  S3, bypassing the log) produced files that were physically present but
  invisible to any normal read. Silver's writes never had this problem
  (they were already `foreachBatch` + plain writes); switching Gold to the
  same pattern fixes it at the root rather than trying to hand-roll
  `_spark_metadata` updates, which is an internal, undocumented Spark
  format not meant for external manipulation.
- **`build_spark_session`'s default master is `local[*]`, matching ADR
  0005 exactly — not `local[2]`, which is what the code actually shipped
  with before this phase's testing caught the drift.** Running 11 (Silver)
  or 9 (Gold) genuinely concurrent Structured Streaming queries against too
  few cores, combined with Spark's default FIFO job scheduler, starved some
  queries of scheduled time *indefinitely* under real generated load — not
  merely lag, a query's batch counter stopped advancing entirely. Fixed by
  correcting the default (aligning code with the ADR's already-stated
  decision) and adding `spark.scheduler.mode=FAIR`, which round-robins job
  slots across concurrently running queries instead of a strict FIFO order.
- **Backfill/reprocessing deletes exclusively through `boto3`'s
  single-object `delete_object`, never `s3fs`'s `rm`/`mv`.** This MinIO
  version rejects S3's bulk `DeleteObjects` API (`MissingContentMD5`), and
  `s3fs` routes *every* deletion through that endpoint internally,
  regardless of how many keys are involved — including the delete inside
  `mv`'s copy-then-delete. `boto3`'s single-object `DELETE` is a different,
  simpler code path that doesn't hit this at all.
- **The synthetic generator (`app.generator`) publishes directly onto the
  real Kafka topics**, the same ones `order-service`/`inventory-service`/
  `fulfillment-orchestrator`'s real consumers subscribe to — deliberately,
  since Bronze has to consume the real event catalog either way and a
  separate topic set would mean either duplicating all 11 topics or Bronze
  subscribing to two names per event type. The tradeoff: running the
  generator alongside the real stack makes those real consumers also
  process synthetic events, visible as expected `404 Not Found` responses
  in `fulfillment-orchestrator`'s logs when it looks up a synthetic,
  nonexistent order ID. Confirmed harmless (zero dead letters produced,
  no errors) but worth knowing before reading those logs and assuming
  something is broken — see `RISKS.md`.
- **Real bugs found and fixed while verifying this phase's own test suite
  and running the real stack against MinIO** (full list with detail in
  `TEST_RESULTS.md`): the `DeadLetterEventDataV1.original_event` dict/string
  schema mismatch between `event_contracts` (Phase 2) and Silver's Spark
  schema; `validate()`'s `unknown_schema_version` check comparing the
  query's static parameter instead of each row's own `schema_version`
  column (permanently dead code); Structured Streaming's `PATH_NOT_FOUND`
  on a genuinely fresh environment; partition-column auto-discovery
  freezing before real dated data exists; the concurrent-writer/committer,
  bulk-delete, `_spark_metadata`, and scheduler-starvation issues above; and
  a naive-vs-aware `datetime` subtraction in `check_freshness` (Spark's
  `TimestampType` collects as naive Python `datetime`s even under
  `spark.sql.session.timeZone=UTC`).

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
