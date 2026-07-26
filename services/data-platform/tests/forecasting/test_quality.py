from __future__ import annotations

import pandas as pd

from app.forecasting import quality


def _good_df(days: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    rows = []
    for sku in ["SKU-0001", "SKU-0002"]:
        for loc in ["LOC-01"]:
            for d in dates:
                rows.append(
                    {"date": d, "sku": sku, "location_id": loc, "units_demanded": 5, "price": 9.99}
                )
    return pd.DataFrame(rows)


def test_required_columns_passes_for_good_df():
    result = quality.check_required_columns(_good_df())
    assert result.passed


def test_required_columns_flags_missing():
    df = _good_df().drop(columns=["price"])
    result = quality.check_required_columns(df)
    assert not result.passed
    assert "price" in result.details["missing"]


def test_not_empty_flags_empty_frame():
    result = quality.check_not_empty(pd.DataFrame())
    assert not result.passed


def test_no_duplicate_grain_flags_duplicates():
    df = _good_df()
    dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    result = quality.check_no_duplicate_grain(dup)
    assert not result.passed
    assert result.details["duplicate_rows"] == 1


def test_no_missing_target_flags_nan():
    df = _good_df()
    df.loc[0, "units_demanded"] = None
    result = quality.check_no_missing_target(df)
    assert not result.passed


def test_no_negative_demand_flags_negative():
    df = _good_df()
    df.loc[0, "units_demanded"] = -1
    result = quality.check_no_negative_demand(df)
    assert not result.passed
    assert result.details["negative_rows"] == 1


def test_valid_prices_flags_zero_or_negative():
    df = _good_df()
    df.loc[0, "price"] = 0
    result = quality.check_valid_prices(df)
    assert not result.passed


def test_consistent_identifiers_flags_blank_sku():
    df = _good_df()
    df.loc[0, "sku"] = ""
    result = quality.check_consistent_identifiers(df)
    assert not result.passed
    assert result.details["bad_sku_rows"] == 1


def test_sufficient_history_flags_short_series():
    df = _good_df(days=10)
    result = quality.check_sufficient_history(df, min_history_days=30)
    assert not result.passed
    assert result.details["series_below_minimum"] == 2  # both SKUs are short


def test_no_unexpected_gaps_flags_missing_days():
    df = _good_df(days=10)
    gapped = df.drop(df.index[5])
    result = quality.check_no_unexpected_gaps(gapped)
    assert not result.passed


def test_all_zero_series_flags_fully_zero_series():
    df = _good_df(days=10)
    df.loc[df["sku"] == "SKU-0001", "units_demanded"] = 0
    result = quality.check_all_zero_series(df)
    assert not result.passed
    assert any("SKU-0001" in s for s in result.details["all_zero_series"])


def test_split_ordering_passes_for_valid_order():
    result = quality.check_split_ordering("2025-01-31", "2025-02-01", "2025-02-07")
    assert result.passed


def test_split_ordering_fails_for_inverted_dates():
    result = quality.check_split_ordering("2025-02-07", "2025-02-01", "2025-01-31")
    assert not result.passed


def test_feature_leakage_safeguard_flags_target_column():
    result = quality.check_feature_leakage_safeguard(["lag_1", "units_demanded"])
    assert not result.passed


def test_run_all_checks_returns_empty_dataset_result_only():
    results = quality.run_all_checks(pd.DataFrame(), min_history_days=1)
    assert len(results) == 1
    assert results[0].name == "not_empty"


def test_run_all_checks_returns_full_set_for_good_df():
    results = quality.run_all_checks(_good_df(days=40), min_history_days=30)
    names = {r.name for r in results}
    assert "extreme_outliers" in names
    assert len(quality.gating_failures(results)) == 0


def test_extreme_outliers_never_gates():
    df = _good_df(days=40)
    df.loc[df.index[0], "units_demanded"] = 100_000
    result = quality.check_extreme_outliers(df)
    assert result.passed  # informational only
    assert result.details["flagged_rows"] >= 1
