from __future__ import annotations

import pandas as pd
import pytest

from app.forecasting.config import ForecastSettings
from app.forecasting.synthetic import generate_synthetic_history, synthetic_holidays


def test_reproducible_for_same_seed(small_config):
    first = generate_synthetic_history(small_config)
    second = generate_synthetic_history(small_config)
    pd.testing.assert_frame_equal(first, second)


def test_different_seed_changes_output(small_config):
    other = small_config.model_copy(update={"seed": small_config.seed + 1})
    first = generate_synthetic_history(small_config)
    second = generate_synthetic_history(other)
    assert not first["units_demanded"].equals(second["units_demanded"])


def test_grain_has_no_duplicates(small_config):
    df = generate_synthetic_history(small_config)
    assert df.duplicated(subset=["date", "sku", "location_id"]).sum() == 0


def test_expected_row_count(small_config):
    df = generate_synthetic_history(small_config)
    days = len(
        pd.date_range(small_config.history_start_date, small_config.history_end_date, freq="D")
    )
    assert len(df) == days * small_config.num_skus * small_config.num_locations


def test_units_are_non_negative(small_config):
    df = generate_synthetic_history(small_config)
    assert (df["units_demanded"] >= 0).all()
    assert (df["units_fulfilled"] >= 0).all()


def test_units_fulfilled_never_exceeds_demanded(small_config):
    df = generate_synthetic_history(small_config)
    assert (df["units_fulfilled"] <= df["units_demanded"]).all()
    assert (df["lost_sales"] == df["units_demanded"] - df["units_fulfilled"]).all()


def test_prices_are_positive(small_config):
    df = generate_synthetic_history(small_config)
    assert (df["price"] > 0).all()


def test_raises_when_history_shorter_than_min_history_days():
    config = ForecastSettings(
        history_start_date="2025-01-01", history_end_date="2025-01-10", min_history_days=30
    )
    with pytest.raises(ValueError, match="min_history_days"):
        generate_synthetic_history(config)


def test_some_series_are_intermittent(small_config):
    """At least one SKU/location series should have a genuine zero-demand
    day — section B's intermittent-demand requirement is actually modeled,
    not just documented."""
    df = generate_synthetic_history(small_config)
    assert (df["units_demanded"] == 0).any()


def test_synthetic_holidays_includes_fixed_dates():
    dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    holidays = synthetic_holidays(dates)
    assert pd.Timestamp("2025-01-01") in holidays
    assert pd.Timestamp("2025-07-04") in holidays
    assert pd.Timestamp("2025-12-25") in holidays
