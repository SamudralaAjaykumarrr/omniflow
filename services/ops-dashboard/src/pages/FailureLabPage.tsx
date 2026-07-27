import { useState } from "react";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { StatusBadge } from "../components/common/StatusBadge";
import { useAsync } from "../hooks/useAsync";
import { useAuth } from "../auth/useAuth";
import { listScenarios, resetScenario, triggerScenario } from "../api/failureLab";
import type { ScenarioDetail } from "../api/types";

/** Live while any scenario is RUNNING or a trigger/reset request is
 * in-flight — fast enough that a run's completion (typically well under a
 * few seconds for every one of these 10 scenarios) shows up promptly. */
const POLL_INTERVAL_MS = 3000;

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

interface ScenarioCardProps {
  detail: ScenarioDetail;
  isBusy: boolean;
  canOperate: boolean;
  onTrigger: (scenarioId: string) => void;
  onReset: (scenarioId: string) => void;
}

function ScenarioCard({ detail, isBusy, canOperate, onTrigger, onReset }: ScenarioCardProps) {
  const { catalog, latest_run: latestRun, last_reset: lastReset, run_count: runCount } = detail;
  const isRunning = latestRun?.status === "RUNNING";
  const disabled = isBusy || isRunning || !canOperate;

  return (
    <li className="scenario-card">
      <h2>{catalog.name}</h2>
      <p>{catalog.description}</p>
      <p className="text-muted">
        <strong>Expected failure behavior:</strong> {catalog.expected_failure_behavior}
      </p>
      <p className="text-muted">
        <strong>Expected recovery behavior:</strong> {catalog.expected_recovery_behavior}
      </p>
      <p className="text-muted">
        <strong>Mechanism:</strong> {catalog.mechanism_reference}
      </p>

      <dl className="definition-grid">
        <dt>Latest run</dt>
        <dd>
          {latestRun ? (
            <>
              <StatusBadge status={latestRun.status} /> #{latestRun.run_number} —{" "}
              {formatTimestamp(latestRun.completed_at ?? latestRun.started_at)}
            </>
          ) : (
            "never run"
          )}
        </dd>
        <dt>Total runs</dt>
        <dd>{runCount}</dd>
        <dt>Last reset</dt>
        <dd>{lastReset ? formatTimestamp(lastReset.reset_at) : "never reset"}</dd>
      </dl>

      {latestRun?.summary && <p>{latestRun.summary}</p>}

      {latestRun && (Object.keys(latestRun.diagnostics).length > 0 || latestRun.error_message) && (
        <details>
          <summary>Diagnostics</summary>
          {latestRun.error_message && <p className="text-critical">{latestRun.error_message}</p>}
          <pre className="code-block">{JSON.stringify(latestRun.diagnostics, null, 2)}</pre>
        </details>
      )}

      <div className="toolbar">
        <button
          type="button"
          className="btn btn--primary"
          disabled={disabled}
          onClick={() => onTrigger(catalog.id)}
        >
          {isRunning ? "Running…" : "Trigger"}
        </button>
        <button
          type="button"
          className="btn btn--secondary"
          disabled={disabled}
          onClick={() => onReset(catalog.id)}
        >
          Reset
        </button>
      </div>
    </li>
  );
}

export function FailureLabPage() {
  const { hasRole } = useAuth();
  const canOperate = hasRole("ops");
  const [busyScenarios, setBusyScenarios] = useState<Set<string>>(new Set());
  const state = useAsync(listScenarios, [], { pollIntervalMs: POLL_INTERVAL_MS });

  function setBusy(scenarioId: string, busy: boolean) {
    setBusyScenarios((prev) => {
      const next = new Set(prev);
      if (busy) next.add(scenarioId);
      else next.delete(scenarioId);
      return next;
    });
  }

  async function handleTrigger(scenarioId: string) {
    setBusy(scenarioId, true);
    try {
      await triggerScenario(scenarioId);
    } finally {
      setBusy(scenarioId, false);
      state.refetch();
    }
  }

  async function handleReset(scenarioId: string) {
    setBusy(scenarioId, true);
    try {
      await resetScenario(scenarioId);
    } finally {
      setBusy(scenarioId, false);
      state.refetch();
    }
  }

  return (
    <>
      <TopBar title="Failure Laboratory" />
      <p className="page-lede">
        Real data from the Phase 8 failure-lab service (GET /scenarios) — 10 deterministic failure
        scenarios, each safe to trigger and rerun against the live stack. Triggering places real
        orders, publishes real Kafka records, or fires real concurrent requests against
        order-service/inventory-service/fulfillment-orchestrator; nothing here is simulated
        client-side.
        {!canOperate && (
          <>
            {" "}
            Triggering/resetting requires the <code>ops</code> or <code>admin</code> role — your
            current role is read-only here.
          </>
        )}
      </p>

      {state.status === "loading" && <LoadingState label="Loading scenario catalog…" />}
      {state.status === "error" && (
        <ErrorState
          error={state.error}
          onRetry={state.refetch}
          context="the failure-lab scenario catalog"
        />
      )}
      {state.status === "success" && state.data.length === 0 && (
        <EmptyState
          title="No scenarios registered"
          description="The failure-lab backend returned an empty catalog — this shouldn't happen."
        />
      )}
      {state.status === "success" && state.data.length > 0 && (
        <ul className="scenario-grid">
          {state.data.map((detail) => (
            <ScenarioCard
              key={detail.catalog.id}
              detail={detail}
              isBusy={busyScenarios.has(detail.catalog.id)}
              canOperate={canOperate}
              onTrigger={handleTrigger}
              onReset={handleReset}
            />
          ))}
        </ul>
      )}
    </>
  );
}
