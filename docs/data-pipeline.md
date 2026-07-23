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
- Partitioned by `event_type` and `date(occurred_at)`.

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
| Stockout frequency | `inventory.rejected` | count by `sku, node_id`, 1-hour window |
| Late-order rate | `order.shipped` vs `fulfillment.assigned.estimated_ship_date` | count where actual > estimate, 1-hour window |
| Product demand by time window | `order.created` items | qty summed by `sku, node_hint`, 15-min tumbling window (feeds forecasting) |
| Dead-letter volume | `deadletter.event` | count by `event_type, failed_consumer`, 1-hour window |
| Consumer processing lag | Kafka consumer-group offsets (via Spark's Kafka source metrics / a small lag-poller sidecar) | max(latest_offset − committed_offset) by topic/consumer group |

## Watermarks and late data

Each streaming aggregation declares a watermark on `occurred_at`
(`withWatermark("occurred_at", "10 minutes")` by default, tuned per dataset —
e.g. fulfillment-latency needs a longer watermark since ship time can lag
order time by design). Events arriving after the watermark has passed for
their window are written to a `late_events` side path with the same schema as
their Silver table plus a `dropped_reason: "late"` flag, so late data is
visible and auditable rather than invisibly discarded — a documented,
measurable limitation, not a silent one.

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

To backfill a dataset (e.g. after fixing a bug in the revenue aggregation):
1. Stop the affected Gold streaming query.
2. Re-run it in **batch** mode reading the full Silver history for the
   affected date range (`spark-submit ... --conf spark.sql.shuffle.partitions=...
   --mode batch --from-date --to-date`), writing to a side path.
3. Validate the backfilled output against the data-quality reconciliation
   check.
4. Atomically swap (rename) the validated output into the live Gold path.
5. Restart the streaming query from a fresh checkpoint pointing past the
   backfilled range.

## Reprocessing process

To reprocess from Bronze (e.g. a Silver validation bug dropped rows that
should have passed): re-run the Silver job in batch mode over the affected
Bronze partitions with the fix applied, writing to a side path, validate row
counts against Bronze for that range, then swap and restart streaming — same
shape as backfill, one layer earlier. Because Bronze is immutable and
partitioned by date, reprocessing is always bounded to "replay this date
range," never "replay everything."

## Schema evolution strategy

Bronze stores the envelope loosely-typed (payload as JSON string/variant) so a
new event field never breaks Bronze ingestion. Silver's per-event-type schema
is versioned alongside `docs/event-catalog.md`'s `schema_version`; a new
minor/patch version is handled by a nullable-column-additive Silver schema
change (old and new both parse); a major version bump (new topic name) gets
its own Silver table until the migration window closes, then a one-time merge.

## Consumer lag and pipeline metrics

Kafka consumer-group lag (per topic/partition) is scraped and exposed as a
Prometheus metric (`docs/reliability.md`), and also lands in the "Consumer
processing lag" Gold dataset above so it is visible both operationally
(Grafana, real-time) and historically (dashboard pipeline-health screen,
queryable trend).
