#!/usr/bin/env bash
# End-to-end smoke test against the REAL running docker-compose stack:
# Postgres, Redpanda, API Gateway, Order/Inventory/Orchestrator services,
# both outbox relays, the order-service validator consumer, and the
# orchestrator's saga consumer. Creates a real order through the gateway and
# polls until the saga carries it all the way to SHIPPED, or fails loudly.
# Also verifies the Phase 3 observability stack: a real trace for this run
# lands in Jaeger, Prometheus is actually scraping every target, and
# Grafana's provisioned dashboard/datasource are live.
#
# Usage: bash scripts/compose_smoke_test.sh   (or: make smoke)
set -euo pipefail

COMPOSE="docker compose"
GATEWAY_URL="http://localhost:8080"
INVENTORY_URL="http://localhost:8002"
ORCHESTRATOR_URL="http://localhost:8003"
JAEGER_URL="http://localhost:16686"
PROMETHEUS_URL="http://localhost:9090"
GRAFANA_URL="http://localhost:3000"
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

for svc in postgres redpanda order-service inventory-service fulfillment-orchestrator api-gateway jaeger prometheus; do
  wait_healthy "$svc"
done

log "waiting for Grafana to answer its health check..."
deadline=$((SECONDS + POLL_TIMEOUT_SECONDS))
until curl -sf "$GRAFANA_URL/api/health" >/dev/null 2>&1; do
  if [ $SECONDS -ge $deadline ]; then
    log "FAIL: grafana did not become ready in time"
    $COMPOSE logs grafana --tail 50
    exit 1
  fi
  sleep 3
done
log "grafana is ready"

# A unique suffix per run — the node/SKU names must not collide with a
# previous run's rows still sitting in the (persistent, non-test) dev
# database volume, or fulfillment-node creation 409s on a duplicate name.
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")
NODE_NAME="smoke-test-node-$RUN_ID"
SKU="SKU-SMOKE-$RUN_ID"

log "creating a fulfillment node and seeding stock..."
NODE_ID=$(curl -sf -X POST "$INVENTORY_URL/fulfillment-nodes" \
  -H 'Content-Type: application/json' \
  -d "{\"name\": \"$NODE_NAME\", \"latitude\": 47.6, \"longitude\": -122.3, \"capacity_per_day\": 100}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
log "node: $NODE_ID"

curl -sf -X POST "$INVENTORY_URL/stock" \
  -H 'Content-Type: application/json' \
  -d "{\"sku\": \"$SKU\", \"node_id\": \"$NODE_ID\", \"available_qty\": 10, \"reorder_threshold\": 1}" \
  > /dev/null

CUSTOMER_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
IDEMPOTENCY_KEY=$(python3 -c "import uuid; print(uuid.uuid4())")

log "creating an order via the API Gateway..."
ORDER_JSON=$(curl -sf -X POST "$GATEWAY_URL/api/orders" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -d "{\"customer_id\": \"$CUSTOMER_ID\", \"customer_email\": \"smoke-$RUN_ID@example.com\", \"customer_display_name\": \"Smoke Test\", \"items\": [{\"sku\": \"$SKU\", \"qty\": 2, \"unit_price\": 9.99}]}")
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
FINAL_STOCK=$(curl -sf "$INVENTORY_URL/stock/$SKU/$NODE_ID" | python3 -c "import sys, json; print(json.load(sys.stdin)['available_qty'])")
if [ "$FINAL_STOCK" != "8" ]; then
  log "FAIL: expected available_qty=8 after reserving 2 of 10, got $FINAL_STOCK"
  exit 1
fi
log "stock: available_qty=8 (10 - 2 reserved)"

log "verifying traces landed in Jaeger for every traced service..."
# Spans are exported in a BatchSpanProcessor's background thread, so give
# the last batch a moment to flush before querying.
sleep 5
for svc in api-gateway order-service inventory-service fulfillment-orchestrator; do
  TRACE_COUNT=$(curl -sf "$JAEGER_URL/api/traces?service=$svc&lookback=10m&limit=5" \
    | python3 -c "import sys, json; print(len(json.load(sys.stdin)['data']))")
  if [ "$TRACE_COUNT" = "0" ]; then
    log "FAIL: no traces found in Jaeger for service '$svc'"
    exit 1
  fi
  log "jaeger: $TRACE_COUNT trace(s) found for $svc"
done

log "verifying Prometheus is scraping every target..."
TARGETS_JSON=$(curl -sf "$PROMETHEUS_URL/api/v1/targets")
DOWN_TARGETS=$(echo "$TARGETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']['activeTargets']
down = [t['labels']['job'] for t in data if t['health'] != 'up']
print(','.join(down))
")
if [ -n "$DOWN_TARGETS" ]; then
  log "FAIL: Prometheus targets not up: $DOWN_TARGETS"
  exit 1
fi
TARGET_COUNT=$(echo "$TARGETS_JSON" | python3 -c "import sys, json; print(len(json.load(sys.stdin)['data']['activeTargets']))")
log "prometheus: all $TARGET_COUNT scrape target(s) are up"

log "verifying Prometheus has real samples for a request-count metric..."
HTTP_REQUEST_SAMPLES=$(curl -sf "$PROMETHEUS_URL/api/v1/query?query=sum(http_requests_total)" \
  | python3 -c "import sys, json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')")
if [ "$(python3 -c "print(1 if float('$HTTP_REQUEST_SAMPLES') > 0 else 0)")" != "1" ]; then
  log "FAIL: expected http_requests_total > 0 in Prometheus, got $HTTP_REQUEST_SAMPLES"
  exit 1
fi
log "prometheus: http_requests_total sum = $HTTP_REQUEST_SAMPLES"

log "verifying Grafana's Prometheus datasource and provisioned dashboard..."
DS_STATUS=$(curl -sf "$GRAFANA_URL/api/datasources/uid/prometheus" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['type'])")
if [ "$DS_STATUS" != "prometheus" ]; then
  log "FAIL: Grafana's 'prometheus' datasource is not provisioned correctly"
  exit 1
fi
DASHBOARD_COUNT=$(curl -sf "$GRAFANA_URL/api/search?query=OmniFlow" \
  | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")
if [ "$DASHBOARD_COUNT" = "0" ]; then
  log "FAIL: no provisioned Grafana dashboard found"
  exit 1
fi
log "grafana: Prometheus datasource live, $DASHBOARD_COUNT dashboard(s) provisioned"

log "PASS: full order lifecycle completed end-to-end through the real stack, traces verified in Jaeger, metrics verified in Prometheus and Grafana"
