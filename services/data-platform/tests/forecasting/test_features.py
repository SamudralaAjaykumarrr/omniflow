from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.features import (
    add_calendar_features,
    add_lag_features,
    add_rolling_features,
    assert_no_leakage,
    build_feature_frame,
    feature_columns,
)


def _series_df(values: list[int]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "sku": "SKU-0001",
            "location_id": "LOC-01",
            "units_demanded": values,
            "price": 10.0,
            "promo_flag": 0,
            "is_holiday": 0,
        }
    )


def test_calendar_features_derive_only_from_date():
    df = _series_df([1, 2, 3, 4, 5, 6, 7, 8])
    out = add_calendar_features(df)
    assert list(out["day_of_week"]) == [pd.Timestamp(d).dayofweek for d in out["date"]]
    assert (out["is_weekend"] == (out["day_of_week"] >= 5)).all()


def test_lag_1_is_exactly_the_previous_row():
    df = _series_df([10, 20, 30, 40, 50])
    out = add_lag_features(df, [1])
    assert pd.isna(out["lag_1"].iloc[0])
    assert out["lag_1"].iloc[1] == 10
    assert out["lag_1"].iloc[4] == 40


def test_lag_7_looks_back_seven_rows():
    values = list(range(1, 16))
    df = _series_df(values)
    out = add_lag_features(df, [7])
    assert out["lag_7"].iloc[7] == values[0]
    assert out["lag_7"].iloc[14] == values[7]
    assert out["lag_7"].iloc[:7].isna().all()


def test_lag_below_one_raises():
    df = _series_df([1, 2, 3])
    with pytest.raises(ValueError, match="leak"):
        add_lag_features(df, [0])


def test_rolling_mean_excludes_current_row():
    """A single, huge outlier on day N must not appear in day N's own
    rolling_mean_3 — only in the *following* days' windows."""
    values = [10, 10, 10, 10_000, 10, 10, 10, 10]
    df = _series_df(values)
    out = add_rolling_features(df, [3])
    outlier_idx = 3
    assert out["rolling_mean_3"].iloc[outlier_idx] == pytest.approx(10.0)
    # The window immediately after the outlier must include it.
    assert out["rolling_mean_3"].iloc[outlier_idx + 1] > 100


def test_rolling_features_respect_grain_grouping():
    """Two different SKUs' series must never leak into each other's
    rolling/lag windows."""
    dates = pd.date_range("2025-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "sku": ["SKU-A"] * 5 + ["SKU-B"] * 5,
            "location_id": "LOC-01",
            "units_demanded": [1, 1, 1, 1, 1] + [100, 100, 100, 100, 100],
            "price": 10.0,
            "promo_flag": 0,
            "is_holiday": 0,
        }
    )
    out = add_lag_features(df, [1])
    sku_a = out[out["sku"] == "SKU-A"]
    sku_b = out[out["sku"] == "SKU-B"]
    assert sku_a["lag_1"].dropna().eq(1).all()
    assert sku_b["lag_1"].dropna().eq(100).all()


def test_feature_columns_pass_leakage_safeguard(small_config):
    assert_no_leakage(feature_columns(small_config))  # must not raise


def test_assert_no_leakage_raises_when_target_present():
    with pytest.raises(AssertionError):
        assert_no_leakage(["lag_7", "units_demanded"])


def test_assert_no_leakage_raises_for_target_derived_columns():
    with pytest.raises(AssertionError):
        assert_no_leakage(["price", "stock_available"])


def test_build_feature_frame_produces_declared_columns(small_config):
    df = _series_df(list(range(1, 61)))
    out = build_feature_frame(df, small_config)
    for col in feature_columns(small_config):
        assert col in out.columns
