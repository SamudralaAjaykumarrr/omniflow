# Decisions Log

Running log of decisions made during the build, newest first. Major
architectural decisions get a full ADR under `docs/adrs/`; this log also
captures smaller in-flight calls that don't warrant a standalone ADR, plus
pointers to the ADRs when they do.

## 2026-07-23 — Planning stage

- Chose Redpanda over Apache Kafka for the event platform. See
  [ADR 0001](docs/adrs/0001-redpanda-over-kafka.md).
- Chose row-level locking for inventory reservations + optimistic
  `version`-column concurrency for order state transitions (two different
  strategies for two different contention profiles, both required by the
  spec). See [ADR 0002](docs/adrs/0002-inventory-concurrency-control.md).
- Chose transactional outbox over CDC/Debezium for reliable event publish.
  See [ADR 0003](docs/adrs/0003-transactional-outbox.md).
- Chose a custom lightweight saga orchestrator over Temporal/Airflow. See
  [ADR 0004](docs/adrs/0004-custom-saga-orchestrator.md).
- Chose PySpark Structured Streaming in single-node `local[*]` mode for the
  local demo, cluster deployment described only in the (unapplied) Terraform/
  architecture docs. See [ADR 0005](docs/adrs/0005-spark-local-mode.md).
- Chose baseline-first forecasting (seasonal-naive/moving-average) with a
  lightweight scikit-learn/statsmodels secondary model, deferring Prophet/
  XGBoost to a documented future upgrade. See
  [ADR 0006](docs/adrs/0006-forecasting-scope.md).
- Chose to author and validate Terraform (`fmt`/`validate` in a container)
  and never apply it — no AWS credentials exist in this session and none
  will be requested. See [ADR 0007](docs/adrs/0007-terraform-not-applied.md).
- Finalized the monorepo layout (`/services`, `/data-platform`, `/frontend`,
  `/infra`, `/observability`, `/docs`, `/scripts`). See
  [ADR 0008](docs/adrs/0008-monorepo-layout.md).
- Chose self-contained JWT + RBAC auth (bcrypt password hashing) over a
  third-party IdP, to keep local evaluation free of paid services. See
  [ADR 0009](docs/adrs/0009-authn-authz.md).
- Verified host toolchain via direct inspection: Docker + Compose present;
  no host pip/node/java/terraform. Decision: all builds, tests, and lint runs
  go through Docker containers rather than assuming/installing a host
  toolchain, consistent with the "no paid services, one-command local demo"
  requirement.
- Decided to run the full 13-phase build additively, each phase leaving the
  system runnable via `docker compose up`, rather than attempting uniform
  "finished" depth across all 16 spec sections simultaneously — recorded as
  the primary scope-management decision for this project (see `RISKS.md`,
  "Scope vs. depth").
