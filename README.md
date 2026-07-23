# OmniFlow

**Event-Driven Retail Order, Inventory and Fulfillment Intelligence Platform.**

OmniFlow is an independently designed, portfolio-scale demonstration of
production-caliber distributed systems and data engineering practice: an
omnichannel order/inventory/fulfillment platform built around event-driven
architecture, safe concurrency, durable saga orchestration, a Kafka-protocol
event bus, a PySpark bronze/silver/gold data pipeline, demand forecasting, and
a full observability stack — running entirely on a single machine with no
paid cloud services.

This is an original design. It is not a clone of, and does not use any
proprietary design, branding, or business information from, any real
retailer.

## Status

This project is under active, staged construction. See `PROJECT_STATUS.md`
for exactly what exists right now and what's next, `RISKS.md` for known risks
and how they're managed, and `TEST_RESULTS.md` for real (never fabricated)
test/coverage/load numbers as they land.

## Why this exists

To demonstrate, with working code and honest measurements rather than claims,
the engineering judgment expected from strong Software Development Engineer
and Data Engineer candidates: idempotent APIs, safe concurrent inventory
reservation, saga-based workflow coordination with compensation, event
contracts with versioning and replay, streaming data quality, and
observability — each with its tradeoffs documented, not just its happy path.

## Architecture at a glance

See `docs/architecture.md` for full container/sequence/data-flow diagrams.
Short version: an API Gateway fronts an Order Service and Inventory Service
(Postgres-backed, row-level-locked and optimistically-versioned respectively —
[ADR 0002](docs/adrs/0002-inventory-concurrency-control.md)); a Fulfillment
Orchestrator runs the order saga over a Redpanda event bus
([ADR 0001](docs/adrs/0001-redpanda-over-kafka.md),
[ADR 0004](docs/adrs/0004-custom-saga-orchestrator.md)); a PySpark Structured
Streaming pipeline turns those events into bronze/silver/gold datasets in
MinIO ([ADR 0005](docs/adrs/0005-spark-local-mode.md)); a React/TypeScript
ops dashboard and a Prometheus/Grafana/Jaeger stack make all of it observable.

## Documentation map

| Doc | Contents |
|---|---|
| `docs/product-requirements.md` | Business scenario, functional/non-functional requirements, non-goals |
| `docs/architecture.md` | Container diagram, all sequence/flow diagrams |
| `docs/system-context.md` | External actors and systems |
| `docs/event-catalog.md` | All event contracts, envelope, versioning, retry/DLQ/replay |
| `docs/data-model.md` | ER diagram and table definitions |
| `docs/data-pipeline.md` | Bronze/silver/gold design, watermarks, checkpointing, backfill |
| `docs/adrs/` | Architecture Decision Records |
| `docs/reliability.md`, `docs/security.md`, `docs/testing-strategy.md` | Land in later phases — see `PROJECT_STATUS.md` |
| `docs/demo-script.md`, `docs/interview-guide.md`, `docs/resume-evidence.md` | Career-facing deliverables — land in Phase 13 |

## Running it locally

Not yet available — no Dockerfiles or compose stack exist until Phase 1
lands. This section will be replaced with the real `docker compose up` /
`make demo` instructions the moment they're true; see `PROJECT_STATUS.md`
for current phase.

## License

See `LICENSE` (added alongside the rest of the repository documentation set
in Phase 13).
