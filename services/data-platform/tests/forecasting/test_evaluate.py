from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from app.forecasting.evaluate import evaluate_all, evaluate_model
from app.forecasting.splits import ChronologicalSplit


@dataclass
class _ConstantModel:
    value: float

    def predict(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series([self.value] * len(df), index=df.index)


def _valid_df() -> pd.DataFrame:
    dates = pd.date_range("2025-02-01", periods=4, freq="D")
    return pd.DataFrame(
        {
            "date": list(dates) * 2,
            "sku": ["SKU-A"] * 4 + ["SKU-B"] * 4,
            "location_id": "LOC-01",
            "units_demanded": [10, 10, 10, 10, 20, 20, 20, 20],
        }
    )


def test_evaluate_model_computes_overall_metrics_from_predictions():
    df = _valid_df()
    model = _ConstantModel(value=10.0)
    result = evaluate_model(df, model, "constant")
    assert result["model_name"] == "constant"
    assert result["n"] == 8
    assert result["overall"]["mae"] == pytest.approx((0 * 4 + 10 * 4) / 8)


def test_evaluate_model_breaks_out_by_sku():
    df = _valid_df()
    model = _ConstantModel(value=10.0)
    result = evaluate_model(df, model, "constant")
    by_sku = {row["sku"]: row for row in result["by_sku"]}
    assert by_sku["SKU-A"]["mae"] == pytest.approx(0.0)
    assert by_sku["SKU-B"]["mae"] == pytest.approx(10.0)


def test_evaluate_model_breaks_out_by_horizon():
    df = _valid_df()
    model = _ConstantModel(value=10.0)
    result = evaluate_model(df, model, "constant")
    horizons = {row["horizon"] for row in result["by_horizon"]}
    assert horizons == {1, 2, 3, 4}


def test_evaluate_all_runs_both_models_against_same_split():
    df = _valid_df()
    split = ChronologicalSplit(
        train_end="2025-01-31", valid_start="2025-02-01", valid_end="2025-02-04"
    )
    result = evaluate_all(df, _ConstantModel(10.0), _ConstantModel(15.0), split)
    assert set(result["models"].keys()) == {"seasonal_naive", "hist_gradient_boosting"}
    assert result["split"]["train_end"] == "2025-01-31"
