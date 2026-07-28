# OmniFlow — Product Requirements

## What this is

OmniFlow is a demonstration retail-technology platform: an omnichannel order,
inventory, and fulfillment system built to show production-caliber distributed
systems and data engineering practice. It is an original design. It is not a
clone of, and does not reuse any proprietary design, branding, or business
information from, any real retailer.

## Business scenario

A retailer with multiple fulfillment nodes (warehouses/stores acting as ship
points) takes orders through a single API. Each order contains one or more
line items. The system must get the order right exactly once, never oversell
a SKU, pick a sensible fulfillment node, and keep every downstream system
(inventory, analytics, forecasting, operations dashboard) consistent with what
actually happened — while tolerating the failures that are normal in a
distributed system (timeouts, duplicate deliveries, partial outages).

## Actors

- **Customer** — submits orders via the API (in the demo, via scripted load
  generator and the dashboard's order-stream view; there is no consumer storefront).
- **Ops user** — authenticated staff who monitor orders, inventory, pipeline
  health, and trigger failure-lab scenarios from the dashboard.
- **Payment simulator** — an internal stand-in for a payment authorization
  provider; deterministic and controllable for failure-lab scenarios. No real
  payment processor, PCI data, or card data is involved anywhere in this system.
- **Fulfillment nodes** — modeled as data (capacity, location, backlog), not as
  separate live systems.

## Functional requirements

1. Validate the customer and order payload before any state is created.
2. Reject duplicate order submissions using a client-supplied idempotency key —
   same key + same payload returns the original result; same key + different
   payload is a conflict.
3. Check available inventory across fulfillment nodes for every line item.
4. Reserve inventory safely under concurrent demand — two concurrent requests
   for the last unit of a SKU must not both succeed.
5. Select a fulfillment node using a documented, explainable scoring formula
   (stock, distance, capacity, delivery promise, backlog).
6. Coordinate order, inventory, simulated payment, and fulfillment as a durable
   saga: partial failure triggers compensation, not a stuck or corrupted order.
7. Publish a domain event for every state transition that matters to the rest
   of the system (see `docs/event-catalog.md`).
8. Process those events through a streaming pipeline into bronze/silver/gold
   datasets (see `docs/data-pipeline.md`).
9. Produce trusted, reconciled analytical datasets from the gold layer.
10. Detect stockout risk, delayed fulfillment, and anomalous event patterns
    from the data platform, not by polling the transactional database.
11. Forecast short-term per-SKU, per-location demand from historical sales,
    with an honestly-reported baseline comparison.
12. Present business and technical state in an operations dashboard aimed at
    the people who run the system, not at shoppers.

## Non-functional requirements

- **Correctness over throughput.** No overselling, no lost orders, no silently
  dropped events, even under simulated failure. This is the property the whole
  project exists to demonstrate.
- **At-least-once processing, explicitly.** Consumers are idempotent because
  delivery is not exactly-once. The system never claims exactly-once semantics
  it does not implement.
- **Local-first.** The entire system runs on a single developer machine with
  no paid cloud services, via one documented command.
- **Explainability.** Every non-trivial decision (node selection, concurrency
  strategy, saga design) is documented with its tradeoffs, not just implemented.
- **Bounded blast radius for the ML component.** Forecasting is a downstream,
  offline, non-blocking component. Its failure or absence does not affect order
  processing.

## Explicit non-goals

- No real payment processing, no PCI scope, no real carrier integration.
- No multi-region/multi-cluster HA story implemented (only documented as a
  scale-out discussion in `RISKS.md` #13 and `infra/terraform/README.md`).
- No mobile app, no consumer-facing storefront UI.
- No claim of exactly-once event delivery anywhere in the system.
- No production AWS deployment — Terraform is authored and validated, not applied.

## Success criteria

The project is successful when: `docker compose up` (or `make demo`) brings up
a working system on a clean machine; a scripted order flow completes end to
end with events visible in the data pipeline; at least the ten Failure
Laboratory scenarios are reproducible and produce documented, observable
outcomes; and every number quoted in `docs/project-evidence.md` or
`docs/career-deliverables.md` was produced by a command actually run against
this repository.
