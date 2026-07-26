"""Forecasting input data-quality checks (section L) — pure functions over
an already-loaded pandas DataFrame, mirroring `app.dq.checks`'s
Spark-DataFrame checks in spirit (a dataclass result per check, no I/O), so
they're unit-testable with hand-built DataFrames and reusable by both
`app.forecasting.dataset.prepare_dataset` (gating) and the `validate` CLI
command (inspectable, non-gating report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.forecasting.features import _TARGET_DERIVED_COLS, GRAIN_COLS, TARGET_COL

REQUIRED_COLUMNS = ["date", "sku", "location_id", TARGET_COL, "price"]

# A row further than this many standard deviations from its own series mean
# is flagged as an outlier — informational only (section B's synthetic
# anomalies are intentional), never gating.
OUTLIER_Z_THRESHOLD = 6.0


@dataclass
class QualityCheckResult:
    name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "details": self.details}


def check_required_columns(df: pd.DataFrame) -> QualityCheckResult:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    return QualityCheckResult("required_columns", not missing, {"missing": missing})


def check_not_empty(df: pd.DataFrame) -> QualityCheckResult:
    return QualityCheckResult("not_empty", len(df) > 0, {"rows": len(df)})


def check_parseable_dates(df: pd.DataFrame) -> QualityCheckResult:
    try:
        pd.to_datetime(df["date"])
        return QualityCheckResult("parseable_dates", True)
    except (ValueError, TypeError) as exc:
        return QualityCheckResult("parseable_dates", False, {"error": str(exc)})


def check_no_duplicate_grain(df: pd.DataFrame) -> QualityCheckResult:
    dupes = int(df.duplicated(subset=GRAIN_COLS).sum())
    return QualityCheckResult("no_duplicate_grain", dupes == 0, {"duplicate_rows": dupes})


def check_no_missing_target(df: pd.DataFrame) -> QualityCheckResult:
    missing = int(df[TARGET_COL].isna().sum())
    return QualityCheckResult("no_missing_target", missing == 0, {"missing_target_rows": missing})


def check_no_negative_demand(df: pd.DataFrame) -> QualityCheckResult:
    negative = int((df[TARGET_COL] < 0).sum())
    return QualityCheckResult("no_negative_demand", negative == 0, {"negative_rows": negative})


def check_valid_prices(df: pd.DataFrame) -> QualityCheckResult:
    invalid = int((df["price"] <= 0).sum()) if "price" in df.columns else 0
    return QualityCheckResult("valid_prices", invalid == 0, {"invalid_price_rows": invalid})


def check_consistent_identifiers(df: pd.DataFrame) -> QualityCheckResult:
    bad_sku = int(df["sku"].isna().sum() + (df["sku"].astype(str).str.strip() == "").sum())
    bad_loc = int(
        df["location_id"].isna().sum() + (df["location_id"].astype(str).str.strip() == "").sum()
    )
    passed = bad_sku == 0 and bad_loc == 0
    return QualityCheckResult(
        "consistent_identifiers", passed, {"bad_sku_rows": bad_sku, "bad_location_rows": bad_loc}
    )


def check_sufficient_history(df: pd.DataFrame, min_history_days: int) -> QualityCheckResult:
    counts = df.groupby(["sku", "location_id"])["date"].nunique()
    short = counts[counts < min_history_days]
    return QualityCheckResult(
        "sufficient_history",
        len(short) == 0,
        {"series_below_minimum": int(len(short)), "min_history_days": min_history_days},
    )


def check_no_unexpected_gaps(df: pd.DataFrame) -> QualityCheckResult:
    gapped = []
    for (sku, loc), group in df.groupby(["sku", "location_id"]):
        dates = pd.to_datetime(group["date"]).sort_values()
        if len(dates) < 2:
            continue
        expected_days = (dates.iloc[-1] - dates.iloc[0]).days + 1
        if expected_days != len(dates):
            gapped.append(f"{sku}:{loc}")
    return QualityCheckResult("no_unexpected_gaps", len(gapped) == 0, {"series_with_gaps": gapped})


def check_extreme_outliers(df: pd.DataFrame) -> QualityCheckResult:
    def _flag(group: pd.DataFrame) -> int:
        values = group[TARGET_COL].to_numpy(dtype=float)
        std = values.std()
        if std == 0:
            return 0
        z = np.abs((values - values.mean()) / std)
        return int((z > OUTLIER_Z_THRESHOLD).sum())

    flagged = sum(_flag(g) for _, g in df.groupby(["sku", "location_id"]))
    # Informational: synthetic anomalies are intentional (section B), so
    # this never gates the pipeline — reported, not enforced.
    return QualityCheckResult("extreme_outliers", True, {"flagged_rows": int(flagged)})


def check_all_zero_series(df: pd.DataFrame) -> QualityCheckResult:
    zero_series = [
        f"{sku}:{loc}"
        for (sku, loc), group in df.groupby(["sku", "location_id"])
        if (group[TARGET_COL] == 0).all()
    ]
    return QualityCheckResult(
        "all_zero_series", len(zero_series) == 0, {"all_zero_series": zero_series}
    )


def check_split_ordering(train_end: str, valid_start: str, valid_end: str) -> QualityCheckResult:
    ok = pd.Timestamp(train_end) < pd.Timestamp(valid_start) <= pd.Timestamp(valid_end)
    return QualityCheckResult(
        "valid_split_ordering",
        ok,
        {"train_end": train_end, "valid_start": valid_start, "valid_end": valid_end},
    )


def check_feature_leakage_safeguard(
    feature_cols: list[str], target_col: str = TARGET_COL
) -> QualityCheckResult:
    leaked = [c for c in feature_cols if c == target_col or c in _TARGET_DERIVED_COLS]
    return QualityCheckResult(
        "feature_leakage_safeguard", len(leaked) == 0, {"leaked_columns": leaked}
    )


def run_all_checks(df: pd.DataFrame, *, min_history_days: int) -> list[QualityCheckResult]:
    if len(df) == 0:
        return [check_not_empty(df)]
    return [
        check_required_columns(df),
        check_not_empty(df),
        check_parseable_dates(df),
        check_no_duplicate_grain(df),
        check_no_missing_target(df),
        check_no_negative_demand(df),
        check_valid_prices(df),
        check_consistent_identifiers(df),
        check_sufficient_history(df, min_history_days),
        check_no_unexpected_gaps(df),
        check_extreme_outliers(df),
        check_all_zero_series(df),
    ]


def gating_failures(results: list[QualityCheckResult]) -> list[QualityCheckResult]:
    """`extreme_outliers` always reports `passed=True` (informational,
    see above), so the only way a check contributes here is a real gating
    failure."""
    return [r for r in results if not r.passed]
