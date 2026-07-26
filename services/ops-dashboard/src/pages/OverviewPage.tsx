import { TopBar } from "../components/layout/TopBar";
import { StatCard } from "../components/common/StatCard";
import { StatusBadge } from "../components/common/StatusBadge";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { useAsync } from "../hooks/useAsync";
import { useTrackedOrders } from "../hooks/useTrackedOrders";
import { listSagaInstances, listDeadLetters } from "../api/orchestrator";
import { API_BASE, get } from "../api/client";
import type { HealthStatus } from "../api/types";

async function loadOverview() {
  const [gatewayReady, orchestratorHealth, sagas, deadLetters] = await Promise.all([
    get<HealthStatus>(API_BASE.gateway, "/readyz").catch(() => ({ status: "not_ready" })),
    get<HealthStatus>(API_BASE.orchestrator, "/healthz").catch(() => ({ status: "not_ready" })),
    listSagaInstances(),
    listDeadLetters(true),
  ]);
  return { gatewayReady, orchestratorHealth, sagas, deadLetters };
}

export function OverviewPage() {
  const state = useAsync(loadOverview, [], { pollIntervalMs: 15_000 });
  const { ids: trackedOrderIds } = useTrackedOrders();

  return (
    <>
      <TopBar title="Overview" />
      <p className="page-lede">
        Executive summary of live order/saga/DLQ state, pulled directly from the API Gateway and
        Fulfillment Orchestrator every 15 seconds.
      </p>

      {state.status === "loading" && <LoadingState label="Loading system overview…" />}
      {state.status === "error" && (
        <ErrorState error={state.error} onRetry={state.refetch} context="the system overview" />
      )}
      {state.status === "success" && (
        <div className="stat-grid">
          <StatCard
            label="API Gateway"
            value={
              <StatusBadge
                status={state.data.gatewayReady.status}
                label={state.data.gatewayReady.status}
              />
            }
            sublabel="order-service + inventory-service reachable"
          />
          <StatCard
            label="Fulfillment Orchestrator"
            value={
              <StatusBadge
                status={state.data.orchestratorHealth.status}
                label={state.data.orchestratorHealth.status}
              />
            }
          />
          <StatCard
            label="Sagas running"
            value={state.data.sagas.filter((s) => s.status === "RUNNING").length}
          />
          <StatCard
            label="Sagas completed"
            value={state.data.sagas.filter((s) => s.status === "COMPLETED").length}
            tone="good"
          />
          <StatCard
            label="Sagas failed"
            value={state.data.sagas.filter((s) => s.status === "FAILED").length}
            tone={state.data.sagas.some((s) => s.status === "FAILED") ? "critical" : undefined}
          />
          <StatCard
            label="Unreplayed dead letters"
            value={state.data.deadLetters.length}
            tone={state.data.deadLetters.length > 0 ? "warning" : "good"}
          />
          <StatCard
            label="Orders tracked this session"
            value={trackedOrderIds.length}
            sublabel="client-curated (see Orders screen)"
          />
        </div>
      )}
    </>
  );
}
