# Phase 6: Streaming data-platform hardening

This branch (`phase-6-streaming-data-platform`) hardens the existing Spark
Structured Streaming data platform: Bronze-level malformed-JSON quarantine,
Prometheus observability for the Spark jobs (closing `RISKS.md` #19), a
real bug fix in Silver's deduplication watermark (found by actually running
the pipeline, not by inspection), a data-lake inspection CLI, and an
end-to-end Phase 6 smoke test.

**Naming note**, same pattern as `docs/phase-5-engineering-quality.md`:
`PROJECT_STATUS.md`'s 0–13 phase table already has a "Phase 6: Demand
forecasting," not started. This document is *not* that phase — the branch
name collides with it by coincidence. The entire Bronze/Silver/Gold/DQ/
generator/backfill platform this document extends was already built and
verified in **Phase 4** (folded with the former Phase 5/data-quality) — see
`docs/data-pipeline.md` for the original design and `PROJECT_STATUS.md` for
what already existed before this branch. This branch is a pulled-forward
hardening slice on top of that, not a rebuild of it. `PROJECT_STATUS.md`'s
phase table is not renumbered by this work.

## What already existed (Phase 4 baseline — not rebuilt here)

- `app/bronze.py` — Kafka (all 11 event-catalog topics) → raw Parquet,
  `event_type`/`date` partitioned.
- `app/silver.py` — one streaming query per event type: schema validation
  → `silver_rejects`, `dropDuplicatesWithinWatermark` dedup, lateness
  detection → `late_events`.
- `app/gold/` — 9 streaming aggregations + `app/lag_poller.py` (consumer
  lag, polled directly, not via Spark).
- `app/dq/` — Bronze-vs-Silver reconciliation, rejection/duplicate/late
  rate, freshness checks → JSON report.
- `app/generator.py` — deterministic synthetic event generator with
  duplicate/late injection.
- `app/backfill.py` — bounded-range Silver/Gold batch reprocessing with
  row-count validation and side-path swap.
- `tests/test_restart.py` — checkpoint-based restart-doesn't-reprocess
  test.
- Already wired into `make coverage`/`make typecheck`/`make docker-build`
  and `.github/workflows/ci.yml`.

Full design of all of the above: `docs/data-pipeline.md` (unchanged except
where noted below) and `docs/event-catalog.md` (source of truth for topics/
schemas — unchanged, no new topics or event types introduced by this
branch).

## What this branch adds

### A. Bronze malformed-JSON quarantine

**Gap found**: a Kafka record whose `value` wasn't parseable JSON (or was
empty/a JSON object missing both `event_id` and `event_type`) parsed to an
all-null envelope and was written into Bronze under an unusable
`event_type=null/date=null` partition — invisible to Silver (which only
ever reads a specific `event_type=<X>` subdirectory) and invisible to
`app.dq.report`. Not literally dropped, but silently orphaned rather than
visibly quarantined.

**Fix** (`app/bronze.py`):
- `transform_to_bronze` now filters out malformed rows before writing to
  Bronze.
- `transform_to_bronze_rejects` (new) captures exactly the complement:
  malformed rows, with the raw Kafka coordinates (`kafka_topic`,
  `kafka_partition`, `kafka_offset`, `kafka_timestamp`), the raw string
  `value` (so an operator can see exactly what the bus carried), a
  `reason` (`empty_kafka_value` or `unparseable_or_empty_envelope`), and
  `ingested_at`/`date` (ingestion date — event time is unknown for a
  malformed payload by definition).
- `write_bronze_stream` was converted from a direct
  `.writeStream.format("parquet")` sink to a `foreachBatch` writer (matching
  Silver/Gold's already-established pattern) that splits each micro-batch
  into valid/malformed, writes each to its own path, and logs both counts.
- New MinIO prefix: `bronze_rejects` (added to
  `infra/docker/minio/create-buckets.sh`), new `Settings.bronze_rejects_path`.

**Distinct from `silver_rejects`**: Bronze's quarantine catches JSON that
never parsed into an envelope at all; Silver's quarantine catches a
*parseable* envelope that fails schema/business validation (unknown
`schema_version`, missing required field, etc.). Two different failure
modes, two different quarantine locations, both never silently dropped.

Tests: `tests/test_bronze.py` (6 new cases — malformed JSON, valid-JSON-
wrong-shape, reject reasons, and a mixed-batch "every row lands in exactly
one of the two outputs" test).

### B. Prometheus metrics for Bronze/Silver/Gold (closes `RISKS.md` #19)

**Gap found** (already flagged, not discovered by this branch):
`docker-compose.yml`'s `spark-bronze`/`spark-silver`/`spark-gold` declared
and exposed a `METRICS_PORT`, but no code ever started a `prometheus_client`
server on it, and `prometheus_client` wasn't even a dependency.

**Fix**:
- `app/metrics.py` (new) — `start_metrics_server(port)` (idempotent per
  process), `data_platform_batch_rows_total{layer,dataset,status}` (a
  Counter — e.g. `status=valid|malformed` for Bronze,
  `on_time|late|invalid` for Silver, `output` for Gold),
  `data_platform_batch_duration_seconds{layer,dataset}` (a Histogram around
  each `foreachBatch` invocation).
- `app/bronze.py`/`app/silver.py`/`app/gold/common.py` each call
  `start_metrics_server(settings.metrics_port)` once in `main()` and
  wrap/record their existing per-batch row counts.
- `prometheus-client==0.21.0` added to `services/data-platform/requirements.txt`
  (already installed in the shared `make typecheck` image from Phase 3).
- `infra/docker/prometheus/prometheus.yml` — three new scrape targets
  (`spark-bronze:9106`, `spark-silver:9107`, `spark-gold:9108`).
  `lag-poller` has no `METRICS_PORT`/scrape target — it's a lightweight
  pyarrow/s3fs loop, not a Spark job, and was out of #19's original scope.

Tests: `tests/test_metrics.py` (record/duration/idempotent-start, using
`prometheus_client`'s public `collect()` API, not private attributes, so it
doesn't break across `prometheus_client` versions).

### C. Data-lake inspection CLI

`app/inspect.py` (new) — `python -m app.inspect <prefix>` (e.g. `bronze`,
`bronze_rejects`, `silver_rejects`, `late_events`, `gold`): lists a MinIO
prefix via boto3, reports object count/total bytes broken out by top-level
partition, and prints up to `--limit` sample keys. No Spark session needed.
Backs the `make inspect-*` targets (below) and the Phase 6 smoke test's
assertions. Tests: `tests/test_inspect.py` (pure `summarize()` logic, no
network).

### D. A real bug found and fixed: Silver's dedup watermark column

**Found running the Phase 6 smoke test against real Kafka/MinIO data**, not
by inspection: `app.dq.report`'s Bronze-vs-Silver reconciliation check
failed for `order.shipped` specifically, off by a large margin (as much as
~44% of that type's rows in one run).

**Root cause**: `app.silver.build_type_query` declared its dedup watermark
on `occurred_at_ts` — the event's own *business* timestamp.
`app.generator.generate_order_lifecycle` legitimately sets `order.shipped`'s
`occurred_at` up to **60 minutes after** `order.created`'s (a simulated
shipping delay — real, meaningful test data for the
`fulfillment_latency`/`late_order_rate` Gold datasets, which need non-trivial
latency to be worth anything). Spark's watermark for a stateful operator
like `dropDuplicatesWithinWatermark` advances to `max(event time seen) -
threshold`, and any operator input row (**not just duplicates**) whose
watermark-column value trails that advanced watermark is dropped by Spark
itself, upstream of `_write_batch` — never reaching Silver, never
reaching `silver_rejects`, never counted late, just gone. One high-latency
shipment's far-future `occurred_at_ts` could advance the watermark far
enough that a *different*, perfectly valid, lower-latency `order.shipped`
event processed afterward would fall behind it and vanish.

`docs/data-pipeline.md`'s original text ("a duplicate arriving after the
dedup watermark has closed is not caught") undersold this — it isn't only
late *duplicates* that are at risk; any row can be, if the watermark column
can legitimately swing far ahead of real time for that event type.

**Fix** (`app/silver.py`, `build_type_query`): watermark declared on
`ingested_at` (Bronze's ingestion wall-clock time, `F.current_timestamp()`
at Bronze write) instead of `occurred_at_ts`. `ingested_at` only moves
forward with real processing time, so it can't be pushed arbitrarily ahead
by a business-modeled delay the way `occurred_at` can. `mark_lateness`'s own
late-event classification (`ingested_at` − `occurred_at_ts`) is unaffected
— it already used `ingested_at` for exactly this reason; this fix
generalizes that same reasoning to the dedup watermark.

Regression test: `tests/test_silver.py::test_dedup_watermark_on_ingested_at_survives_wide_occurred_at_swings`
— two micro-batches, the first with a far-future `occurred_at_ts` but a
present `ingested_at`, the second with a normal `occurred_at_ts` and a
`ingested_at` only seconds later; asserts both survive.

**Recovering already-affected historical data**: this session's persistent
MinIO volume had ~64 rows across 4 event types already silently dropped by
the pre-fix code before this branch's work began. `app.backfill`'s Silver
reprocessing (`reprocess_silver`) uses a plain `dropDuplicates(["event_id"])`
with **no watermark at all** (a watermark on a batch DataFrame is a
documented Spark no-op — see `docs/data-pipeline.md`'s "Backfill process"),
so it was never subject to this bug and could fully recover the lost rows.
Used for real, with explicit confirmation before the destructive
swap step (`--apply` deletes-and-replaces the live partition):
`app.backfill silver --event-type order.shipped --from-date 2026-07-26
--to-date 2026-07-26 --apply` (and the same for `order.created`,
`order.validated`, `inventory.reservation.requested`) — each fully
reconciled (`bronze_distinct_event_ids == on_time + late + rejected`)
before the swap, per `reprocess_silver`'s own row-count-validation
guarantee. `app.dq.report` reached a clean `overall: PASS` afterward.
Full detail: `DECISIONS.md`.

**A related, separate, open finding — verified empirically, not assumed**:
a Bronze-vs-Silver reconciliation gap left by the final `--once` micro-batch
of a Silver run does **not** self-heal with time. Tested directly: after
waiting 25+ minutes with no new traffic — well past `DEDUP_WATERMARK` (10
minutes) — and re-running `silver --once` in between (which found nothing
new to process), the same gap persisted unchanged. This rules out "just
pending watermark state that resolves once the watermark advances"; it
appears `Trigger.AvailableNow()` gives no guaranteed subsequent trigger to
re-evaluate and emit a watermark-gated stateful operator's pending output
for its last batch, once it decides there's no more source data. Not
re-architected this pass (would mean changing `--once`'s stop condition
for stateful queries) — recovered the same way as the historical rows
above, via `app.backfill silver --apply` (no watermark, never subject to
this), applied twice during this branch's own validation to reach a
genuine `app.dq.report` `overall: PASS`. See `RISKS.md` #22.

### E. Synthetic generator: malformed-record injection

`app/generator.py` gained `--malformed-rate` (default `0`, opt-in):
`publish_malformed` publishes an intentionally-broken raw payload directly
to Kafka (bypassing `publish_envelope`'s schema validation), exercising
Bronze's new malformed-JSON quarantine end-to-end against real Kafka/
Parquet. Existing `--duplicate-rate`/`--late-rate` unchanged.

### F. Phase 6 end-to-end smoke test

`scripts/phase6_smoke_test.sh` (`make phase6-smoke`): generates deterministic
synthetic traffic (with duplicate/late/malformed injection) → runs Bronze
twice in a row (proving the second run doesn't reprocess already-committed
Kafka offsets — a live restart/checkpoint check) → runs Silver → runs Gold
→ runs the DQ report, inspecting every layer via `app.inspect` along the
way. Complements `scripts/compose_smoke_test.sh` (order-service/inventory-
service/fulfillment-orchestrator saga — doesn't touch the data platform).

Every `docker compose run` call passes `--no-deps` and is wrapped in a
retry helper: this host's Docker Desktop WSL2 backend has an intermittent
bind-mount race recreating the one-shot `minio-init` dependency container
in rapid succession (a real, reproducible flake hit writing this script,
unrelated to this branch's own logic) — documented in the script itself and
in "Troubleshooting" below.

### G. Makefile targets

`streaming-up`/`streaming-down` (start/stop only the Spark services),
`inspect-bronze`/`inspect-bronze-rejects`/`inspect-silver`/
`inspect-silver-rejects`/`inspect-late-events`/`inspect-gold`,
`phase6-smoke`, `phase6-validate` (tests + smoke + `make ci`), `clean-phase6`
(removes only local pytest/mypy/ruff caches under
`services/data-platform` — never touches MinIO data, checkpoints, Kafka
topics, or any Docker volume). `make help` lists all of them (self-
documenting via the existing `## ` comment convention).

## Architecture

Unchanged from Phase 4 — see `docs/architecture.md` and
`docs/data-pipeline.md` for the full diagrams/design. This branch adds two
new object-storage prefixes (`bronze_rejects`, and the pre-existing
`_backfill`-suffixed side paths used more heavily now for the Silver
recovery above) and three new Prometheus scrape targets; no new services,
topics, or event types.

## Source topics / event-time model / schema strategy

Unchanged — all 11 topics from `docs/event-catalog.md`, envelope schema
unchanged, `app/schemas.py`'s Bronze/Silver schema registry unchanged.

## Storage layout and partitioning

| Layer | Path | Partitioning |
|---|---|---|
| Bronze | `s3a://<bucket>/bronze` | `event_type=<X>/date=<Y>` |
| Bronze quarantine (**new**) | `s3a://<bucket>/bronze_rejects` | `date=<Y>` only (event type unknown for malformed payloads) |
| Silver | `s3a://<bucket>/silver/event_type=<X>` | `date=<Y>` |
| Silver rejects | `s3a://<bucket>/silver_rejects/event_type=<X>` | `date=<Y>` |
| Late events | `s3a://<bucket>/late_events/event_type=<X>` | `date=<Y>` |
| Gold | `s3a://<bucket>/gold/<dataset>` | dataset-specific (see `docs/data-pipeline.md`) |
| DQ reports | `s3a://<bucket>/dq-reports/date=<Y>` | `date=<Y>` |

## Checkpoint layout

Unchanged: `s3a://<bucket>/checkpoints/<layer>/<dataset-or-event-type>`.
Bronze's checkpoint location and semantics are unchanged by the
`foreachBatch` conversion — Kafka offsets are still tracked the same way;
only the *sink* mechanism changed (see "Malformed-event handling" above).

**Checkpoint compatibility note**: converting Bronze from a direct
`.writeStream.format("parquet")` sink to `foreachBatch` did not require a
checkpoint reset in this environment (verified: the existing Bronze
checkpoint reloaded and resumed correctly). Silver's watermark-column
change (`occurred_at_ts` → `ingested_at`) also reloaded without error in
this environment. Neither is a guarantee for every Spark version — a query
plan change *can* require a fresh checkpoint in general; if a future schema
or plan change ever does throw a checkpoint-incompatibility error, the
correct response is a fresh checkpoint path for the affected query only
(never delete/reuse another query's checkpoint), with explicit confirmation
before doing so (see "Recovery behavior" below).

## Deduplication (updated)

`dropDuplicatesWithinWatermark(["event_id"])`, watermark now on `ingested_at`
(was `occurred_at_ts` — see finding D above). `DEDUP_WATERMARK = "10
minutes"`, unchanged.

## Watermark and late-data behavior

`LATE_THRESHOLD_SECONDS = 600` (10 minutes), measured as `ingested_at −
occurred_at_ts`, unchanged — this was already correctly using `ingested_at`
before this branch (only the *dedup* watermark was on the wrong column).
Gold's own per-dataset watermarks (10–30 minutes, `app/gold/queries.py`),
also unchanged.

## Malformed-event handling / quarantine strategy

Two distinct, documented quarantine locations:
1. **`bronze_rejects`** (new, this branch) — unparseable JSON / not an
   envelope at all. Reason column: `empty_kafka_value` or
   `unparseable_or_empty_envelope`.
2. **`silver_rejects`** (Phase 4, unchanged) — a parseable envelope that
   fails schema/business validation. Reason column: e.g.
   `unknown_schema_version`, `missing_event_id`, `invalid_timestamp`,
   `missing_required_field:<name>`.

Neither ever silently drops a row.

## Data-quality rules

Unchanged (`app/dq/checks.py`): Bronze-vs-Silver reconciliation (gating),
schema-rejection-rate ≤ 5% (gating), duplicate-rate (informational),
late-event-rate ≤ 10% (gating), freshness ≤ 60 minutes (gating). See
finding D above for the one behavioral nuance this branch surfaced:
reconciliation is only meaningful measured against a **settled** date (see
Limitations).

## Synthetic event generator

`--orders`, `--dead-letters`, `--duplicate-rate`, `--late-rate`, `--seed`
(all Phase 4, unchanged), `--malformed-rate` (**new**, default `0`).

## Backfill and reprocessing

Unchanged tool (`app/backfill.py`), newly exercised for a real recovery (see
finding D above) rather than only in tests.

## Local setup

```bash
cp .env.example .env
make demo                 # full stack, including spark-bronze/silver/gold
make generate ARGS="--orders 50 --malformed-rate 0.1"
make phase6-smoke          # end-to-end: generate -> bronze -> silver -> gold -> dq-report
```

## Configuration

Unchanged env vars (`app/config.py`, all `DATA_PLATFORM_`-prefixed or
shared infra vars already in `.env.example`): `KAFKA_BOOTSTRAP_SERVERS`,
`MINIO_ENDPOINT`, `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` (local dev
credentials only — see `.env.example`), `DATA_LAKE_BUCKET`, `METRICS_PORT`.
No new configuration surface added by this branch beyond
`Settings.bronze_rejects_path` (derived from `DATA_LAKE_BUCKET`, not a new
env var).

## Makefile commands

See "G. Makefile targets" above; run `make help` for the full, current,
self-documenting list.

## Test strategy

Unit (pure functions, no Spark session): `app.inspect.summarize`,
`app.metrics` (with `collect()`, no live network). Local Spark tests (real
`SparkSession`, no live Kafka/MinIO): malformed-JSON routing
(`test_bronze.py`), the watermark-column regression
(`test_silver.py`), metrics/duration recording. Integration/smoke (real
Kafka/MinIO/Spark, `make phase6-smoke`): synthetic traffic → Bronze
(twice, restart check) → Silver → Gold → DQ report, with `app.inspect`
assertions at every layer.

## End-to-end demonstration

`make phase6-smoke` — see script output in `TEST_RESULTS.md` for a real,
captured run.

## Observability

Prometheus metrics (finding B above): `data_platform_batch_rows_total`,
`data_platform_batch_duration_seconds`, scraped from
`spark-bronze:9106`/`spark-silver:9107`/`spark-gold:9108`. Structured
logging (unchanged, Phase 4): every batch write logs row counts by outcome
(Bronze: valid/malformed; Silver: on-time/late/rejected; Gold: output),
batch id, and dataset/event-type name — see each module's `logger.info(...)`
calls.

## Recovery behavior

Bronze/Silver/Gold checkpoints: unchanged Phase 4 semantics — restarting a
`--once` job resumes from its own checkpoint, verified by
`tests/test_restart.py` and by the smoke test's live Bronze restart check.
**Never** reset a checkpoint as part of normal validation — the one time
this branch needed to recover already-lost data (finding D), it used
`app.backfill`'s existing, documented, row-count-validated recovery path
with explicit confirmation before the destructive swap step, not a
checkpoint deletion.

## Limitations

- **`--once`/`Trigger.AvailableNow()` gives no guaranteed extra flush
  cycle, and this does not self-heal with time — verified, not assumed.**
  If the final micro-batch of a `--once` Silver run contains new data, its
  watermark-gated `dropDuplicatesWithinWatermark` output isn't guaranteed
  to be re-evaluated and emitted before the query stops. Tested directly:
  the resulting reconciliation gap did **not** shrink after waiting 25+
  minutes with no new traffic (well past `DEDUP_WATERMARK`'s 10 minutes),
  with a repeated `silver --once` run in between finding nothing new to
  process — so this is not "pending state that resolves once the watermark
  advances," it genuinely persists until either new data triggers a
  subsequent batch or a batch reprocess is run. Recovered via
  `app.backfill silver --apply` (no watermark, never subject to this) —
  applied twice during this branch's own validation to reach a genuine
  `app.dq.report overall: PASS`. The long-running, continuously-triggering
  production services (real `docker compose up`, not `--once`) are far
  less exposed in practice, since they keep triggering new batches — but
  this wasn't verified to make them immune, only less exposed. Not
  data-loss in the sense of an at-least-once guarantee violation (the
  source Kafka data and Bronze copy are both intact — `app.backfill` can
  always recover it), but it is a real gap in the *streaming* path
  specifically. See `RISKS.md` #22.
- Every Phase 4 limitation in `docs/data-pipeline.md`/`RISKS.md` still
  applies unchanged (non-atomic backfill swap, single fixed lateness
  threshold not synced per-Gold-dataset, etc.).

## Troubleshooting

- **`docker compose run` intermittently fails with `error mounting ...
  create-buckets.sh ... no such file or directory`**: a Docker Desktop
  WSL2 bind-mount race recreating the one-shot `minio-init` container.
  Retry the command — `scripts/phase6_smoke_test.sh` already does this
  automatically (`run_with_retry`) and passes `--no-deps` on every
  `spark-gold` invocation after the first to avoid re-triggering
  `minio-init` unnecessarily.
- **`app.dq.report` reconciliation fails after a `--once` smoke-test run,
  and doesn't clear even after waiting**: this is `RISKS.md` #22, not a
  regression — run `app.backfill silver --event-type <X> --from-date <Y>
  --to-date <Y>` (no `--apply`) to confirm/quantify the gap, then
  `--apply` to recover it.
- **A specific event type's Silver data looks short**: use
  `make inspect-bronze`/`inspect-silver`/`inspect-late-events` to compare
  counts by `event_type=` partition; if a genuine gap is found, `app.backfill
  silver --event-type <X> --from-date <Y> --to-date <Y>` (without
  `--apply`) reports exact row counts without touching the live path.

## Acceptance criteria (this branch's scope)

- [x] Existing event topics/contracts used correctly (no new/changed
  topics or schemas).
- [x] Bronze malformed-JSON quarantine implemented and tested.
- [x] Spark job Prometheus metrics implemented (closes `RISKS.md` #19).
- [x] Real bug found and fixed (Silver dedup watermark column), with a
  regression test.
- [x] Historical data recovered via the existing backfill tool, with
  explicit confirmation before the destructive swap.
- [x] Data-lake inspection CLI + Makefile targets.
- [x] Phase 6 end-to-end smoke test (`make phase6-smoke`).
- [x] All existing Phase 4/5 tests still pass; new tests added, none
  weakened.
- [x] `make ci` still passes (format, lint, typecheck, coverage, security,
  docker-validate, docker-build).
- [x] Documentation updated (this file, plus `docs/data-pipeline.md`,
  `RISKS.md`, `DECISIONS.md`, `PROJECT_STATUS.md`, `README.md`,
  `TEST_RESULTS.md`).

## Zero-cost compliance

Every command in this branch is local Docker Compose against Redpanda,
MinIO, and Spark already running on this host — no AWS, no paid services,
no cloud deployment, no `terraform apply`. `prometheus-client` is the same
zero-cost, already-used-elsewhere-in-this-repo library every other worker
uses. No new paid dependency, image, or infrastructure introduced.
