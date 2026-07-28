# Phase 8: Failure Laboratory

Ten deterministic failure scenarios, each triggerable through a real backend
API and exercised against the real running stack — no scenario is a UI-only
simulation. This phase replaces the Phase 7 "inert preview" screen
(`services/ops-dashboard/src/api/mock/failureLab.ts`, since deleted) with a
working control panel backed by a new service, `services/failure-lab`.

## Why a new service, not new endpoints on existing services

Each scenario needs to orchestrate several existing services (create an
order through the gateway, poll the orchestrator's saga state, toggle
inventory-service's fault injection, publish raw Kafka records) and persist
its own run history. None of that belongs inside order-service,
inventory-service, or fulfillment-orchestrator's own domain models — it is
a client of all of them, the same way the ops dashboard is, except it drives
them rather than just reading from them. A dedicated service keeps this
orchestration logic in one place, gives it its own Postgres database
(`omniflow_failure_lab`) for run history, and lets it be torn down or
redeployed independently of the services it exercises.

## Architecture

```
services/failure-lab/
  app/
    main.py, routes.py       FastAPI app: catalog, trigger, runs, reset
    runner.py                Background-thread execution + persistence
    clients.py                Thin REST clients: Gateway/Order/Inventory/Orchestrator
    kafka.py, kafka_topics.py  Direct Kafka publish helpers + the one owned topic
    models.py                 ScenarioRun, ScenarioReset, FailureLabDeadLetter
    scenarios/
      base.py                 ScenarioContext, ScenarioOutcome, ScenarioEntry, poll_until
      registry.py             The 10 scenarios, in catalog order
      inventory_seed.py       Shared "ensure this marker SKU has stock" helper
      payment_decline.py, payment_timeout.py, inventory_oversell_race.py,
      duplicate_order_submit.py, duplicate_event_delivery.py,
      poison_message_dlq.py, malformed_kafka_record.py, late_event_arrival.py,
      saga_crash_resume.py, downstream_outage.py
    poison_consumer.py        Standalone worker for poison-message-dlq
  migrations/                 Alembic, one initial revision
```

Two new background workers run alongside the FastAPI app (docker-compose
services `failure-lab` and `failure-lab-poison-consumer`), following the
same one-process-per-role pattern every other service in this repo uses
(API process, consumer process, outbox relay all separate).

### Execution flow

1. `POST /scenarios/{id}/trigger` creates a `scenario_runs` row
   (`status=RUNNING`) synchronously and returns it immediately (`202`), then
   hands the actual scenario execution to a background thread
   (`app.runner._execute`). Scenarios that poll for an async effect (saga
   completion, a dead-letter appearing) do so with a bounded timeout
   (`FAILURE_LAB_POLL_TIMEOUT_SECONDS`, default 30s) — never open-ended, so
   a broken scenario reports `ERROR` instead of hanging the thread forever.
2. The dashboard (or `scripts/phase8_smoke_test.sh`, or `curl`) polls
   `GET /scenarios/{id}/runs/{run_id}` until `status` leaves `RUNNING`.
3. `POST /scenarios/{id}/reset` runs synchronously (every scenario's reset
   is a fast, local, idempotent cleanup — re-seed a stock row, force-disable
   a fault flag, clear failure-lab's own dead-letter table) and is recorded
   in `scenario_resets` so the catalog can show "last reset".

### Run status vocabulary

| Status | Meaning |
|---|---|
| `RUNNING` | In progress (transient) |
| `PASSED` | Completed; every assertion held (the general success outcome) |
| `RECOVERED` | Completed; used instead of `PASSED` for the 3 scenarios whose whole point *is* demonstrating recovery from an injected failure (payment-timeout, saga-crash-resume, downstream-outage) |
| `FAILED` | Completed, but an assertion did not hold — a real regression signal |
| `ERROR` | An infrastructure problem (timeout, unreachable service) prevented the scenario from completing — distinct from `FAILED`, which means the scenario ran but the system didn't behave as expected |

### Isolation of chaos topics

Two scenarios (`poison-message-dlq`, `malformed-kafka-record`) publish
deliberately broken or unconditionally-failing content onto Kafka. Neither
ever touches a topic a real transactional consumer subscribes to:

- `poison-message-dlq` uses `failure-lab.poison`, a topic owned entirely by
  the failure lab (`app/kafka_topics.py`) and created alongside the real
  11-topic event catalog in `infra/docker/redpanda/create-topics.sh`, but
  not part of it. Only `app.poison_consumer` (this phase's own worker)
  subscribes to it.
- `malformed-kafka-record` publishes raw, non-JSON bytes onto the real
  `inventory.low` topic — chosen because grepping every service confirmed
  zero transactional consumers subscribe to it (only order-service's
  validator consumes `order.created`; only fulfillment-orchestrator's saga
  consumer consumes `order.validated`/`order.cancelled`). Only Bronze's
  malformed-JSON quarantine (`docs/phase-6-streaming-data-platform.md`) ever
  has to deal with it — if the data platform isn't running, the scenario
  still passes (the deterministic part is the publish itself; Bronze
  quarantine verification is a best-effort diagnostic, see below).
- `late-event-arrival` publishes a well-formed `order.shipped` envelope
  (zero transactional consumers either) with a synthetic order_id and
  `occurred_at` far in the past — the same safe pattern the Phase 4
  synthetic generator already uses against these topics (RISKS.md #17).

### Determinism and timing

Every scenario's *outcome* is deterministic — the same inputs always
produce the same pass/fail verdict. The *wait* for an async effect (a saga
reaching a terminal state, a Kafka consumer processing a message) is real
wall-clock time, bounded by `poll_until` (`app/scenarios/base.py`): it polls
on a fixed interval up to a timeout, then raises `PollTimeoutError` — never
a random sleep, never an unbounded wait. Two scenarios (`malformed-kafka-
record`, `late-event-arrival`) additionally expose a best-effort MinIO-based
diagnostic (`make inspect-bronze-rejects` / `make inspect-late-events`) that
depends on the data platform being up; that check is never the pass/fail
gate, since a lighter-weight `docker compose up` subset (core services only)
must still let the deterministic part of the scenario pass.

### Why not actually stop the container (downstream-outage)

The mock catalog's original description said "Stop inventory-service while
orders are mid-saga." Actually issuing `docker compose stop inventory-
service` from a triggerable dashboard button would affect every other
concurrent user of a shared dev environment and is a hard-to-reverse action
outside this phase's own blast radius. Instead, inventory-service gained an
in-process simulated-outage flag (`app/outage.py` + `SimulatedOutageMiddleware`
in `app/middleware.py`): while active, every route except `/internal/
failure-lab/` and `/metrics` returns 503, including `/healthz` (so the API
Gateway's real `/readyz`, which live-pings both services, genuinely reports
`not_ready` — not a mocked response). It self-clears after a bounded
duration (`duration_seconds`, capped at 300s) even if nobody calls disable.

## The 10 scenarios

| # | id | Category | Mechanism |
|---|---|---|---|
| 1 | `payment-decline` | Saga compensation | `docs/architecture.md` — Saga compensation (failure path) |
| 2 | `payment-timeout` | Retry + backoff | `docs/event-catalog.md` — Retry policy (consumers) |
| 3 | `inventory-oversell-race` | Concurrency control | ADR 0002 — Inventory concurrency control |
| 4 | `duplicate-order-submit` | Idempotency | `docs/data-model.md` — idempotency_keys |
| 5 | `duplicate-event-delivery` | Idempotency | `docs/event-catalog.md` — Consumer idempotency |
| 6 | `poison-message-dlq` | Dead-letter queue | `docs/event-catalog.md` — Retry policy; DLQ screen |
| 7 | `malformed-kafka-record` | Data quality | `docs/data-pipeline.md` — Bronze, malformed-event handling |
| 8 | `late-event-arrival` | Data quality | `docs/data-pipeline.md` — Watermarks and late data |
| 9 | `saga-crash-resume` | Saga resumability | RISKS.md #11 — Saga resume gap |
| 10 | `downstream-outage` | Resilience | `docs/architecture.md` — Service boundaries |

This is the exact catalog `services/ops-dashboard/src/api/mock/failureLab.ts`
already documented as the Phase 8 plan (grounded in mechanisms this repo had
already built) — Phase 8 makes it real rather than inventing a different
list.

### 1. `payment-decline` — Payment hard decline

Places a real order (through the gateway) containing the payment
simulator's decline marker SKU (`SKU-PAYMENT-DECLINE` —
`services/fulfillment-orchestrator/app/payment.py`, deliberately built for
"the Phase 8 failure lab" per its own docstring). **Expected failure**:
`AUTHORIZE_PAYMENT` raises a non-retryable `PaymentDeclinedError`; the saga
skips retry and moves straight to `COMPENSATE_RELEASE_INVENTORY`.
**Expected recovery**: compensation releases the reservation and
transitions the order to `FAILED` — that *is* the correct outcome, not
something to retry past. PASS requires the saga context to show a real
`reservation_ids` entry (proving compensation actually ran), not just any
FAILED order.

### 2. `payment-timeout` — Payment gateway timeout

Same shape, using `SKU-PAYMENT-TIMEOUT-RECOVER` (fails attempt 1,
succeeds from attempt 2 — deterministic, no randomness).
**Expected failure**: first attempt raises a retryable
`PaymentGatewayTimeoutError`. **Expected recovery**: `app.retry.
retry_with_backoff` retries with exponential backoff + jitter; attempt 2
succeeds and the order reaches `SHIPPED`. Terminal status is `RECOVERED`.

### 3. `inventory-oversell-race` — Concurrent reservation race

Seeds a dedicated fulfillment node + SKU to exactly 1 available unit, then
fires 8 concurrent `POST /reservations` directly at inventory-service (not
through the saga — this exercises the row lock itself).
**Expected failure**: naively, more than one request could see stock and
succeed. **Expected recovery**: nothing to recover — `SELECT ... FOR
UPDATE` (ADR 0002) serializes the race so exactly one request wins, the
rest get 409. PASS requires `reserved_count == 1` and final
`available_qty == 0`.

### 4. `duplicate-order-submit` — Duplicate order submission

Submits the identical `Idempotency-Key` + payload to `POST /api/orders`
three times, then the same key with a different payload once.
**Expected failure**: without dedup, a retried/duplicated client request
would create a second order. **Expected recovery**: `idempotency_keys`
(docs/data-model.md) returns the identical cached response for repeats
(one order, not three) and correctly 409s the payload-mismatch case.

### 5. `duplicate-event-delivery` — Duplicate event redelivery

Publishes a synthetic `order.created` envelope directly to Kafka (a
made-up order_id with no real order-service row — the same safe pattern
the Phase 4 generator already uses, RISKS.md #17), then republishes the
identical envelope (same `event_id`) twice more.
**Expected failure**: without dedup, redelivery would reprocess the event.
**Expected recovery**: order-service's `processed_events` ledger makes
every redelivery a no-op — verified via a new internal read endpoint
(`GET /internal/failure-lab/processed-events/{event_id}` on order-service),
not inferred: `processed_at` must be identical before and after the 2
redeliveries.

### 6. `poison-message-dlq` — Poison message / retry exhaustion

Publishes onto `failure-lab.poison` (owned by this phase, see "Isolation of
chaos topics"). The dedicated `app.poison_consumer` worker reuses the exact
same `event_contracts.run_consume_loop` every production consumer uses, but
its `process()` deliberately raises unconditionally.
**Expected failure**: every attempt raises; the shared consume loop retries
with backoff to exhaustion (tuned to 3 attempts / short delays for this
worker specifically — the *mechanism* under test, not its production
timing). **Expected recovery**: deliberately *not* automatic replay — a
true poison message fails identically no matter how many times it's
reprocessed. The correct remediation is operator triage from the DLQ row
(a dedicated `failure_lab_dead_letters` table, distinct from fulfillment-
orchestrator's — see below). Contrast with `downstream-outage`, where
replay *does* recover the message.

### 7. `malformed-kafka-record` — Malformed Kafka record

Publishes deliberately non-JSON bytes onto `inventory.low` (see "Isolation
of chaos topics"). **Expected failure**: a naive Bronze sink would crash
or silently drop it. **Expected recovery**: Bronze's malformed-JSON
quarantine (`bronze_rejects`, `docs/phase-6-streaming-data-platform.md`)
routes it there instead. PASS is the publish succeeding; Bronze
verification is a best-effort diagnostic (`make inspect-bronze-rejects`).

### 8. `late-event-arrival` — Late-arriving event

Publishes a well-formed `order.shipped` envelope with `occurred_at` 45
minutes in the past (Silver's `LATE_THRESHOLD_SECONDS` is 600 = 10
minutes). **Expected failure**: a late event folded into an already-closed
aggregation window would silently skew it. **Expected recovery**: Silver's
lateness check routes it to `late_events` instead. Same best-effort
verification note as above (`make inspect-late-events`).

### 9. `saga-crash-resume` — Orchestrator crash mid-saga

Places a real order containing `SKU-SAGA-CRASH-SIMULATION`
(`services/fulfillment-orchestrator/app/saga.py`). The *real*, automatic
order.validated consumer picks it up and runs the saga normally, but
`advance_saga` pauses itself immediately after `SELECT_AND_RESERVE` commits
(reservation already made) — deliberately data-driven (keyed off the
marker SKU already in the order, not off timing of an admin call racing
the live consumer), leaving the exact on-disk state a real crash between
those two steps would. **Expected failure**: the saga simply stops
advancing — no error, no DLQ entry (this is the documented, narrower gap
in RISKS.md #11). **Expected recovery**: a new
`POST /internal/failure-lab/saga-crash-resume/{order_id}/resume` endpoint
calls the identical `advance_saga` function `resume_incomplete_sagas` calls
for every RUNNING row at real process startup — same recovery code path,
deterministic, no Docker control needed. Terminal status `RECOVERED`.

### 10. `downstream-outage` — Downstream service outage

See "Why not actually stop the container" above. Enables inventory-
service's simulated outage, places a real order, confirms the gateway's
real `/readyz` reports 503, waits for the resulting `order.validated`
event to exhaust Kafka-level retries and dead-letter into fulfillment-
orchestrator's real `dead_letter_events` table (the same table the
dashboard's Dead Letter Queue screen reads from), disables the outage, then
replays the dead letter via a new `POST /dead-letters/{id}/replay` endpoint
(the same operation `app.replay`'s CLI performs, `make replay`, now also
reachable over HTTP — this also closes a documented Phase 7 gap: "DLQ
replay is shown as a CLI command, not a working button"). **Expected
failure**: gateway degradation + dead-letter, both genuinely observed, not
mocked. **Expected recovery**: unlike poison-message-dlq, this failure
*is* transient — replay after the outage clears drives the order to
`SHIPPED`. Terminal status `RECOVERED`.

## Backend endpoints added

**New service, `services/failure-lab`** (published on `:8004`, proxied by
the dashboard at `/failure-lab-api/`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/scenarios` | Catalog + latest run + last reset + run count, all 10 |
| GET | `/scenarios/{id}` | Same, one scenario |
| POST | `/scenarios/{id}/trigger` | Starts a run in the background, `202` |
| GET | `/scenarios/{id}/runs` | Run history, most recent first |
| GET | `/scenarios/{id}/runs/{run_id}` | Poll target for one run |
| POST | `/scenarios/{id}/reset` | Scenario-specific cleanup |
| GET | `/healthz`, `/readyz`, `/metrics` | Standard |

**Small additions to existing services** (all internal/diagnostic, not
proxied to customers — same convention as order-service's existing
`/orders/{id}/transition`):

- order-service: `GET /internal/failure-lab/processed-events/{event_id}`
  (reads the `processed_events` idempotency ledger).
- inventory-service: `POST /internal/failure-lab/outage/enable`,
  `POST .../outage/disable`, `GET .../outage/status`
  (`app/outage.py` + `SimulatedOutageMiddleware`).
- fulfillment-orchestrator: `POST /internal/failure-lab/saga-crash-resume/
  {order_id}/resume`, `POST /dead-letters/{id}/replay` (the latter is
  generally useful beyond the failure lab — see scenario 10's writeup).
  `app/saga.py` gained `CRASH_SIMULATION_SKU` and the pause logic in
  `advance_saga`; this process is no longer purely read-only, so `app/
  main.py` now instruments httpx too (documented as a deliberate,
  version-controlled change — see DECISIONS.md).

## Real bugs found and fixed during this phase

Every prior phase's `docs/phase-N-*.md` documents real bugs found by
actually running the thing, not just writing it — this phase found four,
three of them in code that predates it:

1. **A malformed Kafka record crashed any consumer permanently, forever**
   (`event_contracts.kafka.run_consume_loop`): `parse_envelope(msg)` was
   called *outside* the retry/DLQ try/except that wraps `process()`, so a
   record that isn't valid-envelope-shaped JSON propagated unhandled,
   crashing the consumer process — and since the poisoned offset was never
   committed, every restart hit the identical message and crashed again,
   forever. Found for real: a message the Phase 6 synthetic generator's
   `--malformed-rate` (`docs/phase-6-streaming-data-platform.md`) had left
   sitting in a real topic from earlier phase validation crashed
   `order-validator-consumer` the first time this phase's own `make smoke`
   ran end to end. **Fixed**: parse failures are now logged, counted
   (`KAFKA_MALFORMED_RECORD_TOTAL`), and the offset committed immediately
   — never retried (retrying parsing again can never succeed) and never
   crashing. Regression test:
   `services/event-contracts/tests/test_consume_loop.py::
   test_unparseable_record_is_skipped_committed_and_counted_not_crashed`.

2. **`resume_incomplete_sagas` let one unresumable saga crash the whole
   orchestrator at every startup** (`app/saga.py`): called once at process
   startup, it had no exception handling around `advance_saga` — a single
   stale `RUNNING` saga referencing an order_id no longer in order-service
   (real, orphaned dev data from earlier synthetic-generator testing; 60
   such rows were found in this session's persistent Postgres volume) made
   the orchestrator-consumer crash before it ever started consuming Kafka,
   on every single restart. **Fixed**: each saga is now resumed
   independently inside a try/except; one that raises is marked `FAILED`
   with the error recorded, and every other saga still gets its chance.
   Regression tests: `services/fulfillment-orchestrator/tests/
   test_resume_incomplete_sagas.py`.

3. **A transient failure on a brand-new saga's first `advance_saga` call
   left it stuck forever, invisible to both retry and DLQ** (`app/saga.py`,
   `handle_order_validated`): the event was marked "processed" *before*
   `advance_saga` ran for the first time. If that call raised (a
   downstream 503, any bug), the event was already marked processed — so
   Kafka's own same-message redelivery became a silent no-op
   (`_already_processed` short-circuited before ever calling `advance_saga`
   again), leaving the saga stuck `RUNNING` with no dead-letter entry and
   no further retry, ever. Found running this phase's own
   `downstream-outage` scenario against a live stack for the first time —
   a scenario deliberately designed to exercise exactly this path.
   **Fixed**: the event is now marked processed only after `advance_saga`
   returns without raising; a raise now correctly falls through to Kafka's
   retry, which re-enters the "existing saga" branch and resumes it.
   Regression test: `services/fulfillment-orchestrator/tests/
   test_saga_unexpected_failure_retry.py`.

4. **`app.replay.replay_one` had never worked against a real dead letter**
   (`app/replay.py`): it read `dead_letter.payload["original_event"]`, but
   `app.consumer.dead_letter()` actually stores the flat envelope directly
   (`payload=envelope.model_dump(...)`, no wrapper key) — a mismatch that
   made every real replay attempt raise `KeyError`, silently masked until
   now because the *existing* test for this (`test_dlq_and_replay.py`) and
   this phase's own new tests all independently constructed their own
   fixture with the wrong (wrapped) shape rather than reusing the real
   `dead_letter()` code path, so nothing had ever caught the mismatch.
   Found running `downstream-outage`'s replay step for the first time.
   **Fixed**: `replay_one` now reads `dead_letter.payload` directly; the
   pre-existing test's fixture and this phase's own were both corrected to
   the real shape (a false-positive test fixed alongside the code, not
   just the code). Verified for real: `make replay ARGS="--all"`
   successfully replayed 2 real dead letters left over from this session's
   own earlier (pre-fix) test runs.

All four are documented in `RISKS.md` with status `Closed`.

## Dashboard

`services/ops-dashboard/src/pages/FailureLabPage.tsx` (rewritten) + `src/
api/failureLab.ts` (new): fetches the real catalog (`GET /scenarios`,
polled every 3s), one card per scenario showing description, expected
failure/recovery behavior, mechanism reference, latest run status (via the
shared `StatusBadge`, extended with `PASSED`/`RECOVERED`/`ERROR`), run
count, last reset, and an expandable diagnostics/error panel. Trigger and
Reset buttons are disabled while a request is in flight or the scenario's
latest run is `RUNNING`. Loading/error/empty states use the existing
shared components (`LoadingState`/`ErrorState`/`EmptyState`) — no new
patterns invented. `src/api/mock/failureLab.ts` (the Phase 7 inert preview)
is deleted; there is no fake data left in this screen.

The Dead Letter Queue screen also gained a real "Replay" button
(`src/api/orchestrator.ts`'s `replayDeadLetter`, backed by the same `POST
/dead-letters/{id}/replay` endpoint scenario 10 needed) — closing the
Phase 7-documented "CLI-only" limitation for that screen as a direct
consequence of building this endpoint, not separate scope creep.

## Makefile targets

- `make test-failure-lab` — the new service's own unit/API test suite.
- `make phase8-smoke` — end-to-end: brings up the full stack, triggers all
  10 scenarios, asserts each reaches `PASSED`/`RECOVERED`, resets every
  scenario, reruns all 10 a second time (proves safe-to-rerun for the whole
  catalog, not just asserted in a docstring).
- `make phase8-validate` — `test-failure-lab` + `phase8-smoke` + the
  existing `ci` gate.
- `make clean-phase8` — disposable local caches only (pytest/mypy/ruff),
  never touches Postgres/Redpanda/MinIO data.
- `make replay` (existing) now actually works against a real dead letter
  (bug #4 above) — try it after triggering `downstream-outage`.

`test-failure-lab` is now part of `make test`/`make coverage`/`make ci`;
`services/failure-lab` is part of `make typecheck`, `make security`
(bandit + pip-audit), and `make docker-build`.

## Demo instructions

```
make up                              # or: docker compose up -d
open http://localhost:3001/failure-lab
# click Trigger on any scenario card, watch it move to RUNNING then a
# terminal status within a few seconds; click Reset to clean up and rerun
```

Or entirely from the command line:

```
curl -s -X POST http://localhost:8004/scenarios/payment-decline/trigger | python3 -m json.tool
curl -s http://localhost:8004/scenarios/payment-decline/runs/<run_id> | python3 -m json.tool
curl -s -X POST http://localhost:8004/scenarios/payment-decline/reset | python3 -m json.tool
```

## Testing

- **Backend**: 66 tests in `services/failure-lab/tests/` — unit tests for
  every scenario's `run()`/`reset()` against hand-written fakes (`tests/
  fakes.py`, same convention as fulfillment-orchestrator's own fakes),
  `respx`-mocked HTTP client tests, the registry (asserts exactly the 10
  documented scenarios), the runner (background execution, crash safety,
  run numbering, history ordering), the API routes, Kafka helper functions,
  and the poison consumer.
- **Existing suites extended**: order-service (+3), inventory-service (+5,
  the new outage middleware), fulfillment-orchestrator (+12: replay/resume
  routes, the crash-simulation marker, `resume_incomplete_sagas` hardening,
  the unexpected-failure-retry regression), event-contracts (+1, the
  malformed-record regression).
- **Frontend**: `src/api/failureLab.test.ts` (6 tests) + a rewritten `src/
  pages/FailureLabPage.test.tsx` (7 tests, real API mocked via `vi.spyOn`,
  not the deleted static fixture).
- **Integration**: `scripts/phase8_smoke_test.sh` / `make phase8-smoke` —
  the only test level that exercises all 10 scenarios against the real,
  live stack (Postgres, Redpanda, every real service) end to end, twice,
  proving determinism and safe-rerun for real rather than by assertion.

See `TEST_RESULTS.md` for exact pass counts from commands actually run.

## Cleanup / reset behavior

Every scenario implements `reset()` (requirement: safe to rerun,
repeatedly, during a demo):

| Scenario | Reset behavior |
|---|---|
| payment-decline, payment-timeout, duplicate-order-submit, duplicate-event-delivery, malformed-kafka-record, late-event-arrival, saga-crash-resume | No-op (each run creates fresh, independent state — a new order/event, never shared) |
| inventory-oversell-race | Re-seeds `available_qty=1` at the dedicated shared node |
| poison-message-dlq | Clears failure-lab's own `failure_lab_dead_letters` rows |
| downstream-outage | Force-disables the simulated outage (safety valve if a run was interrupted) |

None of the 10 scenarios ever drop, truncate, or otherwise destructively
modify a table it doesn't own — consistent with `CONTRIBUTING.md`'s
standing rule. `failure_lab_dead_letters` and `scenario_runs`/`scenario_resets`
(this service's own tables) are the only things any reset ever mutates
beyond the specific scenario's own re-seeded row.

## Troubleshooting

- **A scenario reports `ERROR` with "timed out waiting for..."**: the
  async effect it's polling for (saga completion, a dead letter appearing)
  never showed up within `FAILURE_LAB_POLL_TIMEOUT_SECONDS` (default 30s).
  Check `docker compose logs fulfillment-orchestrator-consumer` /
  `order-validator-consumer` for the underlying cause — most commonly a
  dependency container not yet healthy, or (see bugs #1-#3 above) a stale
  poisoned message/orphaned saga from very old dev data if you're running
  against a long-lived Postgres/Redpanda volume from many prior sessions.
- **`downstream-outage` seems stuck "outage active"**: it self-clears after
  `duration_seconds` (default 20s, capped at 300s) regardless; call its
  `reset()` (`POST /scenarios/downstream-outage/reset`) to force-disable
  immediately.
- **`malformed-kafka-record` / `late-event-arrival` "pass" but you don't
  see anything in `bronze_rejects`/`late_events`**: verification there is
  best-effort and requires the data platform (`spark-bronze`/`spark-
  silver`) to be running (`make streaming-up`); the scenario's own pass/
  fail never depends on it.
- **`make replay` or the dead-letter replay button 500s**: this was bug #4
  above — rebuild `fulfillment-orchestrator` if you see this on an image
  older than this phase.

## Known limitations

- **`get_or_create_node`'s create-then-list-again race** (`app/clients.py`):
  two scenarios racing to create the same shared fulfillment node for the
  first time could hit a 409 on the loser; handled (falls back to reading
  back what the winner created), but `scripts/phase8_smoke_test.sh` runs
  scenarios sequentially, so this path is unit-tested
  (`test_inventory_client_get_or_create_node_recovers_from_a_create_race`)
  but not exercised by the live smoke test.
- **`malformed-kafka-record`/`late-event-arrival`'s Bronze/Silver
  verification is best-effort**, not asserted — see "Determinism and
  timing" above.
- Same unauthenticated-dashboard posture as Phase 7 (RISKS.md #25):
  triggering any scenario requires no auth, same as every other dashboard
  action already documented as local-demo-only.
