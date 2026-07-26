import { TopBar } from "../components/layout/TopBar";
import { StatCard } from "../components/common/StatCard";
import { StatusBadge } from "../components/common/StatusBadge";
import { DataTable } from "../components/common/DataTable";
import { MockDataNotice } from "../components/common/MockDataNotice";
import { MOCK_DATA_QUALITY_REPORT } from "../api/mock/dataQuality";

export function DataQualityPage() {
  const report = MOCK_DATA_QUALITY_REPORT;

  return (
    <>
      <TopBar title="Data Quality" />
      <MockDataNotice reason="No browser-facing read API exists yet over app.dq.report's MinIO JSON output (docs/architecture.md names this target state). Shape matches the real report exactly." />

      <div className="stat-grid">
        <StatCard label="Overall" value={<StatusBadge status={report.overall} />} />
        <StatCard
          label="Schema rejection rate"
          value={`${(report.schema_rejection_rate * 100).toFixed(2)}%`}
        />
        <StatCard
          label="Duplicate rate"
          value={`${(report.duplicate_rate * 100).toFixed(2)}%`}
          sublabel="informational — expected under at-least-once delivery"
        />
        <StatCard label="Late-event rate" value={`${(report.late_event_rate * 100).toFixed(2)}%`} />
        <StatCard
          label="Freshness"
          value={`${report.freshness_minutes} min`}
          sublabel={`threshold ${report.freshness_threshold_minutes} min`}
          tone={
            report.freshness_minutes <= report.freshness_threshold_minutes ? "good" : "critical"
          }
        />
      </div>

      <section className="panel">
        <h2>Bronze → Silver reconciliation by event type ({report.report_date})</h2>
        <DataTable
          caption="Bronze vs Silver reconciliation"
          rows={report.reconciliation}
          getRowKey={(r) => r.event_type}
          columns={[
            { key: "type", header: "Event type", render: (r) => r.event_type },
            { key: "bronze", header: "Bronze count", numeric: true, render: (r) => r.bronze_count },
            {
              key: "on_time",
              header: "Silver on-time",
              numeric: true,
              render: (r) => r.silver_on_time,
            },
            { key: "late", header: "Late", numeric: true, render: (r) => r.silver_late },
            {
              key: "rejected",
              header: "Rejected",
              numeric: true,
              render: (r) => r.silver_rejected,
            },
            {
              key: "unaccounted",
              header: "Unaccounted",
              numeric: true,
              render: (r) => (
                <span className={r.unaccounted > 0 ? "text-critical" : undefined}>
                  {r.unaccounted}
                </span>
              ),
            },
          ]}
        />
      </section>
    </>
  );
}
