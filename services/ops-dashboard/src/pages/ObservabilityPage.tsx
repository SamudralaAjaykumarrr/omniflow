import { TopBar } from "../components/layout/TopBar";
import { StatCard } from "../components/common/StatCard";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { EmptyState } from "../components/common/EmptyState";
import { BarChart } from "../components/common/BarChart";
import { LineChart } from "../components/common/LineChart";
import { useAsync } from "../hooks/useAsync";
import { firstValue, instantQuery, rangeQuery, sumValues } from "../api/metrics";

/** Real PromQL against this repo's own metric names — see
 * services/event-contracts/event_contracts/metrics_setup.py,
 * services/inventory-service/app/metrics.py,
 * services/fulfillment-orchestrator/app/metrics.py. */
const QUERIES = {
  requestRateByJob: "sum by (job) (rate(http_requests_total[5m]))",
  p95LatencySeconds:
    "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))",
  kafkaLagByTopic: "max by (topic) (kafka_consumer_lag)",
  kafkaRetriesTotal: "sum(kafka_consumer_retry_total)",
  kafkaDeadLettersTotal: "sum(kafka_dead_letter_total)",
  dbPoolCheckedOutByJob: "sum by (job) (db_pool_checked_out_connections)",
  inventoryConflictsTotal: "sum(inventory_reservation_conflicts_total)",
  sagaDurationP50: "histogram_quantile(0.5, sum by (le) (rate(saga_duration_seconds_bucket[10m])))",
};

async function loadObservability() {
  const now = Math.floor(Date.now() / 1000);
  const [
    requestRateByJob,
    p95Latency,
    kafkaLagByTopic,
    kafkaRetries,
    kafkaDeadLetters,
    dbPoolByJob,
    inventoryConflicts,
    sagaDurationP50,
    requestRateTrend,
  ] = await Promise.all([
    instantQuery(QUERIES.requestRateByJob),
    instantQuery(QUERIES.p95LatencySeconds),
    instantQuery(QUERIES.kafkaLagByTopic),
    instantQuery(QUERIES.kafkaRetriesTotal),
    instantQuery(QUERIES.kafkaDeadLettersTotal),
    instantQuery(QUERIES.dbPoolCheckedOutByJob),
    instantQuery(QUERIES.inventoryConflictsTotal),
    instantQuery(QUERIES.sagaDurationP50),
    rangeQuery("sum(rate(http_requests_total[2m]))", now - 900, now, 30),
  ]);
  return {
    requestRateByJob,
    p95Latency,
    kafkaLagByTopic,
    kafkaRetries,
    kafkaDeadLetters,
    dbPoolByJob,
    inventoryConflicts,
    sagaDurationP50,
    requestRateTrend,
  };
}

export function ObservabilityPage() {
  const state = useAsync(loadObservability, [], { pollIntervalMs: 15_000 });

  return (
    <>
      <TopBar title="Observability / Pipeline Health" />
      <p className="page-lede">
        Live PromQL queries against this stack&rsquo;s own Prometheus (same metric names
        Grafana&rsquo;s provisioned dashboard uses) — see the Grafana/Jaeger links above for full
        trace/dashboard detail.
      </p>

      {state.status === "loading" && <LoadingState label="Querying Prometheus…" />}
      {state.status === "error" && (
        <ErrorState error={state.error} onRetry={state.refetch} context="Prometheus metrics" />
      )}
      {state.status === "success" && (
        <>
          <div className="stat-grid">
            <StatCard
              label="Total request rate"
              value={`${sumValues(state.data.requestRateByJob).toFixed(2)} req/s`}
            />
            <StatCard
              label="p95 HTTP latency"
              value={`${((firstValue(state.data.p95Latency) ?? 0) * 1000).toFixed(0)} ms`}
            />
            <StatCard
              label="Kafka consumer retries"
              value={firstValue(state.data.kafkaRetries) ?? 0}
            />
            <StatCard
              label="Kafka dead letters"
              value={firstValue(state.data.kafkaDeadLetters) ?? 0}
              tone={(firstValue(state.data.kafkaDeadLetters) ?? 0) > 0 ? "warning" : "good"}
            />
            <StatCard
              label="Inventory reservation conflicts"
              value={firstValue(state.data.inventoryConflicts) ?? 0}
            />
            <StatCard
              label="Saga duration (p50)"
              value={
                state.data.sagaDurationP50.length
                  ? `${(firstValue(state.data.sagaDurationP50) ?? 0).toFixed(2)} s`
                  : "no data yet"
              }
            />
          </div>

          <section className="panel">
            <h2>Request rate by service (5m rate)</h2>
            {state.data.requestRateByJob.length === 0 ? (
              <EmptyState
                title="No request-rate samples yet"
                description="Traffic hasn't hit any service since the last scrape."
              />
            ) : (
              <BarChart
                title="Request rate by service"
                data={state.data.requestRateByJob.map((s) => ({
                  label: s.metric.job ?? "unknown",
                  value: Number(s.value[1]),
                }))}
                valueFormat={(v) => `${v.toFixed(2)}/s`}
              />
            )}
          </section>

          <section className="panel">
            <h2>Request rate — last 15 minutes</h2>
            {state.data.requestRateTrend.length === 0 ||
            state.data.requestRateTrend[0].values.length === 0 ? (
              <EmptyState
                title="No trend data yet"
                description="Not enough scrape history in the last 15 minutes."
              />
            ) : (
              <LineChart
                title="Request rate trend"
                xLabels={state.data.requestRateTrend[0].values.map(([ts]) =>
                  new Date(ts * 1000).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  }),
                )}
                series={[
                  {
                    name: "requests/sec",
                    colorVar: "var(--series-1)",
                    values: state.data.requestRateTrend[0].values.map(([, v]) => Number(v)),
                  },
                ]}
                valueFormat={(v) => `${v.toFixed(2)}/s`}
              />
            )}
          </section>

          <section className="panel">
            <h2>Kafka consumer lag by topic</h2>
            {state.data.kafkaLagByTopic.length === 0 ? (
              <EmptyState
                title="No consumer-lag samples yet"
                description="Run make generate or make smoke to produce traffic."
              />
            ) : (
              <BarChart
                title="Kafka consumer lag by topic"
                colorVar="var(--series-2)"
                data={state.data.kafkaLagByTopic.map((s) => ({
                  label: s.metric.topic ?? "unknown",
                  value: Number(s.value[1]),
                }))}
              />
            )}
          </section>

          <section className="panel">
            <h2>DB connection pool (checked out) by service</h2>
            {state.data.dbPoolByJob.length === 0 ? (
              <EmptyState title="No DB pool samples yet" />
            ) : (
              <BarChart
                title="DB pool checked-out connections by service"
                colorVar="var(--series-3)"
                data={state.data.dbPoolByJob.map((s) => ({
                  label: s.metric.job ?? "unknown",
                  value: Number(s.value[1]),
                }))}
              />
            )}
          </section>
        </>
      )}
    </>
  );
}
