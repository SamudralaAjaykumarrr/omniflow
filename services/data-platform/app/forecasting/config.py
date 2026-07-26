"""Typed configuration for the Phase 6 demand-forecasting pipeline —
separate from `app.config.Settings` (MinIO/Kafka connection info shared by
every data-platform component) since these knobs are forecasting-specific:
synthetic-history shape, chronological-split cutoffs, model
hyperparameters, and local artifact paths. See
docs/phase-6-demand-forecasting.md.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForecastSettings(BaseSettings):
    # `protected_namespaces=()` disables pydantic's default "model_*"
    # protected-namespace warning — `model_random_state` is a genuine field
    # name here (the secondary model's random state), not a clash with any
    # pydantic-internal `model_*` method.
    model_config = SettingsConfigDict(env_prefix="FORECAST_", protected_namespaces=())

    seed: int = 42

    # Synthetic history shape (section B).
    history_start_date: str = "2024-07-01"
    history_end_date: str = "2026-06-30"
    num_skus: int = 20
    num_locations: int = 4
    demand_scale: float = 40.0

    # Chronological validation (section E). An empty `training_cutoff_date`
    # (the default) means "derive it from the data at prepare/split time as
    # max(date) - 2 * forecast_horizon_days" rather than baking a second
    # date literal here that could silently drift out of sync with
    # `history_end_date` on an env override — see `app.forecasting.splits`.
    training_cutoff_date: str = ""
    forecast_horizon_days: int = 14
    min_history_days: int = 56

    # Feature engineering — comma-separated so a single env var can carry a
    # list without needing JSON-encoding (pydantic-settings' default list
    # parsing expects a JSON string, which is awkward from a shell/Makefile
    # ARGS= value).
    lag_days_csv: str = Field(default="1,7,14,28", validation_alias="FORECAST_LAG_DAYS")
    rolling_windows_csv: str = Field(default="7,14,28", validation_alias="FORECAST_ROLLING_WINDOWS")

    # Model / champion selection.
    model_random_state: int = 42
    champion_metric: str = "wape"

    # Local artifact persistence (section H) — relative to the service's
    # own working directory (the Dockerfile's final WORKDIR), gitignored.
    artifact_dir: str = "forecasting_artifacts"

    @field_validator("champion_metric")
    @classmethod
    def _validate_champion_metric(cls, v: str) -> str:
        allowed = {"mae", "rmse", "wape"}
        if v not in allowed:
            raise ValueError(f"champion_metric must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("num_skus", "num_locations")
    @classmethod
    def _validate_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("num_skus/num_locations must be >= 1")
        return v

    @field_validator("forecast_horizon_days", "min_history_days")
    @classmethod
    def _validate_positive_days(cls, v: int) -> int:
        if v < 1:
            raise ValueError("forecast_horizon_days/min_history_days must be >= 1 day")
        return v

    @property
    def lag_days(self) -> list[int]:
        return [int(x) for x in self.lag_days_csv.split(",") if x.strip()]

    @property
    def rolling_windows(self) -> list[int]:
        return [int(x) for x in self.rolling_windows_csv.split(",") if x.strip()]


@lru_cache
def get_forecast_settings() -> ForecastSettings:
    return ForecastSettings()
