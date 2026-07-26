from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.config import ForecastSettings
from app.forecasting.splits import resolve_training_cutoff, single_split, walk_forward_folds


def _linear_df(days: int, n_series: int = 1) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    rows = []
    for i in range(n_series):
        for d in dates:
            rows.append(
                {"date": d, "sku": f"SKU-{i:04d}", "location_id": "LOC-01", "units_demanded": 5}
            )
    return pd.DataFrame(rows)


def test_resolve_training_cutoff_uses_explicit_value_when_set():
    config = ForecastSettings(training_cutoff_date="2025-01-15")
    df = _linear_df(60)
    assert resolve_training_cutoff(df, config) == "2025-01-15"


def test_resolve_training_cutoff_derives_from_data_when_unset():
    config = ForecastSettings(training_cutoff_date="", forecast_horizon_days=7)
    df = _linear_df(60)
    cutoff = resolve_training_cutoff(df, config)
    max_date = pd.to_datetime(df["date"]).max()
    assert pd.Timestamp(cutoff) == max_date - pd.Timedelta(days=14)


def test_single_split_produces_non_overlapping_train_valid():
    config = ForecastSettings(training_cutoff_date="", forecast_horizon_days=7, min_history_days=10)
    df = _linear_df(60)
    train, valid, split = single_split(df, config)

    train_dates = pd.to_datetime(train["date"])
    valid_dates = pd.to_datetime(valid["date"])
    assert train_dates.max() < valid_dates.min()
    assert valid_dates.max() <= pd.Timestamp(split.valid_end)
    assert len(valid_dates.unique()) == config.forecast_horizon_days


def test_single_split_raises_when_training_window_too_short():
    config = ForecastSettings(training_cutoff_date="2025-01-05", min_history_days=30)
    df = _linear_df(60)
    with pytest.raises(ValueError, match="min_history_days"):
        single_split(df, config)


def test_single_split_raises_when_no_validation_rows():
    config = ForecastSettings(
        training_cutoff_date="2025-03-01", forecast_horizon_days=7, min_history_days=10
    )
    df = _linear_df(60)  # data ends 2025-03-01, so cutoff has no rows after it
    with pytest.raises(ValueError, match="no rows after cutoff"):
        single_split(df, config)


def test_walk_forward_folds_are_expanding_and_non_overlapping():
    config = ForecastSettings(training_cutoff_date="", forecast_horizon_days=7, min_history_days=10)
    df = _linear_df(90)
    folds = walk_forward_folds(df, config, n_folds=3)

    assert len(folds) == 3
    # Deliberately not `zip(..., strict=True)` — this is a pairwise
    # (i, i+1) walk over one list, so the two slices are always one
    # element apart in length by design.
    for earlier, later in zip(folds, folds[1:], strict=False):
        assert pd.Timestamp(earlier.train_end) < pd.Timestamp(later.train_end)
        assert pd.Timestamp(earlier.valid_end) <= pd.Timestamp(later.valid_start)


def test_walk_forward_folds_skips_folds_below_min_history():
    config = ForecastSettings(training_cutoff_date="", forecast_horizon_days=7, min_history_days=80)
    df = _linear_df(90)
    folds = walk_forward_folds(df, config, n_folds=5)
    # With only 90 days and an 80-day minimum, most candidate folds don't
    # have enough history — the function must skip them, not raise.
    assert len(folds) < 5
