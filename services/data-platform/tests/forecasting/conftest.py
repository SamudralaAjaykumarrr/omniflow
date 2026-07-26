from __future__ import annotations

import pytest

from app.forecasting.config import ForecastSettings


@pytest.fixture
def small_config() -> ForecastSettings:
    """~120 days x 3 SKUs x 2 locations — small enough for pytest to run in
    well under a second, large enough to exercise every synthetic-history
    feature (seasonality, trend, promos, stockouts, intermittency)."""
    return ForecastSettings(
        seed=7,
        history_start_date="2025-01-01",
        history_end_date="2025-04-30",
        num_skus=3,
        num_locations=2,
        demand_scale=20.0,
        forecast_horizon_days=7,
        min_history_days=30,
    )
