import { TopBar } from "../components/layout/TopBar";
import { StatCard } from "../components/common/StatCard";
import { MockDataNotice } from "../components/common/MockDataNotice";
import { LineChart } from "../components/common/LineChart";
import { CHAMPION_SELECTION, MOCK_FORECAST_SERIES } from "../api/mock/forecast";

export function ForecastingPage() {
  const seriesKey = Object.keys(MOCK_FORECAST_SERIES)[0];
  const points = MOCK_FORECAST_SERIES[seriesKey];

  return (
    <>
      <TopBar title="Demand Forecasting" />

      <section className="panel">
        <h2>Champion selection — measured, not live</h2>
        <p className="text-muted">
          These WAPE/MAE/RMSE numbers are real, copied verbatim from this repo&rsquo;s own{" "}
          <code>TEST_RESULTS.md</code> (Phase 6 <code>forecast-smoke</code> run) — a point-in-time
          measured result, not a live query.
        </p>
        <div className="stat-grid">
          <StatCard
            label="Seasonal-naive baseline (WAPE)"
            value={CHAMPION_SELECTION.seasonal_naive.wape.toFixed(4)}
          />
          <StatCard
            label="HistGradientBoosting (WAPE)"
            value={CHAMPION_SELECTION.hist_gradient_boosting.wape.toFixed(4)}
            tone="good"
          />
          <StatCard label="Champion" value={CHAMPION_SELECTION.champion} tone="good" />
        </div>
      </section>

      <section className="panel">
        <h2>Forecast curve — {seriesKey}</h2>
        <MockDataNotice reason="app.forecasting writes real output to local disk/MinIO, but there is no browser-facing read API over it yet — this curve is illustrative, not a real forecast run." />
        <LineChart
          title={`Actual vs. forecast demand — ${seriesKey}`}
          xLabels={points.map((p) => p.date)}
          series={[
            { name: "actual", colorVar: "var(--series-1)", values: points.map((p) => p.actual) },
            {
              name: "forecast",
              colorVar: "var(--series-2)",
              values: points.map((p) => p.forecast),
            },
          ]}
        />
      </section>
    </>
  );
}
