from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.metrics import compute_metrics, mae, metrics_by_group, rmse, wape


def test_mae_known_value():
    actual = pd.Series([10, 20, 30])
    predicted = pd.Series([12, 18, 33])
    assert mae(actual, predicted) == pytest.approx((2 + 2 + 3) / 3)


def test_rmse_known_value():
    actual = pd.Series([0, 0])
    predicted = pd.Series([3, 4])
    assert rmse(actual, predicted) == pytest.approx((25 / 2) ** 0.5)


def test_wape_known_value():
    actual = pd.Series([10, 20, 30])
    predicted = pd.Series([10, 20, 25])
    assert wape(actual, predicted) == pytest.approx(5 / 60)


def test_wape_zero_actual_and_zero_predicted_is_zero():
    actual = pd.Series([0, 0])
    predicted = pd.Series([0, 0])
    assert wape(actual, predicted) == 0.0


def test_wape_zero_actual_but_nonzero_predicted_is_infinite():
    actual = pd.Series([0, 0])
    predicted = pd.Series([1, 0])
    assert wape(actual, predicted) == float("inf")


def test_wape_mixes_zero_and_nonzero_rows_without_dividing_by_a_single_zero():
    """A per-row MAPE would blow up on the zero-actual row; WAPE aggregates
    numerator/denominator across the whole group first."""
    actual = pd.Series([0, 100])
    predicted = pd.Series([5, 100])
    assert wape(actual, predicted) == pytest.approx(5 / 100)


def test_compute_metrics_returns_all_three_keys():
    result = compute_metrics(pd.Series([1, 2]), pd.Series([1, 3]))
    assert set(result.keys()) == {"mae", "rmse", "wape"}


def test_metrics_by_group_groups_correctly():
    df = pd.DataFrame(
        {
            "sku": ["A", "A", "B"],
            "actual": [10, 10, 20],
            "predicted": [10, 12, 18],
        }
    )
    result = metrics_by_group(df, "actual", "predicted", ["sku"])
    result = result.set_index("sku")
    assert result.loc["A", "n"] == 2
    assert result.loc["B", "n"] == 1
    assert result.loc["A", "mae"] == pytest.approx(1.0)
    assert result.loc["B", "mae"] == pytest.approx(2.0)
