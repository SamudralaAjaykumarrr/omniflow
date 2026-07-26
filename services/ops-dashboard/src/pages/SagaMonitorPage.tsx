import { useState } from "react";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { StatusBadge } from "../components/common/StatusBadge";
import { DataTable } from "../components/common/DataTable";
import { useAsync } from "../hooks/useAsync";
import { listSagaInstances } from "../api/orchestrator";
import type { SagaInstance } from "../api/types";

const STATUS_FILTERS = ["", "RUNNING", "COMPLETED", "FAILED"];

export function SagaMonitorPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<SagaInstance | null>(null);
  const state = useAsync(() => listSagaInstances(statusFilter || undefined), [statusFilter], {
    pollIntervalMs: 10_000,
  });

  return (
    <>
      <TopBar title="Saga Monitor" />
      <p className="page-lede">
        Real data from the Fulfillment Orchestrator&rsquo;s saga-instance ledger (GET
        /saga-instances).
      </p>

      <div className="toolbar">
        <label htmlFor="status-filter">Filter by status</label>
        <select
          id="status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s || "All"}
            </option>
          ))}
        </select>
      </div>

      {state.status === "loading" && <LoadingState label="Loading saga instances…" />}
      {state.status === "error" && (
        <ErrorState error={state.error} onRetry={state.refetch} context="saga instances" />
      )}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState
          title="No sagas found"
          description="Create an order to start a saga, or try a different filter."
        />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <DataTable
          caption="Saga instances"
          rows={state.data}
          getRowKey={(s) => s.id}
          onRowActivate={(s) => setSelected(s)}
          columns={[
            {
              key: "order",
              header: "Order ID",
              render: (s) => <code>{s.order_id.slice(0, 8)}…</code>,
            },
            { key: "step", header: "Current step", render: (s) => s.current_step },
            { key: "status", header: "Status", render: (s) => <StatusBadge status={s.status} /> },
            { key: "attempts", header: "Attempts", numeric: true, render: (s) => s.attempt_count },
            {
              key: "updated",
              header: "Updated",
              render: (s) => new Date(s.updated_at).toLocaleString(),
            },
          ]}
        />
      )}

      {selected && (
        <section className="panel">
          <h2>Saga detail — {selected.order_id}</h2>
          <dl className="definition-grid">
            <dt>Status</dt>
            <dd>
              <StatusBadge status={selected.status} />
            </dd>
            <dt>Current step</dt>
            <dd>{selected.current_step}</dd>
            <dt>Attempts</dt>
            <dd>{selected.attempt_count}</dd>
            <dt>Last error</dt>
            <dd>{selected.last_error ?? "none"}</dd>
          </dl>
          <h3>Context</h3>
          <pre className="code-block">{JSON.stringify(selected.context, null, 2)}</pre>
        </section>
      )}
    </>
  );
}
