"""Baseline forecaster (ADR 0006, section C): seasonal-naive — predict a
day's demand as the same weekday's demand one week earlier (`lag_7`),
falling back to the trailing 7-day mean (`rolling_mean_7`) when `lag_7`
isn't available yet (the first week of a series), and to zero only if
neither exists (a series with less than a week of history). This is
deliberately not weakened to make the secondary model look better — it is
the exact "same period last cycle" baseline ADR 0006 commits to.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

BASELINE_NAME = "seasonal_naive"


def predict_seasonal_naive(df: pd.DataFrame) -> pd.Series:
    if "lag_7" not in df.columns:
        raise ValueError("seasonal-naive baseline requires a 'lag_7' feature column")
    prediction = df["lag_7"].astype(float)
    if "rolling_mean_7" in df.columns:
        prediction = prediction.fillna(df["rolling_mean_7"].astype(float))
    return prediction.fillna(0.0).clip(lower=0)


@dataclass
class SeasonalNaiveModel:
    """No parameters to learn — `fit` is a no-op kept only so this shares
    the same `fit`/`predict` interface `SecondaryModel` has, letting the CLI
    and `app.forecasting.evaluate` treat both models uniformly."""

    fitted: bool = False

    def fit(self, train_df: pd.DataFrame, target_col: str) -> SeasonalNaiveModel:
        self.fitted = True
        return self

    def predict(self, df: pd.DataFrame) -> pd.Series:
        return predict_seasonal_naive(df)
