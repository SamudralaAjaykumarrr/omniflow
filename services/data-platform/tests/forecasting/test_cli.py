from __future__ import annotations

import argparse

import pytest

from app.config import Settings
from app.forecasting import cli
from app.forecasting import io as fio
from app.forecasting.config import ForecastSettings


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Wires `app.forecasting.cli` to a throwaway Settings/ForecastSettings
    pair for the duration of a test, bypassing both `lru_cache`d getters —
    this is what keeps every CLI test entirely local (no real MinIO
    connection), matching `make test-data-platform`'s existing contract."""
    settings = Settings()
    config = ForecastSettings(
        seed=11,
        history_start_date="2025-01-01",
        history_end_date="2025-05-31",
        num_skus=2,
        num_locations=2,
        demand_scale=15.0,
        forecast_horizon_days=7,
        min_history_days=30,
        artifact_dir=str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_forecast_settings", lambda: config)
    return settings, config


def test_build_parser_exposes_every_documented_subcommand():
    parser = cli.build_parser()
    subparsers_action = next(
        a for a in parser._subparsers._group_actions if isinstance(a, argparse._SubParsersAction)
    )
    assert set(subparsers_action.choices) == {
        "generate-history",
        "prepare",
        "train-baseline",
        "train-secondary",
        "evaluate",
        "select",
        "forecast",
        "validate",
        "inspect",
        "run",
    }


def test_cmd_run_end_to_end_produces_expected_artifacts(wired, tmp_path):
    settings, config = wired
    history_output = str(tmp_path / "history.parquet")
    dataset_output = str(tmp_path / "dataset.parquet")
    evaluation_output = str(tmp_path / "evaluation.json")
    selection_output = str(tmp_path / "selection.json")
    forecast_output = str(tmp_path / "forecast.parquet")

    args = argparse.Namespace(
        run_id="testrun1",
        history_output=history_output,
        dataset_output=dataset_output,
        evaluation_output=evaluation_output,
        selection_output=selection_output,
        forecast_output=forecast_output,
    )
    exit_code = cli.cmd_run(args)
    assert exit_code == 0

    history_df = fio.read_parquet(history_output, settings)
    assert len(history_df) > 0

    dataset_df = fio.read_parquet(dataset_output, settings)
    assert "lag_7" in dataset_df.columns

    forecast_df = fio.read_parquet(forecast_output, settings)
    assert len(forecast_df) == config.forecast_horizon_days * config.num_skus * config.num_locations
    required_cols = {
        "forecast_generated_at",
        "forecast_date",
        "horizon",
        "sku",
        "location_id",
        "predicted_units",
        "model_name",
        "model_version",
        "run_id",
        "training_cutoff",
    }
    assert required_cols.issubset(forecast_df.columns)
    assert (forecast_df["predicted_units"] >= 0).all()

    evaluation = fio.read_json(evaluation_output, settings)
    assert set(evaluation["models"].keys()) == {"seasonal_naive", "hist_gradient_boosting"}

    selection = fio.read_json(selection_output, settings)
    assert selection["champion_name"] in {"seasonal_naive", "hist_gradient_boosting"}
    assert selection["metric_name"] == config.champion_metric

    # Model artifacts were actually persisted locally under artifact_dir.
    from app.forecasting import artifacts

    for model_name in ["seasonal_naive", "hist_gradient_boosting"]:
        model_path, metadata_path = artifacts.model_paths(
            config.artifact_dir, model_name, "testrun1"
        )
        assert model_path.exists()
        assert metadata_path.exists()


def test_cmd_validate_reports_pass_for_a_clean_dataset(wired, tmp_path, capsys):
    """`generate-history`/`prepare` with no `--output` override write to the
    settings-based MinIO path, which this test must never touch — so the
    frame is built directly via the library functions the CLI itself calls,
    instead of going through `cmd_generate_history`/`cmd_prepare`."""
    settings, config = wired
    dataset_path = str(tmp_path / "dataset.parquet")

    from app.forecasting.dataset import prepare_dataset
    from app.forecasting.synthetic import generate_synthetic_history

    history = generate_synthetic_history(config)
    frame = prepare_dataset(history, config)
    fio.write_parquet(frame, dataset_path, settings)

    validate_args = argparse.Namespace(input=dataset_path)
    exit_code = cli.cmd_validate(validate_args)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[PASS]" in out
