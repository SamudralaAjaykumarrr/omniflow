#!/usr/bin/env bash
# Phase 6 end-to-end smoke test: real synthetic traffic (including
# duplicate/late/malformed injection) -> real Kafka -> real Bronze/Silver/
# Gold Parquet on real MinIO -> real data-quality report, plus a restart
# check proving a second Bronze run doesn't reprocess already-committed
# offsets. Complements `scripts/compose_smoke_test.sh` (which exercises the
# order-service/inventory-service/fulfillment-orchestrator saga, not the
# data platform) — see docs/phase-6-streaming-data-platform.md.
#
# Zero-cost, local-only: everything here is `docker compose` against
# Redpanda/MinIO/Spark already running on this host. Never deletes data —
# `app.bronze`/`app.silver`/`app.gold.runner --once` are append-only
# (availableNow trigger), same as their long-running streaming counterparts.
set -euo pipefail

COMPOSE="docker compose"
ORDERS="${PHASE6_SMOKE_ORDERS:-20}"
SEED="${PHASE6_SMOKE_SEED:-42}"

log() { echo "[phase6-smoke] $*"; }

# Retries a command up to 3 times with a short backoff. This host's Docker
# Desktop WSL2 backend has an intermittent bind-mount race when a one-shot
# dependency container (minio-init) gets recreated in quick succession
# ("error mounting ... no such file or directory") — a real, reproducibly
# hit flake while writing this script, unrelated to this script's own
# logic. Retrying absorbs it rather than failing the whole smoke test on a
# transient host issue.
run_with_retry() {
  local attempt
  for attempt in 1 2 3; do
    if "$@"; then
      return 0
    fi
    # Retry diagnostics go to stderr, never stdout — `object_count` below
    # captures a wrapped command's stdout via `$(...)`, and a retry message
    # on stdout would corrupt the object-count it parses out of that.
    log "command failed (attempt ${attempt}/3): $*" >&2
    [ "$attempt" -lt 3 ] && sleep 3
  done
  return 1
}

log "bringing up prerequisite infra (redpanda, minio) if not already running..."
run_with_retry $COMPOSE up -d redpanda redpanda-topics minio minio-init >/dev/null
$COMPOSE build spark-gold >/dev/null

# Every subsequent `spark-gold` invocation below passes --no-deps: spark-gold
# depends_on minio-init (service_completed_successfully), and without
# --no-deps `docker compose run` re-evaluates that on every single call,
# re-creating the one-shot minio-init container repeatedly — compounding the
# flake described above. minio-init has already run once (above); skipping
# dependency re-evaluation for the rest of this script avoids re-triggering it.

object_count() {
  # Prints just the leading object count from `app.inspect <prefix>`'s
  # first line ("<prefix>: N object(s), M byte(s)").
  local prefix="$1"
  local output
  output="$(run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.inspect "$prefix")"
  echo "$output" | head -n1 | sed -E 's/^[^:]+: ([0-9]+) object.*/\1/'
}

log "generating deterministic synthetic traffic (orders=$ORDERS seed=$SEED, with duplicate/late/malformed injection)..."
# --late-rate is kept under app.dq.checks.LATE_RATE_THRESHOLD (0.10) so this
# smoke test's own dq-report step is expected to pass, not exercise that
# gate's failure path (that's `test_dq.py`'s job, against static data).
run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.generator \
  --orders "$ORDERS" --dead-letters 2 \
  --duplicate-rate 0.15 --late-rate 0.05 --malformed-rate 0.15 \
  --seed "$SEED"

log "running Bronze (Kafka -> raw Parquet), first pass..."
run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.bronze --once
bronze_count_1="$(object_count bronze)"
rejects_count_1="$(object_count bronze_rejects)"
log "bronze: ${bronze_count_1} object(s); bronze_rejects (malformed quarantine): ${rejects_count_1} object(s)"

log "running Bronze again (restart/checkpoint check — must not reprocess committed offsets)..."
run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.bronze --once
bronze_count_2="$(object_count bronze)"
log "bronze after restart: ${bronze_count_2} object(s)"
if [ "$bronze_count_2" != "$bronze_count_1" ]; then
  log "FAIL: Bronze object count changed on a restart with no new Kafka data (${bronze_count_1} -> ${bronze_count_2}) — checkpoint did not prevent reprocessing."
  exit 1
fi
log "OK: restart did not reprocess already-committed Bronze offsets."

if [ "$rejects_count_1" = "0" ]; then
  log "WARNING: no malformed records were quarantined this run (probabilistic --malformed-rate did not fire) — not a failure, but re-run with a different --seed to exercise this path if you need to verify it."
fi

log "running Silver (Bronze -> validated/deduped/late-routed Parquet)..."
run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.silver --once
silver_count="$(object_count silver)"
silver_rejects_count="$(object_count silver_rejects)"
late_count="$(object_count late_events)"
log "silver: ${silver_count} object(s); silver_rejects: ${silver_rejects_count} object(s); late_events: ${late_count} object(s)"

if [ "$silver_count" = "0" ]; then
  log "FAIL: Silver produced no output — expected on-time, valid rows from ${ORDERS} synthetic orders."
  exit 1
fi

log "running Gold (Silver -> business aggregates)..."
run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.gold.runner --once
gold_count="$(object_count gold)"
log "gold: ${gold_count} object(s)"

if [ "$gold_count" = "0" ]; then
  log "FAIL: Gold produced no output."
  exit 1
fi

log "running data-quality report..."
if ! run_with_retry $COMPOSE run --rm --no-deps spark-gold python -m app.dq.report; then
  log "FAIL: data-quality report exited non-zero (a gating check failed) — see output above."
  exit 1
fi

log "PASS: Phase 6 smoke test complete (Bronze/Silver/Gold/rejects/late_events all inspectable, restart safe, DQ report clean)."
