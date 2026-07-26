"""Chronological (never random) train/validation split and rolling-origin
walk-forward folds for time-series evaluation (section E). A random shuffle
split would leak future information into training — ADR 0006 rules it out
explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.forecasting.config import ForecastSettings


@dataclass(frozen=True)
class ChronologicalSplit:
    train_end: str
    valid_start: str
    valid_end: str


def resolve_training_cutoff(df: pd.DataFrame, config: ForecastSettings) -> str:
    """`config.training_cutoff_date` (if set) wins; otherwise the cutoff is
    derived as `max(date) - 2 * forecast_horizon_days` — one horizon held
    out for validation, one horizon of buffer before it so lag/rolling
    features at the start of the validation block still have real history
    behind them."""
    if config.training_cutoff_date:
        return config.training_cutoff_date
    max_date = pd.to_datetime(df["date"]).max()
    cutoff = max_date - pd.Timedelta(days=2 * config.forecast_horizon_days)
    return cutoff.date().isoformat()


def single_split(
    df: pd.DataFrame, config: ForecastSettings
) -> tuple[pd.DataFrame, pd.DataFrame, ChronologicalSplit]:
    """Fixed cutoff: everything up to and including `train_end` trains,
    exactly one `forecast_horizon_days`-long block immediately after it
    validates. Raises `ValueError` (never silently truncates) if the
    resulting training window is shorter than `min_history_days`, or if no
    rows fall in the validation window at all."""
    cutoff = resolve_training_cutoff(df, config)
    dates = pd.to_datetime(df["date"])
    cutoff_ts = pd.Timestamp(cutoff)
    valid_end_ts = cutoff_ts + pd.Timedelta(days=config.forecast_horizon_days)

    history_days = (cutoff_ts - dates.min()).days
    if history_days < config.min_history_days:
        raise ValueError(
            f"training period ({history_days} day(s) before cutoff {cutoff}) is shorter "
            f"than min_history_days={config.min_history_days}"
        )

    train = df[dates <= cutoff_ts]
    valid = df[(dates > cutoff_ts) & (dates <= valid_end_ts)]
    if valid.empty:
        raise ValueError(
            f"no rows after cutoff {cutoff} within horizon {config.forecast_horizon_days}d"
        )

    split = ChronologicalSplit(
        train_end=cutoff,
        valid_start=(cutoff_ts + pd.Timedelta(days=1)).date().isoformat(),
        valid_end=valid_end_ts.date().isoformat(),
    )
    return train, valid, split


def walk_forward_folds(
    df: pd.DataFrame, config: ForecastSettings, *, n_folds: int = 3
) -> list[ChronologicalSplit]:
    """Expanding-window rolling-origin folds: fold i's validation block is
    the `forecast_horizon_days` immediately after fold i's cutoff, and each
    successive cutoff moves forward by one horizon — so every fold's
    training window strictly contains the previous fold's (expanding, never
    shrinking or resetting), and no fold's validation dates overlap
    another's. Folds whose training window would be shorter than
    `min_history_days`, or whose validation block would run past the end of
    the data, are skipped rather than raising — a config with too little
    history for `n_folds` should still evaluate however many folds *are*
    valid, and `evaluate`/CLI callers can check for an empty result."""
    dates = pd.to_datetime(df["date"])
    max_date = dates.max()
    min_date = dates.min()
    horizon = pd.Timedelta(days=config.forecast_horizon_days)

    last_cutoff = pd.Timestamp(resolve_training_cutoff(df, config))
    cutoffs = [last_cutoff - i * horizon for i in range(n_folds)][::-1]

    folds = []
    for cutoff in cutoffs:
        history_days = (cutoff - min_date).days
        if history_days < config.min_history_days:
            continue
        valid_end = cutoff + horizon
        if valid_end > max_date:
            continue
        folds.append(
            ChronologicalSplit(
                train_end=cutoff.date().isoformat(),
                valid_start=(cutoff + pd.Timedelta(days=1)).date().isoformat(),
                valid_end=valid_end.date().isoformat(),
            )
        )
    return folds
