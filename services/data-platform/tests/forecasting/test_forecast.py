from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.baseline import SeasonalNaiveModel
from app.forecasting.forecast import generate_future_forecast
from app.forecasting.synthetic import generate_synthetic_history


def test_generate_future_forecast_shape_and_schema(small_config):
    history = generate_synthetic_history(small_config)
    model = SeasonalNaiveModel().fit(history, "units_demanded")

    forecast_df = generate_future_forecast(
        history, model, "seasonal_naive", "v1", small_config, training_cutoff="2025-03-31"
    )

    expected_rows = (
        small_config.forecast_horizon_days * small_config.num_skus * small_config.num_locations
    )
    assert len(forecast_df) == expected_rows

    required_cols = {
        "forecast_generated_at",
        "forecast_date",
        "horizon",
        "sku",
        "location_id",
        "predicted_units",
        "model_name",
        "model_version",
        "run_id",
        "training_cutoff",
    }
    assert required_cols.issubset(forecast_df.columns)
    assert (forecast_df["predicted_units"] >= 0).all()
    assert forecast_df["horizon"].min() == 1
    assert forecast_df["horizon"].max() == small_config.forecast_horizon_days


def test_generate_future_forecast_dates_are_sequential_after_history(small_config):
    history = generate_synthetic_history(small_config)
    model = SeasonalNaiveModel().fit(history, "units_demanded")
    forecast_df = generate_future_forecast(
        history, model, "seasonal_naive", "v1", small_config, training_cutoff="2025-04-30"
    )
    last_history_date = pd.to_datetime(history["date"]).max()
    forecast_dates = sorted(pd.to_datetime(forecast_df["forecast_date"]).unique())
    assert forecast_dates[0] == last_history_date + pd.Timedelta(days=1)
    assert forecast_dates[-1] == last_history_date + pd.Timedelta(
        days=small_config.forecast_horizon_days
    )


class _Lag1Model:
    """Predicts exactly `lag_1` (falling back to 0) — a probe model whose
    output is only correct if the recursive rollout actually appended the
    previous step's prediction as that series' new "actual" before
    computing the next step's features."""

    def predict(self, df: pd.DataFrame) -> pd.Series:
        return df["lag_1"].fillna(0.0)


def test_generate_future_forecast_recursion_feeds_predictions_forward(small_config):
    history = generate_synthetic_history(small_config)
    model = _Lag1Model()
    forecast_df = generate_future_forecast(
        history, model, "lag1_probe", "v1", small_config, training_cutoff="2025-04-30"
    )
    one_series = forecast_df[
        (forecast_df["sku"] == "SKU-0001") & (forecast_df["location_id"] == "LOC-01")
    ].sort_values("horizon")

    last_history_value = float(
        history[(history["sku"] == "SKU-0001") & (history["location_id"] == "LOC-01")]
        .sort_values("date")["units_demanded"]
        .iloc[-1]
    )
    predicted = one_series["predicted_units"].tolist()
    # Step 1's lag_1 is the last real history value; step 2's lag_1 must be
    # step 1's *prediction* (not the same history value again, and not 0).
    assert predicted[0] == pytest.approx(max(0.0, last_history_value))
    assert predicted[1] == pytest.approx(predicted[0])
