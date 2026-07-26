/**
 * Forecasting screen fallback data. Two distinct provenances, both labeled
 * explicitly in the UI — never blended silently:
 *
 * 1. `CHAMPION_SELECTION` — REAL measured numbers, copied verbatim from
 *    this repo's own `TEST_RESULTS.md` ("Phase 6: Demand forecasting"
 *    section, `make forecast-smoke` run). Not fabricated, not live either —
 *    a point-in-time measured result from a prior session's actual run.
 * 2. `MOCK_FORECAST_SERIES` — a synthetic, illustrative forecast curve.
 *    `app.forecasting` writes real forecasts to local disk / MinIO
 *    (services/data-platform/forecasting_artifacts, or
 *    s3a://<bucket>/forecasting/forecast/), but there is no browser-facing
 *    read API over that output yet, so the actual per-day curve shown here
 *    is illustrative only.
 */

export const CHAMPION_SELECTION = {
  measured_at: "TEST_RESULTS.md — Phase 6 forecast-smoke run",
  seasonal_naive: { mae: 18.446428571428573, rmse: 62.02404487662138, wape: 0.29786620530565167 },
  hist_gradient_boosting: {
    mae: 9.515713349608854,
    rmse: 13.49209166350842,
    wape: 0.15365627092793996,
  },
  champion: "hist_gradient_boosting" as const,
};

export interface ForecastPoint {
  date: string;
  actual: number | null;
  forecast: number;
}

export const MOCK_FORECAST_SERIES: Record<string, ForecastPoint[]> = {
  "SKU-1042 @ node-atl": [
    { date: "07-19", actual: 41, forecast: 39 },
    { date: "07-20", actual: 44, forecast: 42 },
    { date: "07-21", actual: 38, forecast: 40 },
    { date: "07-22", actual: 47, forecast: 45 },
    { date: "07-23", actual: 43, forecast: 44 },
    { date: "07-24", actual: 46, forecast: 45 },
    { date: "07-25", actual: 49, forecast: 47 },
    { date: "07-26", actual: null, forecast: 48 },
    { date: "07-27", actual: null, forecast: 50 },
    { date: "07-28", actual: null, forecast: 49 },
    { date: "07-29", actual: null, forecast: 51 },
    { date: "07-30", actual: null, forecast: 52 },
    { date: "07-31", actual: null, forecast: 50 },
    { date: "08-01", actual: null, forecast: 53 },
  ],
};
