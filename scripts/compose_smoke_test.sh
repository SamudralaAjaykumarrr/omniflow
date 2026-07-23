#!/usr/bin/env bash
# End-to-end smoke test against the REAL running docker-compose stack:
# Postgres, Redpanda, API Gateway, Order/Inventory/Orchestrator services,
# both outbox relays, the order-service validator consumer, and the
# orchestrator's saga consumer. Creates a real order through the gateway and
# polls until the saga carries it all the way to SHIPPED, or fails loudly.
#
# Usage: bash scripts/compose_smoke_test.sh   (or: make smoke)
set -euo pipefail

COMPOSE="docker compose"
GATEWAY_URL="http://localhost:8080"
INVENTORY_URL="http://localhost:8002"
ORCHESTRATOR_URL="http://localhost:8003"
POLL_TIMEOUT_SECONDS=60

log() { echo "[smoke] $*"; }

log "bringing up the full stack..."
$COMPOSE up --build -d

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

log "creating a fulfillment node and seeding stock..."
NODE_ID=$(curl -sf -X POST "$INVENTORY_URL/fulfillment-nodes" \
  -H 'Content-Type: application/json' \
  -d '{"name": "smoke-test-node", "latitude": 47.6, "longitude": -122.3, "capacity_per_day": 100}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
log "node: $NODE_ID"

curl -sf -X POST "$INVENTORY_URL/stock" \
  -H 'Content-Type: application/json' \
  -d "{\"sku\": \"SKU-SMOKE\", \"node_id\": \"$NODE_ID\", \"available_qty\": 10, \"reorder_threshold\": 1}" \
  > /dev/null

CUSTOMER_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
IDEMPOTENCY_KEY=$(python3 -c "import uuid; print(uuid.uuid4())")

log "creating an order via the API Gateway..."
ORDER_JSON=$(curl -sf -X POST "$GATEWAY_URL/api/orders" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -d "{\"customer_id\": \"$CUSTOMER_ID\", \"customer_email\": \"smoke@example.com\", \"customer_display_name\": \"Smoke Test\", \"items\": [{\"sku\": \"SKU-SMOKE\", \"qty\": 2, \"unit_price\": 9.99}]}")
ORDER_ID=$(echo "$ORDER_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
log "order created: $ORDER_ID (initial status: $(echo "$ORDER_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])"))"

log "polling order status until SHIPPED (timeout ${POLL_TIMEOUT_SECONDS}s)..."
deadline=$((SECONDS + POLL_TIMEOUT_SECONDS))
status="UNKNOWN"
while [ $SECONDS -lt $deadline ]; do
  status=$(curl -sf "$GATEWAY_URL/api/orders/$ORDER_ID" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  if [ "$status" = "SHIPPED" ]; then
    break
  fi
  if [ "$status" = "FAILED" ]; then
    log "FAIL: order reached FAILED instead of SHIPPED"
    curl -s "$ORCHESTRATOR_URL/saga-instances/$ORDER_ID" | python3 -m json.tool || true
    exit 1
  fi
  sleep 1
done

if [ "$status" != "SHIPPED" ]; then
  log "FAIL: order did not reach SHIPPED within ${POLL_TIMEOUT_SECONDS}s (last status: $status)"
  curl -s "$ORCHESTRATOR_URL/saga-instances/$ORDER_ID" | python3 -m json.tool || true
  exit 1
fi
log "order reached SHIPPED"

log "checking saga completed cleanly..."
SAGA_STATUS=$(curl -sf "$ORCHESTRATOR_URL/saga-instances/$ORDER_ID" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
if [ "$SAGA_STATUS" != "COMPLETED" ]; then
  log "FAIL: saga status is $SAGA_STATUS, expected COMPLETED"
  exit 1
fi
log "saga status: COMPLETED"

log "checking no dead letters were produced..."
DEAD_LETTER_COUNT=$(curl -sf "$ORCHESTRATOR_URL/dead-letters" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")
if [ "$DEAD_LETTER_COUNT" != "0" ]; then
  log "FAIL: expected 0 unreplayed dead letters, found $DEAD_LETTER_COUNT"
  exit 1
fi
log "dead letters: 0"

log "verifying stock was actually decremented..."
FINAL_STOCK=$(curl -sf "$INVENTORY_URL/stock/SKU-SMOKE/$NODE_ID" | python3 -c "import sys, json; print(json.load(sys.stdin)['available_qty'])")
if [ "$FINAL_STOCK" != "8" ]; then
  log "FAIL: expected available_qty=8 after reserving 2 of 10, got $FINAL_STOCK"
  exit 1
fi
log "stock: available_qty=8 (10 - 2 reserved)"

log "PASS: full order lifecycle completed end-to-end through the real stack"
