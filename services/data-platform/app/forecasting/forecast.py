"""Future forecast generation (section G) — recursive multi-step rollout.

The model is trained as a one-step-ahead (next calendar day) predictor: to
project `forecast_horizon_days` beyond the end of known history, each day's
prediction is appended to the working series as if it were realized demand,
so the next day's lag/rolling features have something to look back on. This
is a standard, disclosed limitation of a pure lag/rolling-feature model
without a native multi-horizon head — errors can compound step-to-step; see
docs/phase-6-demand-forecasting.md 'Limitations'. No confidence interval is
computed here: neither the seasonal-naive baseline nor
`HistGradientBoostingRegressor`'s point prediction supports one without
extra machinery (e.g. quantile regression) this phase doesn't add, so
`lower_bound`/`upper_bound` are simply not fabricated (section G).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

import pandas as pd

from app.forecasting.config import ForecastSettings
from app.forecasting.features import build_feature_frame
from app.forecasting.synthetic import synthetic_holidays


class _PredictModel(Protocol):
    def predict(self, df: pd.DataFrame) -> pd.Series: ...


def _future_row(
    date: pd.Timestamp, sku: str, location_id: str, last_price: float, is_holiday: bool
) -> dict:
    return {
        "date": date,
        "sku": sku,
        "location_id": location_id,
        "units_demanded": float("nan"),
        # Planned/assumed exogenous inputs beyond known history — carry the
        # SKU's last known price forward, and assume no promo is planned
        # (no promo calendar exists beyond the synthetic history's end);
        # both are documented assumptions, not claims about real plans.
        "price": last_price,
        "promo_flag": 0,
        "is_holiday": int(is_holiday),
    }


def generate_future_forecast(
    history_df: pd.DataFrame,
    model: _PredictModel,
    model_name: str,
    model_version: str,
    config: ForecastSettings,
    *,
    training_cutoff: str,
) -> pd.DataFrame:
    working = history_df.copy()
    working["date"] = pd.to_datetime(working["date"])
    last_date = working["date"].max()
    horizon_dates = [
        last_date + pd.Timedelta(days=i) for i in range(1, config.forecast_horizon_days + 1)
    ]
    holiday_dates = set(synthetic_holidays(pd.DatetimeIndex([last_date, horizon_dates[-1]])))

    last_rows = (
        working.sort_values("date")
        .groupby(["sku", "location_id"])
        .tail(1)
        .set_index(["sku", "location_id"])
    )

    generated_at = datetime.now(UTC).isoformat()
    run_id = uuid.uuid4().hex[:12]
    forecast_rows: list[dict] = []

    for step, target_date in enumerate(horizon_dates, start=1):
        is_holiday = target_date.normalize() in holiday_dates
        future_rows = [
            _future_row(
                target_date, sku, loc, float(last_rows.loc[(sku, loc), "price"]), is_holiday
            )
            for sku, loc in last_rows.index
        ]
        future_df = pd.DataFrame(future_rows)

        combined = pd.concat([working, future_df], ignore_index=True)
        featured = build_feature_frame(combined, config)
        current = featured[featured["date"] == target_date].reset_index(drop=True)

        predictions = model.predict(current)

        # Keyed by (sku, location_id) rather than positional order: `current`
        # is sorted by `build_feature_frame`'s internal GRAIN_COLS sort,
        # while `future_df` is ordered by `last_rows.index` — two
        # independently derived orderings that are not guaranteed to match
        # row-for-row, so lining them up by an explicit key (not position)
        # is what actually keeps a prediction attached to the right series.
        predicted_by_key: dict[tuple[str, str], float] = {}
        for row, predicted in zip(current.itertuples(index=False), predictions, strict=True):
            predicted_units = max(0.0, float(predicted))
            predicted_by_key[(row.sku, row.location_id)] = predicted_units
            forecast_rows.append(
                {
                    "forecast_generated_at": generated_at,
                    "forecast_date": target_date.date().isoformat(),
                    "horizon": step,
                    "sku": row.sku,
                    "location_id": row.location_id,
                    "predicted_units": predicted_units,
                    "model_name": model_name,
                    "model_version": model_version,
                    "run_id": run_id,
                    "training_cutoff": training_cutoff,
                }
            )

        # Feed this step's predictions back in as the working series' new
        # "actuals" so the next step's lag/rolling features have history.
        future_df = future_df.copy()
        future_df["units_demanded"] = [
            predicted_by_key[(sku, loc)]
            for sku, loc in zip(future_df["sku"], future_df["location_id"], strict=True)
        ]
        working = pd.concat([working, future_df], ignore_index=True)

    return pd.DataFrame(forecast_rows)
