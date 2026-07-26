import { useState } from "react";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { DataTable } from "../components/common/DataTable";
import { useAsync } from "../hooks/useAsync";
import { listDeadLetters } from "../api/orchestrator";
import type { DeadLetterEvent } from "../api/types";

export function DeadLetterQueuePage() {
  const [unreplayedOnly, setUnreplayedOnly] = useState(true);
  const [selected, setSelected] = useState<DeadLetterEvent | null>(null);
  const state = useAsync(() => listDeadLetters(unreplayedOnly), [unreplayedOnly], {
    pollIntervalMs: 15_000,
  });

  return (
    <>
      <TopBar title="Dead Letter Queue" />
      <p className="page-lede">
        Real data from the Fulfillment Orchestrator&rsquo;s dead-letter table (GET /dead-letters) —
        events that exhausted retries (docs/event-catalog.md &ldquo;Retry policy&rdquo;) rather than
        being silently dropped.
      </p>

      <div className="toolbar">
        <label>
          <input
            type="checkbox"
            checked={unreplayedOnly}
            onChange={(e) => setUnreplayedOnly(e.target.checked)}
          />{" "}
          Show unreplayed only
        </label>
      </div>

      {state.status === "loading" && <LoadingState label="Loading dead letters…" />}
      {state.status === "error" && (
        <ErrorState error={state.error} onRetry={state.refetch} context="dead letters" />
      )}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState
          title="No dead-lettered events"
          description="Nothing has exhausted its retry budget. That's a good sign."
        />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <DataTable
          caption="Dead-lettered events"
          rows={state.data}
          getRowKey={(d) => d.id}
          onRowActivate={setSelected}
          columns={[
            { key: "type", header: "Event type", render: (d) => d.event_type },
            { key: "consumer", header: "Failed consumer", render: (d) => d.failed_consumer },
            { key: "error", header: "Error type", render: (d) => d.error_type },
            { key: "attempts", header: "Attempts", numeric: true, render: (d) => d.attempt_count },
            {
              key: "failed_at",
              header: "Last failed",
              render: (d) => new Date(d.last_failed_at).toLocaleString(),
            },
            {
              key: "replayed",
              header: "Replayed?",
              render: (d) => (d.replayed_at ? new Date(d.replayed_at).toLocaleString() : "no"),
            },
          ]}
        />
      )}

      {selected && (
        <section className="panel">
          <h2>Dead letter detail</h2>
          <dl className="definition-grid">
            <dt>Original event ID</dt>
            <dd>
              <code>{selected.original_event_id}</code>
            </dd>
            <dt>Error message</dt>
            <dd>{selected.error_message}</dd>
          </dl>
          <h3>Payload</h3>
          <pre className="code-block">{JSON.stringify(selected.payload, null, 2)}</pre>
          <p className="text-muted">
            Replay is a CLI-only operation in this repo (deliberately — see
            docs/phase-7-ops-dashboard.md &ldquo;Limitations&rdquo;), not wired into this dashboard:
          </p>
          <pre className="code-block">{`make replay ARGS="--id ${selected.original_event_id}"`}</pre>
        </section>
      )}
    </>
  );
}
