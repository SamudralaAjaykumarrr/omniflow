/**
 * Fixture shaped like the real `app.dq.report` JSON output
 * (services/data-platform/app/dq/report.py, written to
 * s3a://<bucket>/dq-reports/date=<Y>/report.json). There is no HTTP read
 * API over MinIO for the browser to call yet (docs/architecture.md names
 * this as target state), so this dashboard falls back to a clearly-labeled
 * static snapshot rather than pretending to read live data. The shape and
 * field names match the real report exactly, so wiring up a real read API
 * later is a drop-in swap, not a redesign.
 */
export interface EventTypeReconciliation {
  event_type: string;
  bronze_count: number;
  silver_on_time: number;
  silver_late: number;
  silver_rejected: number;
  unaccounted: number;
}

export interface DataQualityReport {
  report_date: string;
  generated_at: string;
  overall: "PASS" | "FAIL";
  reconciliation: EventTypeReconciliation[];
  schema_rejection_rate: number;
  duplicate_rate: number;
  late_event_rate: number;
  freshness_minutes: number;
  freshness_threshold_minutes: number;
}

export const MOCK_DATA_QUALITY_REPORT: DataQualityReport = {
  report_date: "2026-07-25",
  generated_at: "2026-07-25T23:58:04Z",
  overall: "PASS",
  reconciliation: [
    {
      event_type: "order.created",
      bronze_count: 1842,
      silver_on_time: 1831,
      silver_late: 8,
      silver_rejected: 3,
      unaccounted: 0,
    },
    {
      event_type: "order.validated",
      bronze_count: 1842,
      silver_on_time: 1839,
      silver_late: 3,
      silver_rejected: 0,
      unaccounted: 0,
    },
    {
      event_type: "inventory.reserved",
      bronze_count: 1690,
      silver_on_time: 1682,
      silver_late: 6,
      silver_rejected: 2,
      unaccounted: 0,
    },
    {
      event_type: "inventory.rejected",
      bronze_count: 152,
      silver_on_time: 151,
      silver_late: 1,
      silver_rejected: 0,
      unaccounted: 0,
    },
    {
      event_type: "order.shipped",
      bronze_count: 1612,
      silver_on_time: 1594,
      silver_late: 18,
      silver_rejected: 0,
      unaccounted: 0,
    },
    {
      event_type: "order.failed",
      bronze_count: 78,
      silver_on_time: 78,
      silver_late: 0,
      silver_rejected: 0,
      unaccounted: 0,
    },
    {
      event_type: "deadletter.event",
      bronze_count: 14,
      silver_on_time: 14,
      silver_late: 0,
      silver_rejected: 0,
      unaccounted: 0,
    },
  ],
  schema_rejection_rate: 0.0027,
  duplicate_rate: 0.0141,
  late_event_rate: 0.0098,
  freshness_minutes: 4,
  freshness_threshold_minutes: 15,
};
