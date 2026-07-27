#!/usr/bin/env bash
# Idempotent test-data setup for Phase 10 load testing: brings up the real
# docker-compose stack, waits for the core services to be healthy, then
# seeds one fixed fulfillment node + a small fixed SKU pool with generous
# stock directly against inventory-service — the same "seed data directly,
# measured traffic goes through the gateway" precedent
# scripts/compose_smoke_test.sh already established.
#
# Deliberately fixed names/SKUs (not a random RUN_ID suffix, unlike the
# smoke test): k6/scenarios.js needs a stable dataset it can look up by name
# every run, across separate smoke/baseline/load/stress/spike invocations.
# Safe to rerun any number of times: the fulfillment node is only created if
# a node with this exact name doesn't already exist, and inventory-service's
# `POST /stock` (upsert_stock) sets available_qty absolutely — so rerunning
# this script always tops stock back up to LOAD_STOCK_QTY regardless of how
# much a previous load-test run consumed, without ever going negative or
# double-adding.
#
# Usage: bash scripts/load_test_setup.sh   (or: make load-setup)
set -euo pipefail

COMPOSE="docker compose"
INVENTORY_URL="${K6_INVENTORY_URL_HOST:-http://localhost:8002}"
GATEWAY_URL="${K6_BASE_URL_HOST:-http://localhost:8080}"

ORCHESTRATOR_URL="${K6_ORCHESTRATOR_URL_HOST:-http://localhost:8003}"

NODE_NAME="${LOAD_NODE_NAME:-load-test-node-1}"
SKU_PREFIX="${LOAD_SKU_PREFIX:-SKU-LOAD}"
# 100, not a smaller pool: a real finding from this session's own first
# baseline run (docs/phase-10-load-testing.md) — a small SKU pool shared by
# dozens of concurrent VUs causes a lot of orders to contend for the same
# `inventory_stock` row's lock (ADR 0002's row-level locking, working
# exactly as designed), which confounds "saga-consumer throughput" with
# "row-lock contention" as two separate real bottlenecks. A wider pool
# reduces the second effect so load-test results mostly reflect the first.
SKU_COUNT="${LOAD_SKU_COUNT:-100}"
STOCK_QTY="${LOAD_STOCK_QTY:-1000000}"
# Best-effort: how long to wait for a previous run's saga backlog to fully
# drain before handing control back (see the drain_backlog note below).
DRAIN_TIMEOUT_SECONDS="${LOAD_DRAIN_TIMEOUT_SECONDS:-240}"

log() { echo "[load-setup] $*"; }

log "bringing up the full stack..."
$COMPOSE up --build -d

# Real finding from this session's own first (uncalibrated) load-test run:
# the Phase 4/6 Spark bronze/silver/gold streaming jobs are not part of
# this phase's system under test, but `docker stats` showed them consuming
# roughly 5-6 of this host's 8 CPUs continuously (each Structured Streaming
# job polls/micro-batches on its own schedule regardless of whether any
# load test is running) — on an 8-CPU host that starves the actual
# services under test (api-gateway/order-service/inventory-service/
# fulfillment-orchestrator/postgres) of scheduled CPU time the moment k6
# adds concurrent traffic, producing request latency that reflects host
# contention, not those services' own real capacity. Stopped here (not
# just "everything happens to be slower") so load-test numbers measure the
# system this phase actually cares about; restarted at the end of this
# script's normal path is NOT done automatically (`make up`/`make demo`
# brings them back) — see docs/phase-10-load-testing.md.
log "stopping data-platform Spark streaming jobs (not under test, would dominate this host's CPU)..."
$COMPOSE stop spark-bronze spark-silver spark-gold lag-poller

wait_healthy() {
  local service="$1"
  local attempts=40
  for _ in $(seq 1 "$attempts"); do
    status=$($COMPOSE ps "$service" --format '{{.Health}}' 2>/dev/null || true)
    if [ "$status" = "healthy" ]; then
      log "$service is healthy"
      return 0
    fi
    sleep 3
  done
  log "FAIL: $service did not become healthy in time"
  $COMPOSE logs "$service" --tail 50
  exit 1
}

for svc in postgres redpanda order-service inventory-service fulfillment-orchestrator api-gateway; do
  wait_healthy "$svc"
done

log "checking whether fulfillment node '$NODE_NAME' already exists..."
EXISTING_NODE_ID=$(curl -sf "$INVENTORY_URL/fulfillment-nodes" \
  | python3 -c "
import sys, json
nodes = json.load(sys.stdin)
match = [n for n in nodes if n['name'] == '$NODE_NAME']
print(match[0]['id'] if match else '')
")

if [ -n "$EXISTING_NODE_ID" ]; then
  NODE_ID="$EXISTING_NODE_ID"
  log "node already exists: $NODE_ID (reusing, not recreating)"
else
  log "creating fulfillment node '$NODE_NAME'..."
  NODE_ID=$(curl -sf -X POST "$INVENTORY_URL/fulfillment-nodes" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"$NODE_NAME\", \"latitude\": 47.6, \"longitude\": -122.3, \"capacity_per_day\": 100000}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
  log "node created: $NODE_ID"
fi

log "seeding/topping-up $SKU_COUNT SKUs ($SKU_PREFIX-0001..$(printf '%04d' "$SKU_COUNT")) at $STOCK_QTY units each..."
for i in $(seq 1 "$SKU_COUNT"); do
  SKU=$(printf '%s-%04d' "$SKU_PREFIX" "$i")
  curl -sf -X POST "$INVENTORY_URL/stock" \
    -H 'Content-Type: application/json' \
    -d "{\"sku\": \"$SKU\", \"node_id\": \"$NODE_ID\", \"available_qty\": $STOCK_QTY, \"reorder_threshold\": 1}" \
    > /dev/null
done
log "stock seeded/topped-up for $SKU_COUNT SKUs"

log "sanity check: logging in as the seeded ops account through the real gateway..."
curl -sf -X POST "$GATEWAY_URL/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email": "ops@omniflow.local", "password": "'"${GATEWAY_SEED_OPS_PASSWORD:-ops_dev_only}"'"}' \
  > /dev/null
log "ops login OK"

log "PASS: load-test data ready — node=$NODE_ID, $SKU_COUNT SKUs at $STOCK_QTY units each"

# Real finding from this session's own first baseline run: order-creation
# through the gateway is far faster than the fulfillment-orchestrator's
# single sequential Kafka consumer can drive orders to SHIPPED (measured
# sustained throughput on this laptop: roughly 1.5-2 orders/sec — see
# docs/phase-10-load-testing.md). A profile run that starts while a
# previous run's backlog is still draining would contaminate its own
# order_retrieval/e2e_order_workflow results and make profile-to-profile
# comparisons meaningless. Best-effort only: a stale RUNNING saga from the
# known, accepted saga-resume gap (RISKS.md #11) could in principle never
# clear, so this warns and continues rather than failing the whole setup.
log "waiting for any previous run's saga backlog to drain (best-effort, up to ${DRAIN_TIMEOUT_SECONDS}s)..."
deadline=$((SECONDS + DRAIN_TIMEOUT_SECONDS))
while :; do
  running=$(curl -sf "$ORCHESTRATOR_URL/saga-instances?status=RUNNING" \
    | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")
  if [ "$running" = "0" ]; then
    log "saga backlog drained (0 RUNNING)"
    break
  fi
  if [ $SECONDS -ge $deadline ]; then
    log "WARN: $running saga(s) still RUNNING after ${DRAIN_TIMEOUT_SECONDS}s — proceeding anyway (best-effort only)"
    break
  fi
  sleep 5
done
