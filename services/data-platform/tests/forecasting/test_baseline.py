from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.baseline import SeasonalNaiveModel, predict_seasonal_naive


def test_predict_uses_lag_7_when_present():
    df = pd.DataFrame({"lag_7": [5.0, 10.0], "rolling_mean_7": [1.0, 1.0]})
    predictions = predict_seasonal_naive(df)
    assert predictions.tolist() == [5.0, 10.0]


def test_predict_falls_back_to_rolling_mean_when_lag_7_missing():
    df = pd.DataFrame({"lag_7": [None, 10.0], "rolling_mean_7": [3.0, 1.0]})
    predictions = predict_seasonal_naive(df)
    assert predictions.tolist() == [3.0, 10.0]


def test_predict_falls_back_to_zero_when_nothing_available():
    df = pd.DataFrame({"lag_7": [None]})
    predictions = predict_seasonal_naive(df)
    assert predictions.tolist() == [0.0]


def test_predict_never_returns_negative():
    df = pd.DataFrame({"lag_7": [-5.0]})
    predictions = predict_seasonal_naive(df)
    assert predictions.tolist() == [0.0]


def test_predict_requires_lag_7_column():
    df = pd.DataFrame({"lag_14": [1.0]})
    with pytest.raises(ValueError, match="lag_7"):
        predict_seasonal_naive(df)


def test_seasonal_naive_model_fit_predict_interface():
    model = SeasonalNaiveModel()
    fitted = model.fit(pd.DataFrame({"units_demanded": [1, 2]}), "units_demanded")
    assert fitted is model
    assert model.fitted is True
    predictions = model.predict(pd.DataFrame({"lag_7": [7.0]}))
    assert predictions.tolist() == [7.0]
