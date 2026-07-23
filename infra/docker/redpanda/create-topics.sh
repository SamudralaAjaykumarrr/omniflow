#!/usr/bin/env bash
# One-shot job: create every event-catalog topic (docs/event-catalog.md) if it
# doesn't already exist. Idempotent — safe to re-run on every `docker compose up`.
set -euo pipefail

BROKER="${REDPANDA_BROKER:-redpanda:9092}"
TOPICS=(
  "order.created"
  "order.validated"
  "inventory.reservation.requested"
  "inventory.reserved"
  "inventory.rejected"
  "fulfillment.assigned"
  "order.shipped"
  "order.cancelled"
  "order.failed"
  "inventory.low"
  "deadletter.event"
)

existing_topics() {
  rpk topic list --brokers "$BROKER" | awk 'NR > 1 {print $1}'
}

for topic in "${TOPICS[@]}"; do
  if existing_topics | grep -qx "$topic"; then
    echo "topic already exists: $topic"
  else
    rpk topic create "$topic" --brokers "$BROKER" --partitions 3 --replicas 1
  fi
done

echo "all topics present:"
rpk topic list --brokers "$BROKER"
