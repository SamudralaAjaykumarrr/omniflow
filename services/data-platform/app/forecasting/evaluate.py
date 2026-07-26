"""Evaluate baseline and secondary models against the chronological
validation split (section E/F) — overall, per-SKU, per-location, and
per-horizon metrics computed from real predictions, never fabricated.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import pandas as pd

from app.forecasting import metrics as metrics_mod
from app.forecasting.baseline import BASELINE_NAME
from app.forecasting.features import TARGET_COL
from app.forecasting.secondary_model import SECONDARY_MODEL_NAME
from app.forecasting.splits import ChronologicalSplit

logger = logging.getLogger("data_platform.forecasting")


class _PredictModel(Protocol):
    def predict(self, df: pd.DataFrame) -> pd.Series: ...


def evaluate_model(valid_df: pd.DataFrame, model: _PredictModel, model_name: str) -> dict[str, Any]:
    predictions = model.predict(valid_df)
    scored = valid_df.copy()
    scored["predicted_units"] = predictions.to_numpy()
    scored["model_name"] = model_name

    overall = metrics_mod.compute_metrics(scored[TARGET_COL], scored["predicted_units"])
    by_sku = metrics_mod.metrics_by_group(scored, TARGET_COL, "predicted_units", ["sku"])
    by_location = metrics_mod.metrics_by_group(
        scored, TARGET_COL, "predicted_units", ["location_id"]
    )

    valid_dates = pd.to_datetime(scored["date"])
    scored["horizon"] = (valid_dates - valid_dates.min()).dt.days + 1
    by_horizon = metrics_mod.metrics_by_group(scored, TARGET_COL, "predicted_units", ["horizon"])

    return {
        "model_name": model_name,
        "overall": overall,
        "by_sku": by_sku.to_dict(orient="records"),
        "by_location": by_location.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
        "n": len(scored),
    }


def evaluate_all(
    valid_df: pd.DataFrame,
    baseline_model: _PredictModel,
    secondary_model: _PredictModel,
    split: ChronologicalSplit,
) -> dict[str, Any]:
    baseline_result = evaluate_model(valid_df, baseline_model, BASELINE_NAME)
    secondary_result = evaluate_model(valid_df, secondary_model, SECONDARY_MODEL_NAME)
    logger.info(
        "forecasting evaluation (%s..%s): baseline overall=%s secondary overall=%s",
        split.valid_start,
        split.valid_end,
        baseline_result["overall"],
        secondary_result["overall"],
    )
    return {
        "split": {
            "train_end": split.train_end,
            "valid_start": split.valid_start,
            "valid_end": split.valid_end,
        },
        "models": {
            BASELINE_NAME: baseline_result,
            SECONDARY_MODEL_NAME: secondary_result,
        },
    }
