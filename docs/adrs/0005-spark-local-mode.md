# ADR 0005: Data Platform — PySpark Structured Streaming in Single-Node Local Mode

## Status
Accepted

## Context
The spec requires a PySpark Structured Streaming bronze/silver/gold pipeline
against MinIO/S3, with checkpointing, watermarks, and reprocessing. Real Spark
deployments run as a cluster (EMR, standalone cluster, or Kubernetes); none of
that is available or appropriate for a single-machine, no-paid-services local
demo, and provisioning a multi-node cluster locally would consume a large
share of the 15Gi RAM / 8 CPU budget shared with Redpanda, Postgres, MinIO,
and the observability stack.

## Decision
Run Spark in `local[*]` mode inside a single container: one JVM process using
all host cores as executor threads, no separate driver/worker/cluster-manager
processes. All Structured Streaming semantics used (checkpointing, watermarks,
`dropDuplicatesWithinWatermark`, `foreachBatch` sinks) behave identically in
local mode and cluster mode — the code that runs against a real EMR/Kubernetes
Spark cluster is the same code, only the `--master` / cluster config differs.

## Consequences
- Throughput is bounded by one machine — acceptable for a demo-scale event
  generator; not a claim about production throughput. Any load-test numbers
  reported in `docs/resume-evidence.md` are labeled as local single-node
  numbers, not extrapolated.
- No cluster-manager operational complexity (no YARN/Kubernetes scheduler to
  configure) for local dev.
- The cloud deployment story (`infra/terraform`, not applied) documents EMR
  or Kubernetes-based Spark as the production target; this ADR's scope is
  explicitly local-only.

## Alternatives considered
- **Multi-container Spark standalone cluster (1 master + N workers) in
  Compose**: adds real cluster semantics but meaningfully more RAM/CPU
  overhead and operational surface for no correctness benefit at this
  project's data volumes; rejected for the local demo, kept as a documented
  option if the grader wants to see it.
- **Skip Spark, use plain Python/Pandas batch jobs**: would not demonstrate
  Structured Streaming (watermarks, streaming dedup, checkpointed resume),
  which is an explicit spec requirement; rejected.
- **Flink instead of Spark**: equally valid streaming engine, but the spec
  explicitly asks for PySpark; not pursued.
