from __future__ import annotations

from app.forecasting.select import select_champion


def test_secondary_wins_when_measurably_better():
    result = select_champion(
        baseline_name="seasonal_naive",
        baseline_metrics={"wape": 0.30, "mae": 5.0},
        secondary_name="hist_gradient_boosting",
        secondary_metrics={"wape": 0.20, "mae": 4.0},
        metric_name="wape",
    )
    assert result.champion_name == "hist_gradient_boosting"
    assert "0.2000" in result.reason


def test_baseline_wins_when_secondary_is_worse():
    result = select_champion(
        baseline_name="seasonal_naive",
        baseline_metrics={"wape": 0.20},
        secondary_name="hist_gradient_boosting",
        secondary_metrics={"wape": 0.35},
        metric_name="wape",
    )
    assert result.champion_name == "seasonal_naive"
    assert "did not beat" in result.reason


def test_exact_tie_keeps_baseline():
    result = select_champion(
        baseline_name="seasonal_naive",
        baseline_metrics={"wape": 0.25},
        secondary_name="hist_gradient_boosting",
        secondary_metrics={"wape": 0.25},
        metric_name="wape",
    )
    assert result.champion_name == "seasonal_naive"


def test_uses_the_configured_metric_not_a_hardcoded_one():
    result = select_champion(
        baseline_name="seasonal_naive",
        baseline_metrics={"wape": 0.10, "mae": 10.0},
        secondary_name="hist_gradient_boosting",
        secondary_metrics={"wape": 0.05, "mae": 20.0},
        metric_name="mae",
    )
    # secondary has better WAPE but worse MAE — selecting on "mae" must pick
    # the baseline, proving the rule isn't silently hardcoded to WAPE.
    assert result.champion_name == "seasonal_naive"
