# Phase 6: Demand Forecasting

## Purpose / business problem

Predict near-term unit demand per SKU per location so replenishment and
staffing decisions can be made ahead of time, instead of reactively after a
stockout or an overstock. This phase implements the forecasting job named
in `docs/architecture.md`'s target-state diagram ("Forecasting Job — Python
(scikit-learn/statsmodels), Baseline + model, batch") and scoped in
[ADR 0006](adrs/0006-forecasting-scope.md): a baseline forecast first, a
lightweight secondary model second, both measured honestly.

## Scope

A standalone, zero-cost, local batch pipeline — no callers on the order/
inventory/fulfillment critical path, so it cannot block or slow down order
processing if it is wrong, slow, or down. In scope: synthetic historical
demand, a feature-engineered dataset, a seasonal-naive baseline, a
`HistGradientBoostingRegressor` secondary model, chronological (never
random) evaluation, a documented champion-selection rule, and a future
forecast. Out of scope (explicitly, per ADR 0006 and the phase spec):
Prophet, XGBoost, deep learning, any paid model API, and any real
proprietary retail dataset.

## Data sources

The real event catalog cannot supply this phase's target grain: `order.
created`'s item payload (`OrderItemData` in
`services/event-contracts/event_contracts/schemas.py`) carries `sku, qty,
unit_price` only — no location/node attribution (see
`app.gold.queries`'s module docstring, also noted in
`docs/data-pipeline.md`'s Gold table) — and this repo's live data volume is
whatever a smoke test happened to generate, nowhere near enough for a
meaningful per-SKU-per-location model. Per the phase spec ("When the live
local dataset is too small for meaningful model evaluation, create a
deterministic synthetic historical-demand dataset that follows the existing
domain model") and ADR 0006, a deterministic synthetic history
(`app.forecasting.synthetic`) is the dataset this phase trains and
evaluates against. It is explicitly synthetic — not derived from, and not
resembling, any real retailer's data.

## Dataset grain

**SKU x location x calendar date**, one row per combination
(`app.forecasting.features.GRAIN_COLS`). SKUs are named `SKU-0001..SKU-NNNN`
and locations `LOC-01..LOC-NN` — not tied to the transactional `orders`/
`inventory_stock` schema's real identifiers (which have no location
attribution to begin with), but shaped the same way (`sku` as a string,
a per-location identifier) so nothing here conflicts with
`docs/data-model.md`'s existing entities.

Fields (`app.forecasting.synthetic.generate_synthetic_history`):

| Field | Meaning |
|---|---|
| `date`, `sku`, `location_id` | grain |
| `units_demanded` | realized demand (the forecast target) |
| `units_fulfilled` | demand actually fulfilled (capped by `stock_available`) |
| `lost_sales` | `units_demanded - units_fulfilled` |
| `order_count` | approximate order count implied by demand and a per-SKU average items-per-order |
| `stock_available` | on-hand stock that day (low on stockout days) |
| `price` | that day's price (reduced during a promo) |
| `promo_flag` | 1 on a randomly chosen promo day |
| `is_holiday` | 1 on a synthetic holiday date |
| `is_stockout` | 1 when `stock_available` was deliberately constrained |

**Realized vs. fulfilled vs. lost demand are kept as separate columns, on
purpose**: the model is trained to predict `units_demanded` (realized
demand), never `units_fulfilled` — training against fulfilled demand would
teach the model to under-forecast whenever a past stockout capped what was
actually recorded, which is exactly the kind of self-reinforcing shortage
loop a demand forecast should not encode.

## Synthetic-data assumptions (section B)

All of the following are deliberate, documented, and reproducible — never
presented as real:

- **Seed**: `FORECAST_SEED` (default 42) drives a single
  `numpy.random.default_rng`; the entire history is generated from one
  sequential draw of that generator, so the same config always produces
  byte-identical output (`tests/forecasting/test_synthetic.py::
  test_reproducible_for_same_seed`).
- **Shape**: `FORECAST_HISTORY_START_DATE`/`FORECAST_HISTORY_END_DATE`,
  `FORECAST_NUM_SKUS`, `FORECAST_NUM_LOCATIONS`, `FORECAST_DEMAND_SCALE` are
  all configurable (`app.forecasting.config.ForecastSettings`).
- **Weekly seasonality**: a fixed, generic "retail" day-of-week curve
  (weekends higher than midweek) — not fit to any real dataset.
- **Annual seasonality**: one sine cycle peaking in the winter holiday
  season, +/-25% amplitude — a deliberately simple assumption.
- **Trend**: a per-SKU linear daily growth/decline rate, drawn once per SKU.
- **SKU-specific characteristics**: per-SKU base demand (log-normal), price,
  average items-per-order, and a 15% chance of being "intermittent"
  (frequent exact-zero days) — each drawn once per SKU, so a SKU has one
  consistent personality across its whole history.
  **Location-specific effects**: a per-location demand multiplier
  (0.6x-1.4x), simulating different store sizes/traffic.
- **Promotions**: each SKU has its own random daily promo probability
  (1-4%); a promo day gets a 1.5x-3x demand multiplier and a discounted
  price.
- **Stockouts**: ~2% of rows have on-hand stock too low to cover demand,
  capping `units_fulfilled` below `units_demanded`.
- **Intermittent demand**: "intermittent" SKUs get a Bernoulli mask that
  zeroes out a majority of days — the model and metrics must handle
  genuine zero-demand series, not just low ones.
- **Anomalies/outliers**: ~0.25% of rows get a 3x-6x spike, another ~0.25%
  get a near-total drop — rare, deliberate outliers, informationally
  flagged by `app.forecasting.quality.check_extreme_outliers` but never
  gating (removing them would misrepresent a demand series that genuinely
  has occasional shocks).
- **Holidays**: a small, generic, publicly-known fixed calendar (New Year's
  Day, July 4th, Christmas, the fourth Thursday of November) — computed
  from the calendar itself, not sourced from any licensed dataset — gets a
  1.5x demand multiplier.

## Feature engineering (`app.forecasting.features`)

- **Calendar**: `day_of_week`, `week_of_year`, `month`, `is_weekend` —
  derived only from the row's own `date`.
- **Same-day planned/known inputs**: `price`, `promo_flag`, `is_holiday` —
  legitimate features because they represent information knowable *in
  advance* (a pricing/promo/holiday calendar), not anything derived from
  that day's realized demand.
- **Lag features**: `lag_1, lag_7, lag_14, lag_28` (configurable via
  `FORECAST_LAG_DAYS`) — `units_demanded` shifted forward within each
  `(sku, location_id)` group.
- **Rolling features**: `rolling_mean_{7,14,28}`, `rolling_std_{7,14,28}`
  (configurable via `FORECAST_ROLLING_WINDOWS`) — computed on `shift(1)`
  first, so a window's own current-day value is never part of its own
  statistic.

## Leakage prevention

Three independent safeguards, not just a docstring claim:

1. `add_lag_features` raises `ValueError` for any configured lag `< 1`
   (`LEAKAGE_SAFE_LAG_MIN`) — a lag of 0 would just be the target itself.
2. `add_rolling_features` always computes on `shift(1)`, never the raw
   target column, so no window ever includes its own current row.
3. `app.forecasting.features.assert_no_leakage` /
   `app.forecasting.quality.check_feature_leakage_safeguard` statically
   reject `units_demanded`, `units_fulfilled`, `lost_sales`,
   `stock_available`, and `is_stockout` from ever appearing in the declared
   feature list — `app.forecasting.dataset.prepare_dataset` runs this check
   and raises before a model can ever be trained on a leaking column.

All three are exercised directly in `tests/forecasting/test_features.py`
and `tests/forecasting/test_quality.py` (e.g.
`test_rolling_mean_excludes_current_row` plants a huge single-day outlier
and asserts it is absent from that same day's own rolling mean).

## Baseline model (section C)

**Seasonal-naive** (`app.forecasting.baseline`): predicts a day's demand as
the same weekday's demand exactly one week earlier (`lag_7`), falling back
to the trailing-7-day mean (`rolling_mean_7`) when `lag_7` isn't available
yet (a series' first week), and to 0 only if neither exists. This is the
literal "same period last cycle" baseline ADR 0006 committed to — not
weakened to make the secondary model look better.

## Secondary model (section D)

**`sklearn.ensemble.HistGradientBoostingRegressor`**
(`app.forecasting.secondary_model`), trained with a fixed
`random_state` (`FORECAST_MODEL_RANDOM_STATE`, default 42) for
determinism. Chosen per ADR 0006 (pure-Python-wheel scikit-learn, no
Stan/compiled-library toolchain) and specifically over
`GradientBoostingRegressor`/`RandomForestRegressor` for native missing-value
support: the earliest `max(lag_days)` rows of any SKU x location series are
legitimately `NaN` (the lag history doesn't exist yet), which
`HistGradientBoostingRegressor` handles natively without an imputer step.

## Chronological validation (section E)

Never a random shuffle split — always time-ordered
(`app.forecasting.splits`):

- **`single_split`**: a fixed cutoff date (`training_cutoff_date`, or — if
  unset — derived as `max(date) - 2 * forecast_horizon_days`) splits
  everything up to and including the cutoff into training, and exactly one
  `forecast_horizon_days`-long block immediately after it into validation.
  Raises rather than silently truncating if the training window is shorter
  than `min_history_days`, or if the validation window has no rows at all.
- **`walk_forward_folds`**: expanding-window rolling-origin folds — each
  successive cutoff moves forward by one horizon, so every fold's training
  window strictly contains the previous fold's, and no fold's validation
  dates overlap another's. Folds that don't have enough history are skipped
  rather than raised.
- **Forecast horizon**: `FORECAST_FORECAST_HORIZON_DAYS` (default 14).
- **Minimum history**: `FORECAST_MIN_HISTORY_DAYS` (default 56).
- **Aggregation**: daily grain; metrics are reported overall and broken out
  by SKU, location, and horizon-day (see Metrics below).

## Metrics (section F)

Computed from real predictions (`app.forecasting.metrics`), never
fabricated:

- **MAE**, **RMSE** — standard.
- **WAPE** (weighted absolute percentage error =
  `sum(|error|) / sum(|actual|)`) — the scale-aware business metric. Chosen
  over plain MAPE because this dataset has genuinely intermittent/
  zero-demand series (the synthetic generator's intermittent SKUs); MAPE's
  per-row division by a zero actual is undefined, while WAPE aggregates the
  numerator and denominator across the whole group first, so one zero-actual
  row never divides by zero on its own. **MAPE is not reported at all** —
  the phase spec says to include it "only when zero-demand handling is
  explicitly correct and documented," and this dataset's demand hits exact
  zero often enough that no per-row handling is "explicitly correct" here.

Metrics are broken out overall, by SKU, by location, and by horizon-day
(`app.forecasting.evaluate.evaluate_model`).

## Model comparison and champion selection (section F)

`app.forecasting.select.select_champion` compares the baseline and
secondary model's overall validation-set value of `FORECAST_CHAMPION_METRIC`
(default `wape`) and picks whichever is strictly lower. An exact tie (the
secondary model doesn't measurably beat the baseline) keeps the baseline —
a secondary model that doesn't earn its added complexity isn't crowned
champion by default. The comparison and the reason are both written to the
`selection` output as plain measured numbers; whichever model actually wins
is reported honestly, including if the secondary model loses to the
baseline on this run's synthetic data.

## Forecast output (section G)

`app.forecasting.forecast.generate_future_forecast` produces one row per
`(forecast_date, sku, location_id)` for `forecast_horizon_days` beyond the
end of known history:

| Field | Meaning |
|---|---|
| `forecast_generated_at` | when this forecast run executed |
| `forecast_date` | the date being predicted |
| `horizon` | 1..`forecast_horizon_days`, days-ahead of the training cutoff |
| `sku`, `location_id` | grain |
| `predicted_units` | the model's point prediction (never negative) |
| `model_name`, `model_version` | which model produced this row |
| `run_id` | ties this forecast back to its training/evaluation/selection run |
| `training_cutoff` | the cutoff date the champion model was trained through |

**No `lower_bound`/`upper_bound`**: neither the seasonal-naive baseline nor
`HistGradientBoostingRegressor`'s point prediction supports a real
confidence interval without extra machinery (e.g. quantile regression) this
phase doesn't add — the spec explicitly says not to invent one, so none is
fabricated.

**Recursive multi-step rollout**: the model is trained as a one-step-ahead
(next calendar day) predictor. To project multiple days beyond the end of
known history, each day's prediction is appended to the working series as
if it were realized demand, so the next day's lag/rolling features have
something to look back on
(`tests/forecasting/test_forecast.py::
test_generate_future_forecast_recursion_feeds_predictions_forward` proves
this directly with a probe model). This is a standard, disclosed limitation
of a lag/rolling-feature model without a native multi-horizon head —
prediction error can compound step-to-step (see Limitations).

Future-dated rows' `price` carries the SKU's last known price forward;
`promo_flag` is assumed 0 (no promo calendar exists beyond history);
`is_holiday` is computed from the same deterministic calendar formula used
during generation. These are documented assumptions about *unknown future
inputs*, not claims about real plans.

## Storage layout

Everything lives under `s3a://<bucket>/forecasting/` in MinIO
(`app.config.Settings.forecasting_path`, `app.forecasting.paths`) — a new
top-level prefix alongside `bronze`/`silver`/`gold`/`dq-reports`/
`checkpoints`, added to `infra/docker/minio/create-buckets.sh`, not nested
under `gold` since it isn't a Spark streaming aggregation like the other
ten Gold datasets:

```
forecasting/
  synthetic_history/history.parquet     # singleton input, overwritten each run
  dataset/features.parquet              # singleton input, overwritten each run
  forecasts/
    latest.parquet                      # convenience copy of the most recent run
    run_id=<id>/forecast.parquet        # versioned, for lineage
  evaluation/
    latest.json
    run_id=<id>/metrics.json
  selection/
    latest.json
    run_id=<id>/selection.json
```

Trained model artifacts are **persisted locally** (`config.artifact_dir`,
default `forecasting_artifacts/` under the service's own working
directory), per the spec's section H — a joblib binary plus a JSON metadata
file (training timestamp, feature list, training/evaluation range, training
row count, random state, run ID) at
`forecasting_artifacts/<model_name>/<run_id>/{model.joblib,metadata.json}`.
Gitignored; never committed.

## CLI commands

`python -m app.forecasting.cli <subcommand>` (from
`services/data-platform/`, or via the `make forecast-*` targets below):

| Subcommand | Purpose |
|---|---|
| `generate-history` | write deterministic synthetic history |
| `prepare` | build the feature-engineered dataset (gated by data-quality checks) |
| `train-baseline` | train + save the seasonal-naive baseline |
| `train-secondary` | train + save the `HistGradientBoostingRegressor` |
| `evaluate` | score both saved models against the chronological validation split |
| `select` | pick the champion from measured evaluation metrics |
| `forecast` | generate the future forecast from the champion model |
| `validate` | run data-quality checks against the prepared dataset (exit 1 on failure) |
| `inspect {forecast,metrics,selection,dataset}` | print a human-readable summary of an artifact |
| `run` | the full pipeline above, end to end, in one process |

Every subcommand accepts path overrides (`--input`/`--output`/etc.) —
defaulting to the MinIO paths above when omitted — which is what lets
`tests/forecasting/` and `scripts/forecast_smoke_test.sh` redirect every
read/write to a local scratch directory with no live MinIO connection.

## Makefile targets

`forecast-generate-data`, `forecast-prepare`, `forecast-train-baseline`,
`forecast-train-model`, `forecast-evaluate`, `forecast-select`,
`forecast-run`, `forecast-inspect`, `forecast-test`, `forecast-smoke`,
`forecast-clean-safe`, `forecast-validate` (all listed in `make help`).
`forecast-clean-safe` only removes `forecasting_artifacts/` and the local
smoke-test scratch dir — never MinIO data, Docker volumes, checkpoints, or
unrelated Bronze/Silver/Gold data.

## Local demonstration

```bash
make forecast-run                 # full pipeline against real MinIO
make forecast-inspect ARGS="forecast"
make forecast-inspect ARGS="metrics"
make forecast-smoke                # small deterministic end-to-end run, local scratch dir only
```

## Test strategy (section M)

- **Unit tests** (`tests/forecasting/test_{synthetic,features,quality,
  splits,baseline,secondary_model,metrics,select,artifacts,io}.py`):
  synthetic-data reproducibility and shape, calendar/lag/rolling feature
  correctness (including grain-grouping and leakage), every data-quality
  check, chronological split/walk-forward correctness, baseline formula and
  fallbacks, secondary-model determinism/missing-value handling, metric
  formulas (including the WAPE zero-handling case), champion-selection
  logic (including the configured-metric and tie cases), and artifact
  save/load roundtrips.
- **Pipeline tests** (`test_dataset.py`, `test_evaluate.py`,
  `test_forecast.py`, `test_cli.py`): dataset preparation (including its
  data-quality gate), end-to-end evaluation against a chronological split,
  future-forecast generation (schema, row count, and the recursive-rollout
  behavior), and a full `cli.cmd_run` pipeline run against a
  monkeypatched, tmp-path-only Settings/ForecastSettings pair.
- **Smoke test** (`scripts/forecast_smoke_test.sh`, `make forecast-smoke`):
  every CLI subcommand run in sequence against a small deterministic
  config, redirected to a host-bind-mounted local scratch directory —
  verifies the expected files, row counts, and schema actually land,
  without needing a live Redpanda/MinIO/Postgres stack.

None of the forecasting tests need network access, Redpanda, or MinIO —
same "no live Kafka/MinIO needed for its own suite" contract
`test-data-platform` already has (they're plain pandas/scikit-learn
functions, or CLI calls wired to `tmp_path`).

## Observability

Structured logging (module logger `data_platform.forecasting`) at each
pipeline stage: dataset preparation (row/series/feature counts), evaluation
(overall metrics per model), and champion selection are all logged. This
phase does not add its own Prometheus metrics — it is a batch job with no
long-running process to scrape (unlike `app.bronze`/`app.silver`/
`app.gold.runner`'s streaming queries), and each run's own JSON
evaluation/selection output already captures the numbers a metrics scrape
would otherwise surface.

## Limitations

- **Forecast quality is bounded by synthetic data's realism** — this is
  explicitly a demonstration pipeline over a documented synthetic
  generator, not a production forecast tuned against real sales history.
- **Recursive multi-step rollout can compound error** — each future day's
  prediction becomes the next day's "actual" for lag/rolling features;
  errors do not reset between horizon steps. A native multi-horizon model
  (e.g. one model per horizon, or a sequence model) would avoid this but
  is out of scope for this phase's baseline-first mandate.
- **No confidence intervals** — neither model here supports one without
  additional machinery this phase doesn't add (see Forecast output).
- **No real location attribution in the underlying event catalog** — the
  synthetic location dimension does not correspond to any real
  `fulfillment_nodes` row; a future phase wiring this to real data would
  need `order.created`'s item payload extended with a location hint first
  (see `app.gold.queries`'s module docstring).
- **Prophet/XGBoost remain a documented, not-taken upgrade path** — per
  ADR 0006, kept out for dependency-weight reasons, not evaluated here.

## Troubleshooting

- **`DataQualityError` from `prepare`**: a gating check in
  `app.forecasting.quality` failed — the error message lists which
  check(s); re-run `validate` against the same input for full
  per-check detail.
- **`ValueError: training period ... is shorter than min_history_days`**:
  the configured `history_start_date`/`history_end_date`/
  `training_cutoff_date`/`min_history_days` don't leave enough training
  history — widen the history range or lower `min_history_days`.
- **`FileNotFoundError: no saved <model> artifact for run_id=...`**: run
  `train-baseline`/`train-secondary` for that exact `run_id` before
  `evaluate`/`forecast` — artifacts are namespaced by `(model_name, run_id)`
  under `config.artifact_dir`.
- **`ValueError: seasonal-naive baseline requires a 'lag_7' feature
  column`**: `FORECAST_LAG_DAYS` was configured without `7` — the baseline
  needs `lag_7` for its "same weekday last week" prediction.

## Acceptance criteria

See the phase-6 task's acceptance-criteria list (dataset, deterministic
synthetic history, baseline, secondary model, chronological validation, no
random split, leakage safeguards tested, MAE/RMSE/WAPE from real
predictions, honest comparison, measured champion selection, future
forecasts, inspectable outputs, local model artifacts, data-quality checks,
working CLI/Makefile targets, passing deterministic/smoke tests, and a
clean `make ci`) — all satisfied per the validation run recorded in
`TEST_RESULTS.md` and this phase's close-out in `PROJECT_STATUS.md`.

## Zero-cost compliance

Every dependency added (`pandas`, `numpy`, `scikit-learn`, `joblib`) is a
pure-Python-wheel, pip-installable, open-source library with no compiled
system toolchain and no license cost — pinned in
`services/data-platform/requirements.txt`, built into the existing
`spark-gold`-family Docker image (no new image, no new container). No AWS,
no paid API, no paid hosted notebook, no external licensed dataset. All
output lives in the same local MinIO/Docker Compose stack every other phase
already uses.
