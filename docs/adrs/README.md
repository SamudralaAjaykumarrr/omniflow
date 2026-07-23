# Architecture Decision Records

| ADR | Decision |
|---|---|
| [0001](0001-redpanda-over-kafka.md) | Event platform: Redpanda instead of Apache Kafka |
| [0002](0002-inventory-concurrency-control.md) | Inventory concurrency: row-level locking + optimistic order versioning |
| [0003](0003-transactional-outbox.md) | Reliable event publish: transactional outbox, not CDC |
| [0004](0004-custom-saga-orchestrator.md) | Saga orchestration: custom lightweight orchestrator, not Temporal/Airflow |
| [0005](0005-spark-local-mode.md) | Data platform: PySpark Structured Streaming in single-node local mode |
| [0006](0006-forecasting-scope.md) | Demand forecasting: baseline first, lightweight secondary model |
| [0007](0007-terraform-not-applied.md) | AWS infrastructure: Terraform authored and validated, never applied |
| [0008](0008-monorepo-layout.md) | Monorepo layout and service boundaries |
| [0009](0009-authn-authz.md) | Authentication and authorization: JWT + RBAC |

New ADRs are numbered sequentially and never renumbered or deleted; a
superseded decision gets a new ADR that says so and links back.
