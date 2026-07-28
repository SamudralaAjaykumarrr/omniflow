# Contributing to OmniFlow

Guidance for anyone working in this repository — reviewing it, extending it,
or picking up where a phase left off.

## Read these first, in order

1. `PROJECT_STATUS.md` — current phase, what exists, what's next. Check
   this before assuming what has or hasn't been built.
2. `RISKS.md` — known risks and their mitigations/status. Don't re-litigate
   a risk already recorded here without checking its current status first.
3. `DECISIONS.md` and `docs/adrs/` — why things are built the way they are.
   Prefer reading the relevant ADR over re-deriving a design decision from
   scratch.
4. `docs/architecture.md`, `docs/event-catalog.md`, `docs/data-model.md`,
   `docs/data-pipeline.md` — the design itself.

## Environment

Docker + Docker Compose is the only host requirement — 8 CPUs / 15Gi RAM is
what this project has been built and verified against. No host Python,
Node, Java, or Terraform is needed or assumed: every build, test, and lint
command runs inside a container — see the relevant service's Dockerfile or
the root `docker-compose.yml` for the exact invocation. Don't assume a host
toolchain is available; a service's own container is always the source of
truth for how to build/test/lint it.

## Standing project rules

- **Never report fabricated command output, test counts, coverage, or
  performance numbers.** Every figure in `TEST_RESULTS.md`,
  `docs/project-evidence.md`, or `docs/career-deliverables.md` must be
  reproducible by actually running the command it's attributed to.
- **Never run `terraform apply` or use real AWS credentials against this
  repository's Terraform.** `infra/terraform/` is authored and validated
  (`fmt`/`validate` via the official Terraform Docker image) only — see
  ADR 0007.
- **Don't weaken a test to make a build pass.** Fix the root cause, or if
  truly out of scope, document why in `RISKS.md`.
- **At-least-once, not exactly-once.** Every consumer must be idempotent
  (dedupe by `event_id`); never claim exactly-once delivery anywhere in
  code or docs.
- **Two concurrency strategies are intentional, not inconsistent**:
  row-level locking for `inventory_stock` (hot rows), optimistic `version`
  column for `orders` (low contention). See ADR 0002 before "fixing" this.
- **Test schema fixtures must never call `Base.metadata.drop_all`.** Every
  service's `entrypoint.sh` runs `alembic upgrade head` unconditionally
  before handing off to any command, including `pytest` — so Alembic, not
  the test fixtures, owns schema. A fixture that drops tables after a test
  run leaves `alembic_version` claiming a migration is applied while the
  tables it created are gone, and the next migration added will fail
  trying to alter a table that doesn't exist (hit for real once, see
  `DECISIONS.md`/`RISKS.md` #12). Truncate for cleanup, never drop.
- Before closing out a change: format + lint, run the relevant tests, fix
  root causes of any failure, update docs, review the diff, and update
  `PROJECT_STATUS.md` (and `RISKS.md`/`DECISIONS.md`/`TEST_RESULTS.md` if
  anything changed there).

## Engineering conventions

- Python: type hints throughout, Pydantic for request/response and event
  payload validation, SQLAlchemy + Alembic for persistence/migrations.
- All timestamps UTC; all IDs UUIDv4 unless a table's own PK is naturally a
  string (e.g. `sku`, `idempotency_key`).
- Structured exceptions, not bare `Exception`; structured JSON logs with
  `correlation_id` on every log line inside a request/event handling path.
- Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, ...).
- No placeholder implementations, empty TODOs, or hard-coded secrets —
  secrets come from environment variables (`.env.example` documents the
  shape, never real values).
- Prefer the smallest abstraction that keeps a service testable; don't add
  a repository/service layer where a direct, well-tested function will do.

## Monorepo layout

See [ADR 0008](docs/adrs/0008-monorepo-layout.md) for the full layout and
the reasoning behind each service boundary.
