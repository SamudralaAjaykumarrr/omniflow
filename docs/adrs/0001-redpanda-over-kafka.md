# ADR 0001: Event Platform — Redpanda instead of Apache Kafka

## Status
Accepted

## Context
The spec requires "Kafka or Redpanda" for the event platform. The whole
system — API services, orchestrator, Spark pipeline, observability — runs on
one developer machine (measured: 8 CPUs, 15Gi RAM) with no paid cloud
services. Apache Kafka requires either ZooKeeper or KRaft-mode JVM tuning, and
in practice needs meaningful heap + page-cache headroom to behave well even at
toy scale; running it alongside Postgres, MinIO, Spark, and Prometheus/
Grafana/Jaeger on the same host is a real resource-contention risk.

## Decision
Use Redpanda as the broker. It speaks the Kafka wire protocol (so client
libraries, producer/consumer code, and Spark's Kafka source/sink are unchanged
either way), ships as a single binary with no ZooKeeper dependency, and has a
materially smaller memory/CPU footprint at this scale.

## Consequences
- Producer/consumer code, event contracts, and Spark jobs target the Kafka
  protocol, not a Redpanda-specific API — moving to real Apache Kafka or AWS
  MSK later (see the Terraform notes) is a configuration and broker-image
  change, not a code rewrite.
- Redpanda's own operational quirks (its Kafka-compatible admin APIs lag
  slightly behind newer Kafka features) are accepted; nothing in this project
  depends on a Kafka feature Redpanda doesn't support (no exactly-once
  transactions API usage, no tiered storage dependency).
- The AWS deployment path uses MSK, not "Redpanda in the cloud," because MSK
  is the AWS-native managed option the spec calls out — the local/cloud broker
  choice is intentionally allowed to differ, since both speak the same wire
  protocol.

## Alternatives considered
- **Apache Kafka + ZooKeeper**: heavier, more moving parts, no behavioral
  benefit for this project's scale.
- **Apache Kafka in KRaft mode**: lighter than ZooKeeper-Kafka but still a JVM
  process with non-trivial memory tuning; Redpanda's footprint is smaller for
  the same protocol guarantees at this scale.
- **AWS SQS/SNS (fully managed, no broker to run)**: rejected because it
  isn't Kafka-protocol, doesn't demonstrate partition-ordered consumer-group
  semantics or replay-by-offset, and doesn't match the spec's explicit ask.
