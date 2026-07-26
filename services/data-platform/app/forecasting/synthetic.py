"""Deterministic synthetic historical retail demand (section B).

The real order/inventory event catalog has no location attribution on a
`order.created` item (`OrderItemData` carries `sku, qty, unit_price` only —
see `app.gold.queries` module docstring) and this session's live data
volume is whatever a smoke test happened to generate — nowhere near enough
for a meaningful SKU x location x date model. Per ADR 0006 and this phase's
spec, a deterministic synthetic history stands in as the primary dataset;
everything below is explicitly synthetic, not derived from any real
retailer's data.

Grain: one row per (date, sku, location_id). Every assumption is documented
inline and in docs/phase-6-demand-forecasting.md's 'Synthetic-data
assumptions'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.forecasting.config import ForecastSettings

# Generic, publicly-known calendar dates (not a real retailer's proprietary
# promotional calendar) used only to give the synthetic series a holiday
# demand bump — see `synthetic_holidays`.
_FIXED_HOLIDAYS_MONTH_DAY = [(1, 1), (7, 4), (12, 25)]

# Weekly seasonality: a generic "retail" curve (Mon=0..Sun=6) — weekend
# demand higher than midweek. A documented assumption, not fit to any real
# dataset.
_DOW_CURVE = np.array([0.90, 0.85, 0.90, 0.95, 1.05, 1.30, 1.20])


def synthetic_holidays(dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Fixed-date holidays (New Year's Day, July 4th, Christmas) plus the
    fourth Thursday of November (a generic 'harvest holiday' placeholder,
    computed from the calendar, not sourced from any licensed dataset) for
    every year touched by `dates`."""
    years = range(int(dates.min().year), int(dates.max().year) + 1)
    holidays: list[pd.Timestamp] = []
    for year in years:
        for month, day in _FIXED_HOLIDAYS_MONTH_DAY:
            holidays.append(pd.Timestamp(year=year, month=month, day=day))
        nov_first = pd.Timestamp(year=year, month=11, day=1)
        first_thursday_offset = (3 - nov_first.dayofweek) % 7  # Thursday == 3
        first_thursday = nov_first + pd.Timedelta(days=int(first_thursday_offset))
        holidays.append(first_thursday + pd.Timedelta(weeks=3))
    return holidays


def generate_synthetic_history(config: ForecastSettings) -> pd.DataFrame:
    """Deterministic given `config` (seed + shape knobs) — the same config
    always produces the same DataFrame, verified by
    `tests/forecasting/test_synthetic.py::test_reproducible_for_same_seed`.

    Models, per section B: weekly seasonality, annual seasonality, trend,
    SKU-specific characteristics (base demand, intermittency, price),
    location-specific effects, intermittent demand, promotion spikes,
    stockout effects, and rare anomaly/outlier days.
    """
    dates = pd.date_range(config.history_start_date, config.history_end_date, freq="D")
    if len(dates) < config.min_history_days:
        raise ValueError(
            f"history range {config.history_start_date}..{config.history_end_date} "
            f"({len(dates)} day(s)) is shorter than min_history_days={config.min_history_days}"
        )

    rng = np.random.default_rng(config.seed)

    skus = [f"SKU-{i:04d}" for i in range(1, config.num_skus + 1)]
    locations = [f"LOC-{i:02d}" for i in range(1, config.num_locations + 1)]

    # Per-SKU characteristics, drawn once — deliberately not per-row, so a
    # given SKU has one consistent "personality" across its whole history.
    sku_base_demand = rng.lognormal(mean=0.0, sigma=0.6, size=len(skus)) * config.demand_scale
    sku_intermittent = rng.random(len(skus)) < 0.15
    sku_intermittent_prob = rng.uniform(0.25, 0.5, size=len(skus))
    sku_trend_rate = rng.uniform(-0.0003, 0.0008, size=len(skus))
    sku_promo_prob = rng.uniform(0.01, 0.04, size=len(skus))
    sku_base_price = rng.uniform(5.0, 200.0, size=len(skus))
    sku_avg_items_per_order = rng.uniform(1.0, 3.0, size=len(skus))

    loc_multiplier = rng.uniform(0.6, 1.4, size=len(locations))

    sku_df = pd.DataFrame(
        {
            "sku": skus,
            "_base_demand": sku_base_demand,
            "_intermittent": sku_intermittent,
            "_intermittent_prob": sku_intermittent_prob,
            "_trend_rate": sku_trend_rate,
            "_promo_prob": sku_promo_prob,
            "_base_price": sku_base_price,
            "_avg_items_per_order": sku_avg_items_per_order,
        }
    )
    loc_df = pd.DataFrame({"location_id": locations, "_loc_multiplier": loc_multiplier})

    grid = pd.MultiIndex.from_product(
        [dates, skus, locations], names=["date", "sku", "location_id"]
    ).to_frame(index=False)
    grid = grid.merge(sku_df, on="sku", how="left").merge(loc_df, on="location_id", how="left")

    n = len(grid)
    day_index = (grid["date"] - dates[0]).dt.days.to_numpy()
    dow = grid["date"].dt.dayofweek.to_numpy()
    doy = grid["date"].dt.dayofyear.to_numpy()

    dow_multiplier = _DOW_CURVE[dow]
    # Single annual sine cycle peaking in the winter holiday season
    # (day-of-year ~ 330-350), amplitude +/-25% — a documented, deliberately
    # simple seasonality assumption, not fit to any real data.
    annual_multiplier = 1.0 + 0.25 * np.sin(2 * np.pi * (doy - 80) / 365.25)
    trend_multiplier = 1.0 + grid["_trend_rate"].to_numpy() * day_index

    promo_roll = rng.random(n)
    promo_flag = (promo_roll < grid["_promo_prob"].to_numpy()).astype(int)
    promo_multiplier = np.where(promo_flag == 1, rng.uniform(1.5, 3.0, size=n), 1.0)

    # Rare anomaly/outlier days: ~0.25% spikes, ~0.25% drops.
    anomaly_roll = rng.random(n)
    is_spike = anomaly_roll < 0.0025
    is_drop = (anomaly_roll >= 0.0025) & (anomaly_roll < 0.005)
    anomaly_multiplier = np.ones(n)
    anomaly_multiplier[is_spike] = rng.uniform(3.0, 6.0, size=int(is_spike.sum()))
    anomaly_multiplier[is_drop] = rng.uniform(0.0, 0.2, size=int(is_drop.sum()))

    intermittent_mask = np.where(
        grid["_intermittent"].to_numpy(),
        (rng.random(n) < grid["_intermittent_prob"].to_numpy()).astype(float),
        1.0,
    )

    holiday_dates = set(synthetic_holidays(dates))
    is_holiday = grid["date"].isin(holiday_dates).to_numpy().astype(int)
    holiday_multiplier = np.where(is_holiday == 1, 1.5, 1.0)

    expected_units = (
        grid["_base_demand"].to_numpy()
        * grid["_loc_multiplier"].to_numpy()
        * dow_multiplier
        * annual_multiplier
        * trend_multiplier
        * promo_multiplier
        * anomaly_multiplier
        * intermittent_mask
        * holiday_multiplier
    )
    expected_units = np.clip(expected_units, 0.0, None)
    units_demanded = rng.poisson(expected_units)

    # Stockout effect: ~2% of rows have on-hand stock too low to cover
    # demand; the rest have comfortable headroom.
    stockout_roll = rng.random(n)
    is_stockout = stockout_roll < 0.02
    stock_available = np.where(
        is_stockout,
        np.round(units_demanded * rng.uniform(0.0, 0.5, size=n)),
        units_demanded + rng.integers(5, 50, size=n),
    ).astype(int)
    units_fulfilled = np.minimum(units_demanded, stock_available)

    price = grid["_base_price"].to_numpy() * rng.uniform(0.97, 1.03, size=n)
    price = np.where(promo_flag == 1, price * rng.uniform(0.7, 0.9, size=n), price)
    price = np.round(price, 2)

    order_count = np.where(
        units_demanded > 0,
        np.maximum(1, np.round(units_demanded / grid["_avg_items_per_order"].to_numpy())),
        0,
    ).astype(int)

    result = pd.DataFrame(
        {
            "date": grid["date"].dt.date,
            "sku": grid["sku"],
            "location_id": grid["location_id"],
            "units_demanded": units_demanded.astype(int),
            "units_fulfilled": units_fulfilled.astype(int),
            "lost_sales": (units_demanded - units_fulfilled).astype(int),
            "order_count": order_count,
            "stock_available": stock_available,
            "price": price,
            "promo_flag": promo_flag,
            "is_holiday": is_holiday,
            "is_stockout": is_stockout.astype(int),
        }
    )
    return result.sort_values(["date", "sku", "location_id"]).reset_index(drop=True)
