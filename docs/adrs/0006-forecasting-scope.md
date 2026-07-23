# ADR 0006: Demand Forecasting — Baseline First, Lightweight Secondary Model

## Status
Accepted

## Context
The spec explicitly marks forecasting as secondary to the distributed-systems
and data-platform work, and requires a baseline before any "real" model, an
honest metric comparison, and a rule against fabricated performance numbers.
Prophet and XGBoost are both reasonable choices but pull in heavier
dependencies (Prophet: `cmdstanpy`/Stan toolchain; XGBoost: a compiled
library) for a component the spec itself says must not destabilize the core
system.

## Decision
Baseline: seasonal-naive / moving-average forecast per SKU/location (predict
next period ≈ same period last cycle, or a rolling window mean — whichever is
implemented is documented plainly, no dressing it up). Secondary model:
scikit-learn (e.g. gradient-boosted trees) or `statsmodels` (e.g. ETS/ARIMA),
chosen for being pure-Python-wheel installable with no extra system toolchain.
Both are trained/evaluated with a time-aware split (train on earlier periods,
validate on later ones — never a random shuffle split, which would leak
future information). MAE and RMSE are reported for both, computed from an
actual run against the synthetic historical dataset, and the secondary
model's metrics are only claimed as "better" if the numbers actually say so.

## Consequences
- The forecasting job is a standalone batch process reading Gold
  (`product_demand_by_window`) and writing a `forecast` dataset; it has no
  callers on the order/inventory/fulfillment critical path, so it cannot
  block or destabilize order processing if it fails or is slow.
- Prophet/XGBoost remain a documented optional upgrade path in
  `docs/interview-guide.md` ("what I would improve"), not a promise the
  project fails to keep.
- Forecast quality is bounded by synthetic data's realism — explicitly
  documented as a limitation, not glossed over.

## Alternatives considered
- **Prophet as the primary secondary model**: attractive for its holiday/
  seasonality handling, but its native dependency toolchain is a heavier,
  slower Docker build for a component the spec says should not destabilize
  the core system; kept as a named future upgrade instead.
- **XGBoost**: strong general-purpose choice, same dependency-weight
  reasoning; also named as a future upgrade.
- **Skip a secondary model, ship only the baseline**: rejected — the spec
  asks for a real comparison, and a comparison needs two real numbers.
