#!/usr/bin/env bash
# Phase 8 (Failure laboratory) end-to-end smoke test against the REAL
# running docker-compose stack: triggers all 10 deterministic failure
# scenarios through the failure-lab's real HTTP API, polls each to a
# terminal state, asserts the expected outcome (PASSED or RECOVERED, never
# FAILED/ERROR), then reruns every scenario a second time after calling its
# reset endpoint — proving the "safe to rerun" requirement for the whole
# catalog, not just asserted in a docstring.
#
# Usage: bash scripts/phase8_smoke_test.sh   (or: make phase8-smoke)
set -euo pipefail

COMPOSE="docker compose"
FAILURE_LAB_URL="http://localhost:8004"
POLL_TIMEOUT_SECONDS=45

log() { echo "[phase8-smoke] $*"; }

log "bringing up the full stack..."
$COMPOSE up --build -d

wait_healthy() {
  local service="$1"
  local attempts=60
  for _ in $(seq 1 "$attempts"); do
    status=$($COMPOSE ps "$service" --format '{{.Health}}' 2>/dev/null || true)
    if [ "$status" = "healthy" ]; then
      log "$service is healthy"
      return 0
    fi
    sleep 3
  done
  log "FAIL: $service did not become healthy in time"
  $COMPOSE logs "$service" --tail 80
  exit 1
}

for svc in postgres redpanda order-service inventory-service fulfillment-orchestrator api-gateway failure-lab; do
  wait_healthy "$svc"
done

SCENARIOS=(
  "payment-decline"
  "payment-timeout"
  "inventory-oversell-race"
  "duplicate-order-submit"
  "duplicate-event-delivery"
  "poison-message-dlq"
  "malformed-kafka-record"
  "late-event-arrival"
  "saga-crash-resume"
  "downstream-outage"
)

log "verifying the catalog exposes exactly 10 scenarios..."
CATALOG_COUNT=$(curl -sf "$FAILURE_LAB_URL/scenarios" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))")
if [ "$CATALOG_COUNT" != "10" ]; then
  log "FAIL: expected 10 scenarios in the catalog, found $CATALOG_COUNT"
  exit 1
fi
log "catalog: 10 scenarios"

trigger_and_wait() {
  local scenario_id="$1"
  local run_json run_id status deadline

  run_json=$(curl -sf -X POST "$FAILURE_LAB_URL/scenarios/$scenario_id/trigger")
  run_id=$(echo "$run_json" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

  deadline=$((SECONDS + POLL_TIMEOUT_SECONDS))
  status="RUNNING"
  while [ "$status" = "RUNNING" ]; do
    if [ $SECONDS -ge $deadline ]; then
      log "FAIL: $scenario_id run $run_id did not finish within ${POLL_TIMEOUT_SECONDS}s"
      exit 1
    fi
    sleep 1
    status=$(curl -sf "$FAILURE_LAB_URL/scenarios/$scenario_id/runs/$run_id" \
      | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  done

  if [ "$status" != "PASSED" ] && [ "$status" != "RECOVERED" ]; then
    log "FAIL: $scenario_id run $run_id ended $status, expected PASSED or RECOVERED"
    curl -s "$FAILURE_LAB_URL/scenarios/$scenario_id/runs/$run_id" | python3 -m json.tool || true
    exit 1
  fi
  log "$scenario_id: $status (run $run_id)"
}

log "--- pass 1: every scenario from a clean start ---"
for id in "${SCENARIOS[@]}"; do
  trigger_and_wait "$id"
done

log "--- reset every scenario ---"
for id in "${SCENARIOS[@]}"; do
  curl -sf -X POST "$FAILURE_LAB_URL/scenarios/$id/reset" > /dev/null
  log "$id: reset"
done

log "--- pass 2: rerun every scenario after reset (proves safe-to-rerun) ---"
for id in "${SCENARIOS[@]}"; do
  trigger_and_wait "$id"
done

log "all 10 scenarios PASSED/RECOVERED on both passes."
