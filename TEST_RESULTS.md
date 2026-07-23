# Test Results

Last updated: 2026-07-23 (Phase 1 complete).

This file is updated after every phase with real output from real commands;
no number here is ever estimated or invented (see `RISKS.md` #4).

## Format

Each phase appends a dated section with:
- The exact command(s) run (`pytest`, `docker compose run ...`, etc.)
- Pass/fail counts and coverage percentage, pasted from actual output
- Any known-excluded lines/files and why
- Load-test results (when applicable): p50/p95/p99 latency, throughput,
  error rate, from an actual local run, with the exact load profile used

## History

### 2026-07-23 — Phase 1: Core domain

Commands run (via `docker compose run --rm <service> pytest -q --cov=app
--cov-report=term-missing`, each against its own `*_test` Postgres database):

**order-service** — 21 passed, 0 failed, 96% coverage (337 stmts, 14 missed).
Missing lines are `app/db.py` (the `get_db` generator's teardown path, only
exercised under real ASGI request/response lifecycle, not the test session
fixture) and a couple of unreached branches in `app/routes.py` /
`app/service.py` for error paths not currently hit by a dedicated test.

**inventory-service** — 9 passed, 0 failed, 95% coverage (345 stmts, 17
missed). Includes the two concurrency tests described below. Missing lines
are the same `app/db.py` teardown path plus a couple of unreached error
branches in `app/routes.py`/`app/stock.py`.

**api-gateway** — 9 passed, 0 failed, 93% coverage (132 stmts, 9 missed).
Missing lines are mostly alternate proxy-route error branches not covered by
a dedicated test yet.

**Total: 39 passed, 0 failed** across the three service suites.

Concurrency tests (the core claim of ADR 0002), run against a real
Postgres, each attempt on its own DB connection/session:
- `test_concurrent_reservations_for_last_unit_exactly_one_succeeds`: 10
  concurrent threads race to reserve 1 unit of stock — exactly 1 succeeds, 9
  correctly rejected, final ledger `available_qty=0, reserved_qty=1`.
- `test_concurrent_reservations_exactly_consume_multi_unit_stock`: 10 threads
  race for 5 units — exactly 5 succeed, final ledger `available_qty=0,
  reserved_qty=5`.

End-to-end acceptance check (real `docker compose up`, all 4 containers
healthy, verified via `curl` against the running stack — not just unit
tests):
- Created an order through the API Gateway (`POST /api/orders`) — `201`,
  state `CREATED`.
- Resubmitted the identical request with the same `Idempotency-Key` — `201`
  with the *same* order `id`, proving idempotent replay.
- Cancelled the order (`CREATED -> CANCELLED`, valid transition) — `200`.
- Cancelled it again (`CANCELLED -> CANCELLED`, invalid transition) — `409`
  with `error_code: conflict`.

Lint/format: `ruff check .` — all checks passed. `ruff format --check .` —
50 files already formatted, 0 remaining.

**Bugs found and fixed during this test pass** (see `DECISIONS.md` for the
full writeup): a Docker entrypoint bug that silently ignored `docker compose
run`'s command override and started the API server instead of running
tests; a test-only thread-safety bug in the concurrency test harness (shared
ORM object accessed from multiple threads); a real header-duplication bug in
the gateway's proxy layer (`X-Correlation-ID` sent as two header lines,
joined into one comma-separated value on receipt); and two test-isolation
bugs in the gateway suite (a `setdefault` that a real compose-injected env
var silently defeated, and a shared in-process rate-limit counter leaking
state between test functions).
