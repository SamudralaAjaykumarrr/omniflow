import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { StatusBadge } from "../components/common/StatusBadge";
import { DataTable } from "../components/common/DataTable";
import { CreateOrderForm } from "../components/forms/CreateOrderForm";
import { useAsync } from "../hooks/useAsync";
import { useTrackedOrders } from "../hooks/useTrackedOrders";
import { useAuth } from "../auth/useAuth";
import { getOrder } from "../api/orders";
import type { Order } from "../api/types";

interface TrackedOrderResult {
  id: string;
  order: Order | null;
  errorMessage: string | null;
}

async function loadTrackedOrders(ids: string[]): Promise<TrackedOrderResult[]> {
  const results = await Promise.allSettled(ids.map((id) => getOrder(id)));
  return results.map((result, i) => ({
    id: ids[i],
    order: result.status === "fulfilled" ? result.value : null,
    errorMessage: result.status === "rejected" ? (result.reason as Error).message : null,
  }));
}

export function OrdersPage() {
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const { ids, addOrder, removeOrder } = useTrackedOrders();
  const [manualId, setManualId] = useState("");
  const state = useAsync(() => loadTrackedOrders(ids), [ids.join(",")]);

  return (
    <>
      <TopBar title="Orders" />
      <p className="page-lede">
        Order Service has no list-all endpoint (checked: only single-order lookup and history), so
        this screen tracks order IDs client-side — created here or entered manually — and fetches
        each one&rsquo;s real current state from the API Gateway.
      </p>

      <section className="panel">
        <h2>Create a demo order</h2>
        {hasRole("ops") ? (
          <CreateOrderForm
            onCreated={(order) => {
              addOrder(order.id);
              navigate(`/orders/${order.id}`);
            }}
          />
        ) : (
          <p className="form__note">
            Creating an order requires the <code>ops</code> or <code>admin</code> role — the API
            Gateway would reject this with a 403 for your current role.
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Track an existing order by ID</h2>
        <form
          className="form form--inline"
          onSubmit={(e) => {
            e.preventDefault();
            if (manualId.trim()) {
              addOrder(manualId.trim());
              setManualId("");
            }
          }}
        >
          <label htmlFor="manual-order-id" className="visually-hidden">
            Order ID
          </label>
          <input
            id="manual-order-id"
            placeholder="Order UUID"
            value={manualId}
            onChange={(e) => setManualId(e.target.value)}
          />
          <button type="submit" className="btn btn--secondary">
            Track
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>Tracked orders</h2>
        {ids.length === 0 && (
          <EmptyState
            title="No orders tracked yet"
            description="Create a demo order above, or track an existing order by ID."
          />
        )}
        {ids.length > 0 && state.status === "loading" && (
          <LoadingState label="Loading tracked orders…" />
        )}
        {ids.length > 0 && state.status === "error" && (
          <ErrorState error={state.error} onRetry={state.refetch} context="tracked orders" />
        )}
        {ids.length > 0 && state.status === "success" && (
          <DataTable
            caption="Tracked orders"
            rows={state.data}
            getRowKey={(row) => row.id}
            onRowActivate={(row) => row.order && navigate(`/orders/${row.id}`)}
            columns={[
              {
                key: "id",
                header: "Order ID",
                render: (row) => <code>{row.id.slice(0, 8)}…</code>,
              },
              {
                key: "status",
                header: "Status",
                render: (row) =>
                  row.order ? (
                    <StatusBadge status={row.order.status} />
                  ) : (
                    <span className="text-muted">not found</span>
                  ),
              },
              {
                key: "total",
                header: "Total",
                numeric: true,
                render: (row) =>
                  row.order ? `${row.order.currency} ${row.order.order_total.toFixed(2)}` : "—",
              },
              {
                key: "updated",
                header: "Updated",
                render: (row) =>
                  row.order
                    ? new Date(row.order.updated_at).toLocaleString()
                    : (row.errorMessage ?? "—"),
              },
              {
                key: "actions",
                header: "Actions",
                render: (row) => (
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeOrder(row.id);
                    }}
                  >
                    Stop tracking
                  </button>
                ),
              },
            ]}
          />
        )}
      </section>
    </>
  );
}
