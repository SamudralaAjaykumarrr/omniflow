#!/usr/bin/env bash
# Phase 6 demand-forecasting smoke test: a small, deterministic end-to-end
# run of every forecasting CLI subcommand (generate synthetic history ->
# prepare dataset -> validate -> train baseline -> train secondary ->
# evaluate -> select champion -> future forecast -> inspect), verifying the
# expected files and schemas actually land.
#
# Unlike scripts/phase6_smoke_test.sh (the streaming-data-platform smoke
# test), this needs no live Redpanda/MinIO/Postgres — `app.forecasting` is a
# pandas/scikit-learn batch pipeline, and every path here is redirected to a
# host-bind-mounted scratch directory rather than the real MinIO paths
# `app.forecasting.paths` builds by default (see
# docs/phase-6-demand-forecasting.md 'Local demonstration'). Each CLI
# subcommand runs in its own throwaway `docker compose run` container, so
# the scratch directory (including local model artifacts, via
# FORECAST_ARTIFACT_DIR) is bind-mounted specifically so state survives
# across those separate container invocations.
set -euo pipefail

COMPOSE="docker compose"
HOST_SCRATCH="$(pwd)/services/data-platform/.forecast_smoke_output"
SCRATCH="/tmp/forecast_smoke"
RUN_ID="smoke-test"

log() { echo "[forecast-smoke] $*"; }

log "resetting local scratch output dir (disposable, gitignored)..."
rm -rf "$HOST_SCRATCH"
mkdir -p "$HOST_SCRATCH"

run_cli() {
  $COMPOSE run --rm --no-deps \
    -e FORECAST_SEED=99 \
    -e FORECAST_HISTORY_START_DATE=2025-01-01 \
    -e FORECAST_HISTORY_END_DATE=2025-06-30 \
    -e FORECAST_NUM_SKUS=4 \
    -e FORECAST_NUM_LOCATIONS=2 \
    -e FORECAST_FORECAST_HORIZON_DAYS=7 \
    -e FORECAST_MIN_HISTORY_DAYS=30 \
    -e FORECAST_ARTIFACT_DIR="$SCRATCH/artifacts" \
    -v "$HOST_SCRATCH:$SCRATCH" \
    spark-gold python -m app.forecasting.cli "$@"
}

log "building spark-gold image (the forecasting CLI lives in the data-platform package)..."
$COMPOSE build spark-gold >/dev/null

log "generating deterministic synthetic history (seed=99, 4 SKUs x 2 locations, 2025-01-01..2025-06-30)..."
run_cli generate-history --output "$SCRATCH/history.parquet"

log "preparing the feature-engineered forecasting dataset..."
run_cli prepare --input "$SCRATCH/history.parquet" --output "$SCRATCH/dataset.parquet"

log "validating the prepared dataset (data-quality gate)..."
run_cli validate --input "$SCRATCH/dataset.parquet"

log "training the seasonal-naive baseline (run_id=$RUN_ID)..."
run_cli train-baseline --input "$SCRATCH/dataset.parquet" --run-id "$RUN_ID"

log "training the secondary model (HistGradientBoostingRegressor, run_id=$RUN_ID)..."
run_cli train-secondary --input "$SCRATCH/dataset.parquet" --run-id "$RUN_ID"

log "evaluating both models against the chronological validation split..."
run_cli evaluate --input "$SCRATCH/dataset.parquet" --run-id "$RUN_ID" \
  --output "$SCRATCH/evaluation.json"

log "selecting the champion model from measured metrics..."
run_cli select --input "$SCRATCH/evaluation.json" --run-id "$RUN_ID" \
  --output "$SCRATCH/selection.json"

log "generating the future forecast from the champion model..."
run_cli forecast --input "$SCRATCH/dataset.parquet" --history "$SCRATCH/history.parquet" \
  --selection "$SCRATCH/selection.json" --run-id "$RUN_ID" \
  --output "$SCRATCH/forecast.parquet"

log "inspecting forecast output, metrics, and selection..."
run_cli inspect forecast --path "$SCRATCH/forecast.parquet"
run_cli inspect metrics --path "$SCRATCH/evaluation.json"
run_cli inspect selection --path "$SCRATCH/selection.json"

log "verifying forecast row count and schema..."
cat > "$HOST_SCRATCH/verify.py" <<'PYEOF'
import json
import sys

import pandas as pd

scratch = sys.argv[1]
forecast = pd.read_parquet(f"{scratch}/forecast.parquet")

expected_rows = 7 * 4 * 2  # horizon x skus x locations
if len(forecast) != expected_rows:
    print(f"FAIL: expected {expected_rows} forecast rows, got {len(forecast)}")
    sys.exit(1)

required = {
    "forecast_generated_at", "forecast_date", "horizon", "sku", "location_id",
    "predicted_units", "model_name", "model_version", "run_id", "training_cutoff",
}
missing = required - set(forecast.columns)
if missing:
    print(f"FAIL: forecast output missing columns: {missing}")
    sys.exit(1)

if (forecast["predicted_units"] < 0).any():
    print("FAIL: forecast contains negative predicted_units")
    sys.exit(1)

with open(f"{scratch}/selection.json") as f:
    selection = json.load(f)
if selection["champion_name"] not in {"seasonal_naive", "hist_gradient_boosting"}:
    print(f"FAIL: unexpected champion_name {selection['champion_name']!r}")
    sys.exit(1)

with open(f"{scratch}/evaluation.json") as f:
    evaluation = json.load(f)
if set(evaluation["models"].keys()) != {"seasonal_naive", "hist_gradient_boosting"}:
    print(f"FAIL: evaluation.json missing a model's results: {evaluation['models'].keys()}")
    sys.exit(1)

print(
    f"OK: {len(forecast)} forecast row(s), champion={selection['champion_name']} "
    f"({selection['metric_name']}: baseline={selection['baseline_value']:.4f} "
    f"secondary={selection['secondary_value']:.4f})"
)
PYEOF
run_cli_no_module() {
  $COMPOSE run --rm --no-deps -v "$HOST_SCRATCH:$SCRATCH" spark-gold python "$SCRATCH/verify.py" "$SCRATCH"
}
if ! run_cli_no_module; then
  log "FAIL: forecast output verification failed — see output above."
  exit 1
fi

log "PASS: Phase 6 demand-forecasting smoke test complete (dataset/baseline/secondary/evaluation/selection/forecast all produced, inspectable, and schema-verified)."
