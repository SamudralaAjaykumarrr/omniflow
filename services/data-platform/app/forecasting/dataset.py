"""Assembles the forecasting dataset: raw synthetic history -> quality gate
-> feature-engineered, model-ready frame (grain: SKU x location x date). See
docs/phase-6-demand-forecasting.md.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.forecasting import quality
from app.forecasting.config import ForecastSettings
from app.forecasting.features import build_feature_frame, feature_columns

logger = logging.getLogger("data_platform.forecasting")


class DataQualityError(Exception):
    def __init__(self, failures: list[quality.QualityCheckResult]):
        self.failures = failures
        super().__init__(f"forecasting data-quality gate failed: {[f.name for f in failures]}")


def prepare_dataset(history_df: pd.DataFrame, config: ForecastSettings) -> pd.DataFrame:
    results = quality.run_all_checks(history_df, min_history_days=config.min_history_days)
    failures = quality.gating_failures(results)
    if failures:
        raise DataQualityError(failures)

    frame = build_feature_frame(history_df, config)

    leak_check = quality.check_feature_leakage_safeguard(feature_columns(config))
    if not leak_check.passed:
        raise DataQualityError([leak_check])

    logger.info(
        "forecasting dataset prepared: %s row(s), %s series (sku x location), %s feature(s)",
        len(frame),
        frame.groupby(["sku", "location_id"]).ngroups,
        len(feature_columns(config)),
    )
    return frame
