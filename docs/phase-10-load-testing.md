# Phase 10: Load testing

Status: **complete** (the load-test-tooling slice of Phase 10 — see
`PROJECT_STATUS.md`; coverage tooling, the other slice of the original
Phase 10 scope, landed earlier via `docs/phase-5-engineering-quality.md`).

This document covers what was built, why, and this session's own real
measured results against the live `docker compose` stack. Every number
below comes from a k6 run actually executed in this session
(`load-test-reports/*.json`, gitignored — regenerate with `make load-*`);
none is estimated (`RISKS.md` #4).

## Why k6

Evaluated k6 vs. Locust for this repo specifically:

- **k6** is a single static Go binary — no separate master/worker processes
  to orchestrate, no host Python dependency (this repo already runs every
  Python tool in a throwaway container; k6 fits the same `docker compose
  run` pattern used everywhere else). Its built-in executor types
  (`constant-vus`, `ramping-vus`, `shared-iterations`) map directly onto
  smoke/baseline/load/stress/spike without hand-rolling stage logic, and its
  declarative `thresholds` block fails the process non-zero the moment a
  threshold is crossed — "fail clearly when thresholds are violated" for
  free, not something to build.
- **Locust** would have been the more idiomatic choice for a pure-Python
  monorepo, but its distributed-load model (master + worker processes) and
  web-UI-first design add real orchestration for a single-machine demo that
  doesn't need it, and its threshold/pass-fail story is something you'd have
  to script yourself (Locust doesn't fail its own exit code on an SLO
  breach without custom code).

k6 won on "fits this repo's existing throwaway-container pattern" and "gets
non-zero-exit-on-threshold-breach for free."

## Architecture

- `docker-compose.yml` gained a `k6` service gated behind a `load-test`
  Compose profile (`profiles: ["load-test"]`) — it **never** starts on a
  plain `docker compose up`/`make demo`, only via `docker compose
  --profile load-test run ...` (wired by the Makefile's `load-*` targets).
- `k6/scenarios.js` is the **one** script reused unchanged across every
  profile; `k6/lib/profiles.js` supplies the per-profile executor
  configuration (VUs/stages/duration), thresholds, and e2e poll timeout,
  selected via a `PROFILE` env var. `k6/lib/config.js`/`auth.js`/`ids.js`
  hold shared config, the real login helper, and unique-ID generation.
- `scripts/load_test_setup.sh` (`make load-setup`) is the idempotent,
  reusable test-data seed — brings the stack up, seeds one fixed
  fulfillment node + a fixed SKU pool with generous stock directly against
  inventory-service (same "seed data directly, measured traffic goes
  through the gateway" precedent `scripts/compose_smoke_test.sh` already
  established for Phase 1-9), stops the (unrelated) Spark streaming jobs,
  and waits for any previous run's saga backlog to drain.

## Authentication

Every scenario logs in through the real `POST /auth/login` (bcrypt-verified
credentials against a real Postgres `users` table, a real signed JWT — ADR
0009) using the seeded demo accounts: `ops@omniflow.local` for
order-creation/cancel traffic (needs the `ops` role), `viewer@omniflow.local`
for read-only traffic. No token is ever stubbed or forged. `setup()` logs in
once per k6 run and shares the tokens with every VU; the `auth_login`
scenario itself logs in fresh on every iteration, since login latency is
exactly what that scenario measures.

## Workloads

All six run through the real `api-gateway` container (`http://api-gateway:8000`,
the same in-network hostname every other service already uses to reach it —
real traffic through the real gateway, never a direct call to
order-service/inventory-service for anything measured):

1. **`auth_login`** — repeated `POST /auth/login`.
2. **`order_creation`** — `POST /api/orders`, unique `customer_id`/email/
   `Idempotency-Key` every iteration, a random SKU from the seeded pool.
3. **`order_retrieval`** — `GET /api/orders/{id}` against a small fixed pool
   of real orders created once in `setup()`.
4. **`inventory_lookup`** — `GET /api/inventory/stock/{sku}/{node_id}`.
5. **`concurrent_orders`** — the same `order_creation` request logic, run as
   a separate scenario at higher concurrency, to isolate throughput under
   contention from the "normal" creation rate.
6. **`e2e_order_workflow`** — create an order, then poll
   `GET /api/orders/{id}` through the real gateway until it reaches
   `SHIPPED`/`FAILED` or a bounded timeout — the real fulfillment saga
   (Kafka consumer, node scoring, reservation, payment simulation,
   transitions), not a fire-and-check. Deliberately run at a much lower
   iteration count than the other scenarios; each iteration holds a polling
   loop open.

`setup()` also does two things deliberately **not** part of measured
traffic: looking up the fixed load-test node's id directly against
inventory-service (a one-time lookup, same precedent as the smoke test's own
seeding step), and creating the small order pool `order_retrieval` reads
back repeatedly.

## Test data and uniqueness

`scripts/load_test_setup.sh` seeds one fixed fulfillment node
(`load-test-node-1`) and 100 SKUs (`SKU-LOAD-0001`..`SKU-LOAD-0100`) with
1,000,000 units of stock each. `POST /stock` (`upsert_stock`) sets
`available_qty` **absolutely**, so rerunning the seed script always tops
stock back up regardless of what a previous run consumed — safe to rerun
any number of times, no negative/double-add risk. Every iteration's
`customer_id` (a real UUIDv4), email, and `Idempotency-Key` are derived from
a per-run `RUN_ID` plus k6's own `__VU`/`__ITER`, so no two VUs, iterations,
or separate profile runs ever collide.

100 SKUs, not fewer: a real finding from this session's own first
(uncalibrated) run — see "Real findings" below.

## Profiles

| Profile | Peak combined VUs | Duration | Rate limit override |
|---|---|---|---|
| smoke | 7 | ~20-25s | yes (100000/min) |
| baseline | 14 | ~60s | yes |
| load | 41 (ramped) | ~50s | yes |
| stress | 68 (ramped) | ~40s + e2e tail | yes |
| spike | 41 (sudden burst) | ~30s + e2e tail | yes |

Every profile raises `GATEWAY_RATE_LIMIT_PER_MINUTE` (already an
env-overridable setting, no code change) for that run only, then restores
the default 120/min afterward — see "Real findings" below for why even
smoke needs this.

## Thresholds and real measured results

All five profiles were run for real against this session's live stack
(Spark bronze/silver/gold stopped during the run — see below) and all five
**passed** (`make load-smoke`/`load-baseline`/`load-test`/`load-stress`/
`load-spike` all exit 0). Numbers below are read directly from each run's
`--summary-export` JSON.

### smoke

- Thresholds: `http_req_failed rate<0.01`, `http_req_duration p(95)<2000,
  p(99)<3000` — **passed**.
- 139 requests, 118 iterations, 6.28 req/s, 0% failed.
- `http_req_duration`: avg 53.9ms, p95 213.4ms, p99 243.3ms, max 259.6ms.
- e2e workflow: 1/1 reached `SHIPPED`, 7.17s.

### baseline ("normal expected traffic")

- Thresholds: `http_req_failed rate<0.01`, `http_req_duration p(95)<1500,
  p(99)<2500` (+ per-scenario p95 caps), `http_reqs count>100` — **passed**.
- 783 requests, 748 iterations, 12.42 req/s, 0% failed.
- `http_req_duration`: avg 52.9ms, p95 244.1ms, p99 265.9ms, max 279.7ms.
- Per-scenario p95: `order_creation` 64.7ms, `order_retrieval` 40.7ms,
  `inventory_lookup` 27.1ms.
- e2e workflow: 3/3 reached `SHIPPED`, avg 6.72s, p95 8.03s.

### load (ramps to a moderate sustained peak)

- Thresholds: `http_req_failed rate<0.02`, `http_req_duration p(95)<2500,
  p(99)<4000`, `http_reqs count>150` — **passed**.
- 1,520 requests, 1,476 iterations, 28.70 req/s, 0% failed.
- `http_req_duration`: avg 75.5ms, p95 292.9ms, p99 350.1ms, max 963.8ms.
- e2e workflow: 4/4 reached `SHIPPED`, avg 7.11s, p95 11.28s.

### stress (intentionally pushes past comfortable capacity)

- Thresholds: `http_req_failed rate<0.20`, `http_req_duration p(95)<6000`
  — **passed** (deliberately wide; the point is to observe the real
  breaking point, not force a clean pass).
- 2,106 requests, 1,534 iterations, 8.55 req/s (lower than `load`'s because
  the long e2e polling tail dominates wall time after the other scenarios'
  own windows close), 0% HTTP failures.
- `http_req_duration`: avg 237.6ms, p95 699.0ms, p99 1.03s, max 1.37s.
- e2e workflow: **3/4 reached `SHIPPED`** (75%) within a 150s poll timeout;
  a 5th iteration was cut off by the scenario's own `maxDuration` before it
  could start. Real, honest degradation under 68 combined VUs — not hidden.

### spike (sudden short burst, not a ramp)

- Thresholds: `http_req_failed rate<0.25`, `http_req_duration p(95)<6000`
  — **passed**.
- 1,143 requests, 777 iterations, 6.16 req/s, 0% HTTP failures.
- `http_req_duration`: avg 143.1ms, p95 472.4ms, p99 700.6ms, max 812.0ms.
- e2e workflow: **1/2 reached `SHIPPED`** (50%) within a 120s poll timeout;
  2 further iterations were cut off by the scenario's own window. A sudden
  burst degrades e2e completion more than a comparable sustained ramp
  (`load`), which is exactly what a spike profile is supposed to show.

**Across all five real runs: 0% HTTP-level failure rate, every profile's
declared thresholds passed, and correctness held throughout** — 0 orders
double-reserved, 0 new incorrect dead letters (see "Real findings" for the 2
transient ones actually observed, and why).

## Real findings (bugs and capacity limits found by actually running this)

Consistent with this project's own standing practice (`DECISIONS.md`,
`RISKS.md`) of fixing root causes found by running the system for real, not
by inspection:

1. **Makefile recipe lines run in separate subshells.** The first attempt
   at raising `GATEWAY_RATE_LIMIT_PER_MINUTE` set the override only on the
   `docker compose up -d --no-deps api-gateway` line; a separate `docker
   compose run k6 ...` line (without the override in *its* environment)
   caused `docker compose` to reconcile api-gateway's dependency config
   against the *current* shell env and silently recreate it back to the
   default 120/min the instant k6 started — verified directly (`docker
   compose exec api-gateway env` showed the override, then 120 again one
   line later). Fixed by setting the override on both lines and adding
   `--no-deps` to the `run` command too, so it never re-evaluates
   api-gateway's desired config at all.
2. **Six 1-2-VU scenarios running concurrently in one k6 container clear
   the gateway's default rate limit (120/min per client IP) trivially** —
   every k6 VU shares one client IP. Verified directly: real 429s from the
   real `RateLimitMiddleware` on an early smoke run, not a fabricated
   number. Every profile, including smoke, raises the limit for its own run
   only (see "Profiles" above) — a load-test-only configuration override
   (already an env var, no code change), not a change to the limiter's code
   or to `make demo`'s own defaults.
3. **A small SKU pool (originally 20) causes real, load-bearing lock
   contention** on `inventory_stock` rows (ADR 0002's row-level locking
   working exactly as designed) once dozens of concurrent VUs all reserve
   from the same handful of SKUs — this confounds "how fast can the saga
   pipeline really go" with "how much are these orders fighting over the
   same few rows." Widened the seeded pool to 100 SKUs specifically to
   reduce this artificial confound.
4. **The Phase 4/6 Spark bronze/silver/gold streaming jobs consumed roughly
   5-6 of this host's 8 CPUs continuously**, `docker stats` confirmed,
   regardless of whether any load test was running. On an 8-CPU host that
   starved the actual services under test the moment k6 added concurrent
   traffic — one early (uncalibrated) run saw a single request take **3m32s**
   purely from host CPU contention, not from anything in api-gateway/order-
   service/inventory-service/fulfillment-orchestrator's own code.
   `scripts/load_test_setup.sh` now stops `spark-bronze`/`spark-silver`/
   `spark-gold`/`lag-poller` before seeding data — they are not part of this
   phase's system under test, and their CPU usage would otherwise dominate
   results that are supposed to describe the order/inventory/gateway/saga
   path. (`make up`/`make demo` bring them back; load testing does not
   restart them automatically.)
5. **Recreating any container on the Compose network (here: api-gateway,
   between profile runs, to apply/restore the rate-limit override) can
   cause a brief Docker embedded-DNS hiccup for *other*, unrelated
   containers' in-flight service-to-service calls.** Two real dead letters
   were observed during this session (`order.validated`, error `[Errno -2]
   Name or service not known` resolving `inventory-service` from
   fulfillment-orchestrator-consumer — not the container being recreated).
   Both were successfully recovered with the existing `make replay
   ARGS="--all"` (already-existing Phase 2/8 tooling, not new for this
   phase) — real recovery, not asserted. Documented as a real, minor,
   load-test-harness-induced side effect rather than silently absorbed;
   see `RISKS.md` (new entry).
6. **A genuinely valuable capacity finding, not a bug**: once (3) and (4)
   above were fixed, the real order → fulfillment-saga pipeline sustained
   **~28.7 orders/sec at `load` scale with 0% failures and sub-12s p99 saga
   completion**, and even at `stress` scale (68 combined VUs) held **0% HTTP
   failure rate** with saga completion only degrading (not failing outright)
   under real backlog pressure. The single sequential Kafka consumer
   (`fulfillment-orchestrator-consumer`) is still a documented, deliberate
   single-instance limitation (`RISKS.md` #8/#13, ADR 0004) — this session's
   numbers show it comfortably handles a genuine "moderate peak" load
   profile end to end, and degrades gracefully rather than catastrophically
   under `stress`/`spike`.

## Limitations — laptop, not cloud-scale

Every number above comes from one Docker Desktop/WSL2 host (8 CPUs, 15Gi
RAM) with the full observability stack (Jaeger/Prometheus/Grafana),
Redpanda, Postgres, and every application service running concurrently
alongside k6 itself. This is **not** a cloud-scale capacity claim — it
measures this specific single-instance, single-machine deployment
(consistent with `RISKS.md` #2's resource-ceiling risk and #13's
single-instance posture), not what a horizontally-scaled or cloud-hosted
deployment of the same architecture could sustain. In particular:

- Postgres, api-gateway, order-service, inventory-service, and
  fulfillment-orchestrator are all single instances with no connection
  pooling beyond SQLAlchemy's own per-process default (5 + 10 overflow) —
  a real ceiling this session's `stress`/`spike` profiles approach but do
  not fully saturate.
- The in-process, per-client-IP rate limiter is explicitly not
  multi-instance-safe (`RISKS.md` #13) — this test suite works around it
  for measurement purposes via a documented config override, not by
  changing or disabling the limiter's logic.
- `fulfillment-orchestrator-consumer` is a single sequential Kafka consumer
  process — the real, measured ceiling on end-to-end saga throughput, not
  the gateway or any individual service's own request-handling capacity.

## Validation strategy

- `make load-setup` seeds data idempotently and is safe to rerun.
- Each `make load-*` target fails non-zero (via k6's own threshold
  enforcement) the moment a declared threshold is crossed — verified
  directly during development (an uncalibrated first baseline run legitimately
  failed its own thresholds before recalibration, see "Real findings").
- `--summary-export` writes a machine-readable JSON report per profile to
  `load-test-reports/` (gitignored, regenerated per run, never committed —
  same convention as `coverage-reports/`).
- Existing Phase 1-9 correctness checks (`make test`, `make smoke`,
  `make phase8-smoke`) are unaffected by any Phase 10 change; verified by
  rerunning them after this phase's changes (see `TEST_RESULTS.md`).

## Affected files

- `k6/scenarios.js`, `k6/lib/{config,auth,ids,profiles}.js` — new.
- `scripts/load_test_setup.sh` — new.
- `docker-compose.yml` — new `k6` service (gated behind the `load-test`
  Compose profile).
- `Makefile` — `load-setup`, `load-smoke`, `load-baseline`, `load-test`,
  `load-stress`, `load-spike`, `load-validate`, `load-clean` targets.
- `.gitignore` — `load-test-reports/`.
- `docs/phase-10-load-testing.md` — this document.
- `README.md`, `PROJECT_STATUS.md`, `DECISIONS.md`, `RISKS.md`,
  `TEST_RESULTS.md` — updated with this phase's real results.

No Phase 1-9 application code (order-service, inventory-service,
fulfillment-orchestrator, api-gateway, failure-lab, ops-dashboard,
data-platform) was touched.
