# ADR 0004: Saga Orchestration — Custom Lightweight Orchestrator, not Temporal/Airflow

## Status
Accepted

## Context
Coordinating order validation, inventory reservation, node selection, and
simulated payment as a durable, compensable workflow is one of the things this
project exists to demonstrate. Off-the-shelf durable-execution engines
(Temporal, Airflow, AWS Step Functions) solve this well in production but each
adds a real operational dependency (Temporal: its own server + Postgres/
Cassandra + UI; Airflow: a scheduler + metadata DB + webserver, and is
batch/DAG-oriented rather than event-driven-saga-oriented).

## Decision
Build a small, explicit orchestrator: a Python service that consumes domain
events, persists saga progress in `saga_instances` (current step, status,
attempt count, next retry time, last error), and drives the next action
(reserve inventory → select node → authorize payment → confirm shipment) or
the compensating action on failure (release inventory → mark order failed).
On startup, the orchestrator reloads any `RUNNING`/`COMPENSATING` saga
instances from Postgres and resumes them — durability comes from the table,
not from an in-memory process that must never crash.

## Consequences
- The saga/compensation/retry mechanics that the spec asks to be demonstrated
  are visible in this project's own code, not delegated to a framework's
  internals — directly useful for the interview-guide walkthrough this
  project is partly built to support.
- No second database, scheduler, or UI to operate; one more Python service on
  the same Postgres/Redpanda already in the stack.
- This does not scale to hundreds of saga types or long-running (hours/days)
  workflows as gracefully as Temporal would — documented explicitly in
  `docs/reliability.md` and the interview guide as the honest tradeoff and the
  first thing that would change for genuine enterprise scale.

## Alternatives considered
- **Temporal**: the strongest production answer for durable workflows;
  rejected here only because it would hide the exact mechanics (retry,
  compensation, state persistence) this project is meant to demonstrate
  behind Temporal's own runtime, and because it's a second stateful system to
  operate locally. Named as the recommended real-world upgrade.
- **Airflow**: DAG/batch-scheduling model doesn't fit a per-order, event-
  triggered saga naturally; rejected.
- **Choreography (no central orchestrator, services react to each other's
  events directly)**: was considered — it's a legitimate saga style — but
  makes the "what step is this order on and what happens on failure" question
  implicit across multiple services instead of visible in one place, which
  works against the project's explainability goal. The orchestrator
  (choreography's sibling pattern) was chosen so saga state and compensation
  logic have one clear home.
