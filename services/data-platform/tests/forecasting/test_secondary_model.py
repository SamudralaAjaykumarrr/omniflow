from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.forecasting.secondary_model import SecondaryModel


def _train_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.uniform(0, 10, n)
    x2 = rng.uniform(0, 5, n)
    y = 2 * x1 + 3 * x2 + rng.normal(0, 0.1, n)
    return pd.DataFrame({"x1": x1, "x2": x2, "units_demanded": y})


def test_fit_predict_returns_series_aligned_to_input_index():
    df = _train_df()
    model = SecondaryModel(feature_columns=["x1", "x2"], random_state=42)
    model.fit(df, "units_demanded")
    predictions = model.predict(df)
    assert list(predictions.index) == list(df.index)
    assert len(predictions) == len(df)


def test_predictions_never_negative():
    df = _train_df()
    model = SecondaryModel(feature_columns=["x1", "x2"], random_state=42)
    model.fit(df, "units_demanded")
    predictions = model.predict(df)
    assert (predictions >= 0).all()


def test_deterministic_given_same_random_state():
    df = _train_df()
    model_a = SecondaryModel(feature_columns=["x1", "x2"], random_state=42).fit(
        df, "units_demanded"
    )
    model_b = SecondaryModel(feature_columns=["x1", "x2"], random_state=42).fit(
        df, "units_demanded"
    )
    pd.testing.assert_series_equal(model_a.predict(df), model_b.predict(df))


def test_learns_a_reasonable_fit_on_a_simple_linear_signal():
    df = _train_df(n=500)
    model = SecondaryModel(feature_columns=["x1", "x2"], random_state=42).fit(df, "units_demanded")
    predictions = model.predict(df)
    mae = float(np.mean(np.abs(predictions.to_numpy() - df["units_demanded"].to_numpy())))
    assert mae < 2.0  # loose bound: just confirms it actually learned something


def test_predict_before_fit_raises():
    model = SecondaryModel(feature_columns=["x1"])
    with pytest.raises(RuntimeError, match="fit"):
        model.predict(pd.DataFrame({"x1": [1.0]}))


def test_handles_missing_feature_values_natively():
    df = _train_df()
    df.loc[0, "x1"] = np.nan
    model = SecondaryModel(feature_columns=["x1", "x2"], random_state=42)
    model.fit(df, "units_demanded")  # must not raise on NaN features
    predictions = model.predict(df)
    assert len(predictions) == len(df)
