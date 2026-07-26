import { TopBar } from "../components/layout/TopBar";
import { MockDataNotice } from "../components/common/MockDataNotice";
import { BarChart } from "../components/common/BarChart";
import { LineChart } from "../components/common/LineChart";
import { DataTable } from "../components/common/DataTable";
import {
  MOCK_DEAD_LETTER_VOLUME,
  MOCK_FULFILLMENT_SUCCESS_RATE,
  MOCK_ORDERS_PER_MINUTE,
  MOCK_REVENUE_BY_PRODUCT,
  MOCK_STOCKOUT_FREQUENCY,
} from "../api/mock/goldDatasets";

export function DataPlatformPage() {
  return (
    <>
      <TopBar title="Data Platform / Gold Datasets" />
      <MockDataNotice reason="No browser-facing read API exists yet over MinIO's Gold Parquet (docs/architecture.md names this target state). Field names/grains match the real 10 Gold datasets in docs/data-pipeline.md." />

      <section className="panel">
        <h2>Orders per minute</h2>
        <LineChart
          title="Orders per minute"
          xLabels={MOCK_ORDERS_PER_MINUTE.map((p) => p.window_start)}
          series={[
            {
              name: "orders",
              colorVar: "var(--series-1)",
              values: MOCK_ORDERS_PER_MINUTE.map((p) => p.order_count),
            },
          ]}
        />
      </section>

      <section className="panel">
        <h2>Fulfillment success rate</h2>
        <LineChart
          title="Fulfillment success rate"
          xLabels={MOCK_FULFILLMENT_SUCCESS_RATE.map((p) => p.window_start)}
          series={[
            {
              name: "success rate",
              colorVar: "var(--series-3)",
              values: MOCK_FULFILLMENT_SUCCESS_RATE.map((p) => p.success_rate),
            },
          ]}
          valueFormat={(v) => `${(v * 100).toFixed(1)}%`}
        />
      </section>

      <section className="panel">
        <h2>Revenue by product and location</h2>
        <BarChart
          title="Revenue by product"
          colorVar="var(--series-2)"
          data={MOCK_REVENUE_BY_PRODUCT.map((r) => ({ label: r.sku, value: r.revenue }))}
          valueFormat={(v) => `$${v.toLocaleString()}`}
        />
      </section>

      <section className="panel">
        <h2>Stockout frequency by SKU</h2>
        <BarChart
          title="Stockout frequency"
          colorVar="var(--series-4)"
          data={MOCK_STOCKOUT_FREQUENCY.map((r) => ({ label: r.sku, value: r.rejection_count }))}
        />
      </section>

      <section className="panel">
        <h2>Dead-letter volume by event type</h2>
        <DataTable
          caption="Dead-letter volume"
          rows={MOCK_DEAD_LETTER_VOLUME}
          getRowKey={(r) => `${r.event_type}-${r.failed_consumer}`}
          columns={[
            { key: "type", header: "Event type", render: (r) => r.event_type },
            { key: "consumer", header: "Failed consumer", render: (r) => r.failed_consumer },
            { key: "count", header: "Count", numeric: true, render: (r) => r.count },
          ]}
        />
      </section>
    </>
  );
}
