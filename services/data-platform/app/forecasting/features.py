"""Feature engineering for the forecasting dataset — grain: SKU x location x
calendar date (docs/phase-6-demand-forecasting.md). Every feature here is
computed strictly from information available *before* the row's own
realized demand: calendar/price/promo/holiday features derive only from the
date/plan itself (known in advance, not derived from the target), and lag/
rolling features are always taken from `shift(1)` onward — never the
current or a future row's `units_demanded`. See `assert_no_leakage` and
`tests/forecasting/test_features.py`.
"""

from __future__ import annotations

import pandas as pd

from app.forecasting.config import ForecastSettings

TARGET_COL = "units_demanded"
GRAIN_COLS = ["date", "sku", "location_id"]

# Columns that are only knowable *because* the target already happened
# (fulfillment is capped by on-hand stock, which is itself a function of
# that day's demand) — these must never be used as model features, however
# tempting they look, or the model would be trained on information it can
# never have at real forecast time.
_TARGET_DERIVED_COLS = {
    TARGET_COL,
    "units_fulfilled",
    "lost_sales",
    "stock_available",
    "is_stockout",
}

# A lag/rolling feature computed from `shift(k)` for k < 1 would include the
# current row's own target — the one leakage mode this module must never
# introduce.
LEAKAGE_SAFE_LAG_MIN = 1


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["day_of_week"] = out["date"].dt.dayofweek
    out["week_of_year"] = out["date"].dt.isocalendar().week.astype(int)
    out["month"] = out["date"].dt.month
    out["is_weekend"] = (out["day_of_week"] >= 5).astype(int)
    return out


def add_lag_features(df: pd.DataFrame, lag_days: list[int]) -> pd.DataFrame:
    out = df.sort_values(GRAIN_COLS).reset_index(drop=True)
    grouped = out.groupby(["sku", "location_id"])[TARGET_COL]
    for lag in lag_days:
        if lag < LEAKAGE_SAFE_LAG_MIN:
            raise ValueError(f"lag {lag} would leak the current or a future row's target")
        out[f"lag_{lag}"] = grouped.shift(lag)
    return out


def add_rolling_features(df: pd.DataFrame, rolling_windows: list[int]) -> pd.DataFrame:
    """Rolling mean/std computed on `shift(1)` first, so a window's own
    current-day value is never part of its own rolling statistic."""
    out = df.sort_values(GRAIN_COLS).reset_index(drop=True)
    out["_shifted_target"] = out.groupby(["sku", "location_id"])[TARGET_COL].shift(1)
    for window in rolling_windows:
        grouped_shifted = out.groupby(["sku", "location_id"])["_shifted_target"]
        min_periods = max(1, window // 2)
        out[f"rolling_mean_{window}"] = grouped_shifted.transform(
            lambda s, w=window, mp=min_periods: s.rolling(w, min_periods=mp).mean()
        )
        out[f"rolling_std_{window}"] = grouped_shifted.transform(
            lambda s, w=window, mp=min_periods: s.rolling(w, min_periods=mp).std()
        )
    return out.drop(columns=["_shifted_target"])


def build_feature_frame(df: pd.DataFrame, config: ForecastSettings) -> pd.DataFrame:
    out = add_calendar_features(df)
    out = add_lag_features(out, config.lag_days)
    out = add_rolling_features(out, config.rolling_windows)
    return out


def feature_columns(config: ForecastSettings) -> list[str]:
    """Same-day `price`/`promo_flag`/`is_holiday` are legitimate features —
    they represent planned/known-in-advance information (a pricing and
    promo calendar, a holiday calendar), not anything derived from that
    day's realized demand. `units_fulfilled`/`stock_available`/etc. are
    deliberately excluded — see `_TARGET_DERIVED_COLS`."""
    cols = [
        "day_of_week",
        "week_of_year",
        "month",
        "is_weekend",
        "price",
        "promo_flag",
        "is_holiday",
    ]
    cols += [f"lag_{lag}" for lag in config.lag_days]
    for window in config.rolling_windows:
        cols += [f"rolling_mean_{window}", f"rolling_std_{window}"]
    return cols


def assert_no_leakage(feature_cols: list[str]) -> None:
    """Static safeguard: no declared feature name may be the target itself
    or a target-derived column."""
    leaked = [c for c in feature_cols if c in _TARGET_DERIVED_COLS]
    if leaked:
        raise AssertionError(f"leakage-unsafe columns in feature set: {leaked}")
