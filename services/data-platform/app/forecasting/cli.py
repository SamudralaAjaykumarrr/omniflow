"""Command-line interface for the Phase 6 demand-forecasting pipeline.
Every subcommand is a thin wrapper around a pure/library function elsewhere
in this package — no business logic lives here, only argument parsing, I/O
wiring, and exit-code handling. See docs/phase-6-demand-forecasting.md 'CLI
commands' and the `make forecast-*` Makefile targets that call these.

Usage:
  python -m app.forecasting.cli run [--run-id ID]
  python -m app.forecasting.cli generate-history [--output PATH]
  python -m app.forecasting.cli prepare [--input PATH] [--output PATH]
  python -m app.forecasting.cli train-baseline [--input PATH] [--run-id ID]
  python -m app.forecasting.cli train-secondary [--input PATH] [--run-id ID]
  python -m app.forecasting.cli evaluate --run-id ID [--input PATH]
  python -m app.forecasting.cli select --run-id ID
  python -m app.forecasting.cli forecast --run-id ID
  python -m app.forecasting.cli validate [--input PATH]
  python -m app.forecasting.cli inspect {forecast,metrics,selection,dataset}
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid

import pandas as pd

from app.config import Settings, get_settings
from app.forecasting import artifacts, paths, quality
from app.forecasting import evaluate as evaluate_mod
from app.forecasting import io as fio
from app.forecasting import select as select_mod
from app.forecasting.baseline import BASELINE_NAME, SeasonalNaiveModel
from app.forecasting.config import ForecastSettings, get_forecast_settings
from app.forecasting.dataset import DataQualityError, prepare_dataset
from app.forecasting.features import TARGET_COL, feature_columns
from app.forecasting.forecast import generate_future_forecast
from app.forecasting.secondary_model import SECONDARY_MODEL_NAME, SecondaryModel
from app.forecasting.splits import single_split
from app.forecasting.synthetic import generate_synthetic_history

logger = logging.getLogger("data_platform.forecasting.cli")


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _load_dataset(input_path: str | None, settings: Settings) -> pd.DataFrame:
    return fio.read_parquet(input_path or paths.dataset_path(settings), settings)


def _load_trained_model(config: ForecastSettings, model_name: str, run_id: str):
    model_path, _ = artifacts.model_paths(config.artifact_dir, model_name, run_id)
    if not model_path.exists():
        raise FileNotFoundError(
            f"no saved {model_name} artifact for run_id={run_id} at {model_path}"
        )
    return artifacts.load_model(model_path)


def _train_metadata(
    *,
    run_id: str,
    model_name: str,
    feature_cols: list[str],
    train_df: pd.DataFrame,
    split,
    random_state: int | None,
):
    return artifacts.build_metadata(
        run_id=run_id,
        model_name=model_name,
        model_version="v1",
        feature_columns=feature_cols,
        training_range={
            "start": str(pd.to_datetime(train_df["date"]).min().date()),
            "end": split.train_end,
        },
        evaluation_range={"start": split.valid_start, "end": split.valid_end},
        training_rows=len(train_df),
        random_state=random_state,
    )


def cmd_generate_history(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    df = generate_synthetic_history(config)
    out_path = args.output or paths.synthetic_history_path(settings)
    fio.write_parquet(df, out_path, settings)
    print(f"synthetic history: {len(df)} row(s) -> {out_path}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    history_df = fio.read_parquet(args.input or paths.synthetic_history_path(settings), settings)
    frame = prepare_dataset(history_df, config)
    out_path = args.output or paths.dataset_path(settings)
    fio.write_parquet(frame, out_path, settings)
    print(
        f"forecasting dataset: {len(frame)} row(s), "
        f"{len(feature_columns(config))} feature(s) -> {out_path}"
    )
    return 0


def cmd_train_baseline(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    frame = _load_dataset(args.input, settings)
    train_df, _valid_df, split = single_split(frame, config)

    model = SeasonalNaiveModel().fit(train_df, TARGET_COL)
    run_id = args.run_id or _new_run_id()
    metadata = _train_metadata(
        run_id=run_id,
        model_name=BASELINE_NAME,
        feature_cols=["lag_7", "rolling_mean_7"],
        train_df=train_df,
        split=split,
        random_state=None,
    )
    model_path, _ = artifacts.save_model(model, metadata, config.artifact_dir)
    print(f"baseline trained: run_id={run_id} rows={len(train_df)} -> {model_path}")
    return 0


def cmd_train_secondary(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    frame = _load_dataset(args.input, settings)
    train_df, _valid_df, split = single_split(frame, config)

    feats = feature_columns(config)
    model = SecondaryModel(feature_columns=feats, random_state=config.model_random_state)
    model.fit(train_df, TARGET_COL)

    run_id = args.run_id or _new_run_id()
    metadata = _train_metadata(
        run_id=run_id,
        model_name=SECONDARY_MODEL_NAME,
        feature_cols=feats,
        train_df=train_df,
        split=split,
        random_state=config.model_random_state,
    )
    model_path, _ = artifacts.save_model(model, metadata, config.artifact_dir)
    print(f"secondary model trained: run_id={run_id} rows={len(train_df)} -> {model_path}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    frame = _load_dataset(args.input, settings)
    _train_df, valid_df, split = single_split(frame, config)

    baseline_model = _load_trained_model(config, BASELINE_NAME, args.run_id)
    secondary_model = _load_trained_model(config, SECONDARY_MODEL_NAME, args.run_id)

    result = evaluate_mod.evaluate_all(valid_df, baseline_model, secondary_model, split)
    fio.write_json(result, args.output or paths.evaluation_path(settings, args.run_id), settings)
    # The unversioned "latest" convenience copy is a MinIO-path convention
    # only — skipped when the caller explicitly redirected --output
    # elsewhere (e.g. tests, the local smoke test), so those never touch a
    # real MinIO path.
    if not args.output:
        fio.write_json(result, paths.evaluation_path(settings), settings)
    print(json.dumps({m: r["overall"] for m, r in result["models"].items()}, indent=2))
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    evaluation = fio.read_json(args.input or paths.evaluation_path(settings, args.run_id), settings)
    baseline_overall = evaluation["models"][BASELINE_NAME]["overall"]
    secondary_overall = evaluation["models"][SECONDARY_MODEL_NAME]["overall"]

    result = select_mod.select_champion(
        baseline_name=BASELINE_NAME,
        baseline_metrics=baseline_overall,
        secondary_name=SECONDARY_MODEL_NAME,
        secondary_metrics=secondary_overall,
        metric_name=config.champion_metric,
    )
    payload = {
        "champion_name": result.champion_name,
        "metric_name": result.metric_name,
        "baseline_value": result.baseline_value,
        "secondary_value": result.secondary_value,
        "reason": result.reason,
        "run_id": args.run_id,
    }
    fio.write_json(payload, args.output or paths.selection_path(settings, args.run_id), settings)
    if not args.output:
        fio.write_json(payload, paths.selection_path(settings), settings)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    frame = _load_dataset(args.input, settings)
    _train_df, _valid_df, split = single_split(frame, config)

    selection = fio.read_json(
        args.selection or paths.selection_path(settings, args.run_id), settings
    )
    champion_name = selection["champion_name"]
    model = _load_trained_model(config, champion_name, args.run_id)

    history_df = fio.read_parquet(args.history or paths.synthetic_history_path(settings), settings)
    forecast_df = generate_future_forecast(
        history_df, model, champion_name, "v1", config, training_cutoff=split.train_end
    )

    out_path = args.output or paths.forecast_path(settings, args.run_id)
    fio.write_parquet(forecast_df, out_path, settings)
    if not args.output:
        fio.write_parquet(forecast_df, paths.forecast_path(settings), settings)
    print(
        f"forecast: {len(forecast_df)} row(s), horizon={config.forecast_horizon_days}d, "
        f"champion={champion_name} -> {out_path}"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = get_forecast_settings()
    frame = _load_dataset(args.input, settings)
    results = quality.run_all_checks(frame, min_history_days=config.min_history_days)
    failures = quality.gating_failures(results)
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.details}")
    return 1 if failures else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.what == "forecast":
        df = fio.read_parquet(args.path or paths.forecast_path(settings, args.run_id), settings)
        print(f"forecast rows: {len(df)}")
        if not df.empty:
            print(f"date range: {df['forecast_date'].min()}..{df['forecast_date'].max()}")
            print(f"models: {sorted(df['model_name'].unique())}")
            print(df.head(10).to_string(index=False))
    elif args.what == "metrics":
        payload = fio.read_json(args.path or paths.evaluation_path(settings, args.run_id), settings)
        for model_name, result in payload["models"].items():
            print(f"{model_name}: {result['overall']}")
    elif args.what == "selection":
        payload = fio.read_json(args.path or paths.selection_path(settings, args.run_id), settings)
        print(json.dumps(payload, indent=2))
    else:
        df = fio.read_parquet(args.path or paths.dataset_path(settings), settings)
        print(f"dataset rows: {len(df)}, columns: {list(df.columns)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Full local pipeline in one process: generate -> prepare -> train both
    models -> evaluate -> select -> forecast -> print a summary. This is
    what `make forecast-run`/`make forecast-smoke` exercise end to end."""
    settings = get_settings()
    config = get_forecast_settings()
    run_id = args.run_id or _new_run_id()
    logger.info("forecasting run %s starting (seed=%s)", run_id, config.seed)

    history_df = generate_synthetic_history(config)
    fio.write_parquet(
        history_df, args.history_output or paths.synthetic_history_path(settings), settings
    )

    frame = prepare_dataset(history_df, config)
    fio.write_parquet(frame, args.dataset_output or paths.dataset_path(settings), settings)

    train_df, valid_df, split = single_split(frame, config)

    baseline_model = SeasonalNaiveModel().fit(train_df, TARGET_COL)
    feats = feature_columns(config)
    secondary_model = SecondaryModel(feature_columns=feats, random_state=config.model_random_state)
    secondary_model.fit(train_df, TARGET_COL)

    for name, model, feats_used, random_state in [
        (BASELINE_NAME, baseline_model, ["lag_7", "rolling_mean_7"], None),
        (SECONDARY_MODEL_NAME, secondary_model, feats, config.model_random_state),
    ]:
        metadata = _train_metadata(
            run_id=run_id,
            model_name=name,
            feature_cols=feats_used,
            train_df=train_df,
            split=split,
            random_state=random_state,
        )
        artifacts.save_model(model, metadata, config.artifact_dir)

    evaluation = evaluate_mod.evaluate_all(valid_df, baseline_model, secondary_model, split)
    evaluation_out = args.evaluation_output or paths.evaluation_path(settings, run_id)
    fio.write_json(evaluation, evaluation_out, settings)
    if not args.evaluation_output:
        fio.write_json(evaluation, paths.evaluation_path(settings), settings)

    selection = select_mod.select_champion(
        baseline_name=BASELINE_NAME,
        baseline_metrics=evaluation["models"][BASELINE_NAME]["overall"],
        secondary_name=SECONDARY_MODEL_NAME,
        secondary_metrics=evaluation["models"][SECONDARY_MODEL_NAME]["overall"],
        metric_name=config.champion_metric,
    )
    selection_payload = {
        "champion_name": selection.champion_name,
        "metric_name": selection.metric_name,
        "baseline_value": selection.baseline_value,
        "secondary_value": selection.secondary_value,
        "reason": selection.reason,
        "run_id": run_id,
    }
    selection_out = args.selection_output or paths.selection_path(settings, run_id)
    fio.write_json(selection_payload, selection_out, settings)
    if not args.selection_output:
        fio.write_json(selection_payload, paths.selection_path(settings), settings)

    champion_model: SeasonalNaiveModel | SecondaryModel = (
        baseline_model if selection.champion_name == BASELINE_NAME else secondary_model
    )
    forecast_df = generate_future_forecast(
        history_df,
        champion_model,
        selection.champion_name,
        "v1",
        config,
        training_cutoff=split.train_end,
    )
    forecast_out = args.forecast_output or paths.forecast_path(settings, run_id)
    fio.write_parquet(forecast_df, forecast_out, settings)
    if not args.forecast_output:
        fio.write_parquet(forecast_df, paths.forecast_path(settings), settings)

    print(f"run_id: {run_id}")
    print(f"history rows: {len(history_df)}, dataset rows: {len(frame)}")
    print(f"split: train_end={split.train_end} valid={split.valid_start}..{split.valid_end}")
    print(f"baseline overall: {evaluation['models'][BASELINE_NAME]['overall']}")
    print(f"secondary overall: {evaluation['models'][SECONDARY_MODEL_NAME]['overall']}")
    print(f"champion: {selection.champion_name} ({selection.reason})")
    print(f"forecast rows: {len(forecast_df)} -> {forecast_out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 6 demand-forecasting pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-history", help="Generate deterministic synthetic demand history")
    p.add_argument("--output")
    p.set_defaults(func=cmd_generate_history)

    p = sub.add_parser("prepare", help="Build the feature-engineered forecasting dataset")
    p.add_argument("--input")
    p.add_argument("--output")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("train-baseline", help="Train the seasonal-naive baseline")
    p.add_argument("--input")
    p.add_argument("--run-id")
    p.set_defaults(func=cmd_train_baseline)

    p = sub.add_parser(
        "train-secondary", help="Train the HistGradientBoostingRegressor secondary model"
    )
    p.add_argument("--input")
    p.add_argument("--run-id")
    p.set_defaults(func=cmd_train_secondary)

    p = sub.add_parser(
        "evaluate", help="Evaluate baseline + secondary on the chronological validation split"
    )
    p.add_argument("--input")
    p.add_argument("--output")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("select", help="Select the champion model from measured evaluation metrics")
    p.add_argument("--input")
    p.add_argument("--output")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_select)

    p = sub.add_parser("forecast", help="Generate the future forecast from the champion model")
    p.add_argument("--input")
    p.add_argument("--history")
    p.add_argument("--selection")
    p.add_argument("--output")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_forecast)

    p = sub.add_parser(
        "validate", help="Run forecasting data-quality checks against the prepared dataset"
    )
    p.add_argument("--input")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("inspect", help="Inspect forecast output, metrics, selection, or dataset")
    p.add_argument("what", choices=["forecast", "metrics", "selection", "dataset"])
    p.add_argument("--path")
    p.add_argument("--run-id")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("run", help="Run the full local pipeline end to end")
    p.add_argument("--run-id")
    p.add_argument("--history-output")
    p.add_argument("--dataset-output")
    p.add_argument("--evaluation-output")
    p.add_argument("--selection-output")
    p.add_argument("--forecast-output")
    p.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = args.func(args)
    except (ValueError, FileNotFoundError, DataQualityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
