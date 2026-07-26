import { Link, useParams } from "react-router-dom";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { ErrorState } from "../components/common/ErrorState";
import { StatusBadge } from "../components/common/StatusBadge";
import { CancelOrderForm } from "../components/forms/CancelOrderForm";
import { useAsync } from "../hooks/useAsync";
import { getOrder, getOrderHistory } from "../api/orders";

export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const state = useAsync(async () => {
    const [order, history] = await Promise.all([getOrder(orderId), getOrderHistory(orderId)]);
    return { order, history };
  }, [orderId]);

  return (
    <>
      <TopBar title="Order detail" />
      <p className="page-lede">
        <Link to="/orders">← Back to Orders</Link>
      </p>

      {state.status === "loading" && <LoadingState label="Loading order…" />}
      {state.status === "error" && (
        <ErrorState error={state.error} onRetry={state.refetch} context={`order ${orderId}`} />
      )}
      {state.status === "success" && (
        <>
          <section className="panel">
            <h2>
              Order <code>{state.data.order.id}</code>{" "}
              <StatusBadge status={state.data.order.status} />
            </h2>
            <dl className="definition-grid">
              <dt>Customer</dt>
              <dd>{state.data.order.customer_id}</dd>
              <dt>Total</dt>
              <dd>
                {state.data.order.currency} {state.data.order.order_total.toFixed(2)}
              </dd>
              <dt>Assigned node</dt>
              <dd>{state.data.order.assigned_node_id ?? "not yet assigned"}</dd>
              <dt>Correlation ID</dt>
              <dd>
                <code>{state.data.order.correlation_id}</code>
              </dd>
              <dt>Created</dt>
              <dd>{new Date(state.data.order.created_at).toLocaleString()}</dd>
              <dt>Updated</dt>
              <dd>{new Date(state.data.order.updated_at).toLocaleString()}</dd>
            </dl>

            <h3>Items</h3>
            <table className="data-table">
              <caption className="visually-hidden">Order items</caption>
              <thead>
                <tr>
                  <th scope="col">SKU</th>
                  <th scope="col" className="data-table__cell--numeric">
                    Qty
                  </th>
                  <th scope="col" className="data-table__cell--numeric">
                    Unit price
                  </th>
                </tr>
              </thead>
              <tbody>
                {state.data.order.items.map((item) => (
                  <tr key={item.sku}>
                    <td>{item.sku}</td>
                    <td className="data-table__cell--numeric">{item.qty}</td>
                    <td className="data-table__cell--numeric">{item.unit_price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="panel">
            <h2>Cancel order</h2>
            <CancelOrderForm order={state.data.order} onCancelled={() => state.refetch()} />
          </section>

          <section className="panel">
            <h2>Status history</h2>
            {state.data.history.length === 0 ? (
              <p>No transitions recorded yet.</p>
            ) : (
              <ol className="timeline">
                {state.data.history.map((entry, i) => (
                  <li key={i} className="timeline__entry">
                    <span className="timeline__marker" aria-hidden="true" />
                    <div>
                      <p>
                        {entry.from_status ? `${entry.from_status} → ` : ""}
                        <strong>{entry.to_status}</strong>
                      </p>
                      {entry.reason && <p className="text-muted">{entry.reason}</p>}
                      <time dateTime={entry.changed_at}>
                        {new Date(entry.changed_at).toLocaleString()}
                      </time>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </>
  );
}
