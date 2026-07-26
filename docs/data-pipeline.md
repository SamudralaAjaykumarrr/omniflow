# Data Pipeline

PySpark Structured Streaming, run single-node (`local[*]`) inside a container
for the local demo (ADR 0005). Source is Redpanda (all 11 topics from
`docs/event-catalog.md`); sink is Parquet on MinIO, S3 API-compatible so the
same job targets real S3 unchanged in the AWS deployment story.

## Layers

### Bronze — immutable raw events
- One Spark read per topic (or a single multiplexed read with `event_type`
  discriminating), written as-is: full envelope + payload, plus
  Kafka-provided `topic`, `partition`, `offset`, `kafka_timestamp`.
- Append-only, never updated or deleted. This is the system of record for
  "what did the bus actually carry" and the input to any reprocessing.
- Partitioned by `event_type` and `date(occurred_at)`.
- **Malformed-event handling** (Phase 6): a Kafka record whose `value`
  isn't parseable JSON matching the envelope shape (or is empty) is routed
  to a `bronze_rejects` path instead — kept with its raw Kafka coordinates,
  raw string value, and a reason (`empty_kafka_value` or
  `unparseable_or_empty_envelope`), partitioned by ingestion date only
  (event time is unknown by definition for a malformed payload). Distinct
  from Silver's `silver_rejects`, below, which quarantines a *parseable*
  envelope that fails schema/business validation — never conflated. See
  `docs/phase-6-streaming-data-platform.md` section A.

### Silver — validated, deduplicated, normalized
- Reads Bronze (streaming), applies:
  - **Schema validation** against the envelope + per-event schema
    (`docs/event-catalog.md`); invalid rows are quarantined to a
    `silver_rejects` path with the validation failure reason, not dropped
    silently.
  - **Deduplication** by `event_id` using `dropDuplicatesWithinWatermark`
    (Spark 3.5+) over a watermark window — handles redelivery from
    at-least-once producers/consumers without unbounded state growth.
  - **Normalization**: timestamps coerced to UTC `timestamp`, enums
    validated against known value sets, nested `data` flattened per event
    type into typed columns.
- Written to `silver_path/event_type=<X>/date(occurred_at)/` — one query
  per event type, each writing to its own base path rather than a path
  shared across all 11 concurrent queries and dynamically partitioned by
  `event_type`. The latter hit a real `_temporary`-staging collision
  against S3A/MinIO's non-atomic rename under concurrent writers (Phase 4);
  a distinct base path per event type sidesteps it entirely. Physically
  the same directory shape either way — only the write-time mechanism
  differs.

### Gold — business-ready aggregations
Ten datasets, each a Structured Streaming aggregation over Silver with
watermark + windowed grouping, written as Parquet with `overwrite`/`append`
per micro-batch via `foreachBatch` (so each gold table can use the merge
semantics it needs — most are append-only rollups, a couple need upsert-by-key):

| Gold dataset | Source events | Aggregation |
|---|---|---|
| Orders per minute | `order.created` | Count, 1-min tumbling window |
| Revenue by product and location | `order.shipped` + `order_items` (joined from Silver) | Sum(qty × unit_price) by `sku, node_id`, 1-hour tumbling window |
| Fulfillment success rate | `order.shipped` vs `order.failed` | shipped / (shipped + failed), 1-hour window |
| Average fulfillment latency | `order.created` → `order.shipped` | avg(shipped.occurred_at − created.occurred_at), 1-hour window |
| Inventory reservation failure rate | `inventory.reserved` vs `inventory.rejected` | rejected / (reserved + rejected), 1-hour window |
| Stockout frequency | `inventory.rejected` | count by `sku` (not `sku, node_id` — the real `inventory.rejected` payload evaluates a rejection across all candidate nodes, not attributed to one; see `app.gold.queries` module docstring), 1-hour window |
| Late-order rate | `order.shipped` vs `fulfillment.assigned.estimated_ship_date` | count where actual > estimate, 1-hour window |
| Product demand by time window | `order.created` items | qty summed by `sku` (not `sku, node_hint` — the real `order.created` item payload has no `node_hint` field; see `app.gold.queries` module docstring), 15-min tumbling window (originally scoped to feed forecasting — as built in Phase 6, `app.forecasting` reads a deterministic synthetic history instead, precisely because this dataset has no location dimension to build a SKU x location grain from; see `docs/phase-6-demand-forecasting.md`) |
| Dead-letter volume | `deadletter.event` | count by `event_type, failed_consumer`, 1-hour window |
| Consumer processing lag | Kafka consumer-group offsets, polled directly (`app.lag_poller`, independent of Spark — see that module's docstring for why) | max(latest_offset − committed_offset) by topic/consumer group |

## Watermarks and late data

Each streaming aggregation declares a watermark on `occurred_at`
(`withWatermark("occurred_at", "10 minutes")` by default, tuned per dataset —
e.g. fulfillment-latency needs a longer watermark since ship time can lag
order time by design). Structured Streaming doesn't expose a per-row "this
was dropped for being late" event from inside a windowed aggregation, so
lateness is measured once, earlier, at Silver: a valid row whose Bronze
`ingested_at` lagged its own `occurred_at` by more than
`LATE_THRESHOLD_SECONDS` (600s, matching Silver's own dedup watermark) is
routed to a `late_events` side path (same schema as Silver plus a
`dropped_reason: "late"` flag) instead of being written to Silver at all, so
late data is visible and auditable rather than invisibly discarded.

This single, fixed threshold is deliberately not synced to each Gold
dataset's own watermark (10-30 minutes) individually — it is always at least
as strict as the narrowest one (10 minutes), so it can flag a row "late" that
a wider-watermark dataset (e.g. fulfillment-latency's 30 minutes) would still
have windowed successfully. A documented, deliberate false-positive-safe
simplification: it can route a row to `late_events` that one particular Gold
dataset didn't actually need to drop, but it never lets a row Gold *would*
drop reach Silver silently.

## Duplicate handling

At-least-once delivery means the same `event_id` can arrive more than once at
every layer. Bronze keeps every delivery (it is the raw record). Silver
deduplicates by `event_id` within the watermark window. Gold aggregates read
only from deduplicated Silver, so duplicate delivery cannot double-count
revenue or order counts — this is the concrete mechanism behind the
"idempotent pipeline" claim, and it is bounded (a duplicate arriving after the
dedup watermark has closed is not caught — documented as a known limitation,
mitigated by keeping the watermark wider than the observed p99 redelivery
delay).

**Watermark column, and why (Phase 6)**: the dedup watermark is declared on
`ingested_at` (Bronze's ingestion wall-clock time), not `occurred_at`
(the event's own business timestamp) — a real bug, found running the
pipeline end-to-end, not by inspection: `occurred_at` can legitimately swing
far ahead of real time for some event types (`order.shipped`'s simulated
shipping delay is up to 60 minutes after `order.created`'s), and Spark's
watermark for a stateful operator drops **any** row (not just duplicates)
whose watermark-column value trails an already-advanced watermark — a
row that reaches the operator after a far-future-dated sibling has already
advanced the watermark past it is silently dropped upstream of every sink,
never quarantined, never counted late. `ingested_at` only moves forward
with real processing time, so it can't be pushed ahead of itself by a
business-modeled delay. Full writeup: `docs/phase-6-streaming-data-platform.md`
section D, `RISKS.md` #21, `DECISIONS.md`.

**`--once` mode's final batch can leave a real, non-self-healing gap**:
verified directly, not assumed — a reconciliation gap left by the last
`--once` micro-batch of a Silver run did not shrink after waiting 25+
minutes (well past `DEDUP_WATERMARK`'s 10 minutes) with no new traffic and
a repeated no-op `silver --once` run in between. `Trigger.AvailableNow()`
gives no guaranteed subsequent trigger to flush a watermark-gated stateful
operator's pending output once it decides there's no more source data.
Not a regression of the fix above, and not data loss in the source/Bronze
sense (Kafka and Bronze both still have it) — but the *streaming* Silver
path can genuinely strand it until either new data arrives or
`app.backfill silver --apply` (no watermark, unaffected) reprocesses it,
which is exactly what this branch's own validation needed to do to reach
a genuine `app.dq.report overall: PASS`. See `RISKS.md` #22.

## Checkpointing

Every streaming query has its own checkpoint location under
`s3a://omniflow/checkpoints/<layer>/<dataset>/`, storing Kafka offsets and
aggregation state. Restarting a job resumes exactly where it left off —
no reprocessing, no gap — which is what makes the pipeline safe to restart
after a crash or deploy.

## Partitioning strategy

Bronze/Silver: `event_type=.../date=YYYY-MM-DD/` — this keeps single-event-type
backfills and date-range reprocessing cheap (partition pruning) and matches
how the data-quality and replay tooling scope their reads. Gold: partitioned
by the dataset's natural grouping key (e.g. `date` for time-series rollups,
`node_id` for per-node datasets) chosen per-table for the read patterns the
dashboard actually uses.

## Backfill process

Implemented by `app.backfill` (`python -m app.backfill gold --dataset
<name> --from-date <Y> --to-date <Y> [--apply]`, or `make backfill
ARGS="gold --dataset ..."`). To backfill a dataset (e.g. after fixing a bug
in the revenue aggregation):
1. Re-run it in **batch** mode (`app.backfill.reprocess_gold`) reading the
   full Silver history for the affected date range — a watermark/window
   declared on a batch DataFrame is a documented Spark no-op, so the same
   `app.gold.queries` functions the live streaming queries use apply
   unchanged — writing to a side path (`<gold_path>_backfill/<name>/`).
2. Row-count-validate the backfilled output (`app.backfill` reports the
   count; a real data-quality reconciliation pass is `app.dq.report`).
3. Swap the validated output into the live Gold path (`--apply`). This is a
   **best-effort per-file copy+delete**, not atomic across the whole date
   range — MinIO/S3 have no "atomically replace this directory" primitive.
   A crash mid-swap can leave a partial mix of old/new files; re-running
   the same backfill is safe (it overwrites the side path and re-copies
   every affected file).
4. Restart the streaming query from a fresh checkpoint pointing past the
   backfilled range — a separate, deliberate operational step (stopping and
   restarting a running container), not automated by the tool.

## Reprocessing process

Implemented by the same tool (`python -m app.backfill silver --event-type
<X> --from-date <Y> --to-date <Y> [--apply]`). To reprocess from Bronze
(e.g. a Silver validation bug dropped rows that should have passed):
re-run the Silver job in batch mode over the affected Bronze partitions
with the fix applied (`app.backfill.reprocess_silver`), writing to a side
path; validates that every distinct Bronze `event_id` in range was
accounted for (on-time + late + rejected) before writing anything, raising
rather than silently swapping an inconsistent result. Then swap (same
non-atomic caveat as above) and restart streaming — same shape as backfill,
one layer earlier. Because Bronze is immutable and partitioned by date,
reprocessing is always bounded to "replay this date range," never "replay
everything."

## Schema evolution strategy

Bronze stores the envelope loosely-typed (payload as JSON string/variant) so a
new event field never breaks Bronze ingestion. Silver's per-event-type schema
is versioned alongside `docs/event-catalog.md`'s `schema_version`; a new
minor/patch version is handled by a nullable-column-additive Silver schema
change (old and new both parse); a major version bump (new topic name) gets
its own Silver table until the migration window closes, then a one-time merge.

## Data-quality checks

`app.dq.checks`/`app.dq.report` (`python -m app.dq.report [--date Y]`, or
`make dq-report`) run against one date's real Bronze/Silver/`silver_rejects`/
`late_events` Parquet: Bronze-vs-Silver reconciliation (every distinct
Bronze `event_id` for the date should be accounted for as on-time, late, or
rejected in Silver — broken out per `event_type` so one type's mismatch
isn't averaged away by the others), schema-rejection-rate, duplicate-rate
(informational — at-least-once delivery makes some rate expected, not a
defect), late-event-rate, and freshness. Writes a JSON report to
`s3a://<bucket>/dq-reports/date=<Y>/report.json` and exits non-zero if a
gating check failed, so it's safe to wire into a scheduler directly.

## Synthetic event generator

`app.generator` (`python -m app.generator [--orders N] [--dead-letters N]
[--duplicate-rate R] [--late-rate R] [--malformed-rate R]`, or `make
generate`) publishes a realistic, causally-chained stream of the 11
event-catalog event types directly onto Kafka, validated against
`event_contracts.schemas` before publish — the same contract every real
producer in this system is held to. Publishes onto the same real topics the
real order-service/inventory-service/fulfillment-orchestrator consumers
subscribe to (Bronze consumes the real event catalog either way), so those
real consumers also see synthetic events — harmless (they 404 looking up a
synthetic order ID that doesn't exist in Postgres, producing no dead
letters), but expected noise in their logs when the generator has been run.
`--duplicate-rate`/`--late-rate` deliberately exercise Silver's dedup and
late-event paths end-to-end with real Kafka/Parquet, not just hand-built
unit-test DataFrames. `--malformed-rate` (Phase 6, default 0, opt-in)
publishes an intentionally-broken raw payload directly (bypassing schema
validation) to exercise Bronze's malformed-JSON quarantine the same way.

## Spark job metrics (Phase 6)

`app.bronze`/`app.silver`/`app.gold.runner` each start a standalone
`prometheus_client` HTTP server on their `METRICS_PORT` (already declared in
`docker-compose.yml`) and record `data_platform_batch_rows_total{layer,
dataset,status}` and `data_platform_batch_duration_seconds{layer,dataset}`
per micro-batch — closes `RISKS.md` #19. Scraped by Prometheus
(`infra/docker/prometheus/prometheus.yml`) alongside every other service/
worker. `app.lag_poller` is intentionally not instrumented this way — it's
a lightweight pyarrow/s3fs loop, not a Spark job.

## Consumer lag and pipeline metrics

Kafka consumer-group lag (per topic/partition) is scraped and exposed as a
Prometheus metric (`docs/reliability.md`), and also lands in the "Consumer
processing lag" Gold dataset above so it is visible both operationally
(Grafana, real-time) and historically (dashboard pipeline-health screen,
queryable trend).
