"""Stable MinIO path layout for forecasting artifacts, under
`settings.forecasting_path` (docs/phase-6-demand-forecasting.md 'Storage
layout'). `synthetic_history`/`dataset` are singleton paths — each pipeline
run overwrites them, since they are inputs, not lineage-tracked outputs.
Forecasts/evaluation/selection are versioned by `run_id` for lineage, with a
`latest` copy kept alongside for convenience (`inspect` and the smoke test
both default to reading `latest`).
"""

from __future__ import annotations

from app.config import Settings


def synthetic_history_path(settings: Settings) -> str:
    return f"{settings.forecasting_path}/synthetic_history/history.parquet"


def dataset_path(settings: Settings) -> str:
    return f"{settings.forecasting_path}/dataset/features.parquet"


def forecast_path(settings: Settings, run_id: str | None = None) -> str:
    if run_id is None:
        return f"{settings.forecasting_path}/forecasts/latest.parquet"
    return f"{settings.forecasting_path}/forecasts/run_id={run_id}/forecast.parquet"


def evaluation_path(settings: Settings, run_id: str | None = None) -> str:
    if run_id is None:
        return f"{settings.forecasting_path}/evaluation/latest.json"
    return f"{settings.forecasting_path}/evaluation/run_id={run_id}/metrics.json"


def selection_path(settings: Settings, run_id: str | None = None) -> str:
    if run_id is None:
        return f"{settings.forecasting_path}/selection/latest.json"
    return f"{settings.forecasting_path}/selection/run_id={run_id}/selection.json"
