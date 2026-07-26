"""Forecast accuracy metrics (section F) — computed from actual predictions
against actual demand, never fabricated. MAE and RMSE are standard. WAPE
(weighted absolute percentage error = sum(|error|) / sum(|actual|)) is the
scale-aware business metric reported here, since this dataset has
genuinely intermittent/zero-demand series (`app.forecasting.synthetic`'s
intermittent SKUs) where per-row MAPE's division by a zero actual is
undefined. WAPE sums the numerator and denominator across the whole group
first, so an individual zero-actual row never divides by zero on its own.

MAPE is intentionally not reported at all: section F says to include it
"only when zero-demand handling is explicitly correct and documented" —
this dataset's demand series legitimately hit exact zero often enough
(intermittent SKUs, section B) that no per-row MAPE handling is "explicitly
correct" here, so it is omitted rather than special-cased.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def mae(actual: pd.Series, predicted: pd.Series) -> float:
    return float(np.mean(np.abs(actual.to_numpy() - predicted.to_numpy())))


def rmse(actual: pd.Series, predicted: pd.Series) -> float:
    return float(np.sqrt(np.mean((actual.to_numpy() - predicted.to_numpy()) ** 2)))


def wape(actual: pd.Series, predicted: pd.Series) -> float:
    actual_np = actual.to_numpy()
    predicted_np = predicted.to_numpy()
    denom = np.sum(np.abs(actual_np))
    if denom == 0:
        return 0.0 if np.sum(np.abs(predicted_np)) == 0 else float("inf")
    return float(np.sum(np.abs(actual_np - predicted_np)) / denom)


def compute_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    return {
        "mae": mae(actual, predicted),
        "rmse": rmse(actual, predicted),
        "wape": wape(actual, predicted),
    }


def metrics_by_group(
    df: pd.DataFrame, actual_col: str, predicted_col: str, group_cols: list[str]
) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(group_cols):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_cols, key_tuple, strict=True))
        row.update(compute_metrics(group[actual_col], group[predicted_col]))
        row["n"] = len(group)
        rows.append(row)
    return pd.DataFrame(rows)
