import { useId, useState } from "react";
import type { FormEvent } from "react";
import { TopBar } from "../components/layout/TopBar";
import { LoadingState } from "../components/common/LoadingState";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorState } from "../components/common/ErrorState";
import { DataTable } from "../components/common/DataTable";
import { StatusBadge } from "../components/common/StatusBadge";
import { StockCheckForm } from "../components/forms/StockCheckForm";
import { useAsync } from "../hooks/useAsync";
import { listFulfillmentNodes, getStock } from "../api/inventory";
import { ApiError } from "../api/client";
import type { Stock } from "../api/types";

export function InventoryPage() {
  const nodesState = useAsync(listFulfillmentNodes, []);
  const [sku, setSku] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [lookup, setLookup] = useState<{
    status: "idle" | "loading" | "error" | "success";
    stock?: Stock;
    error?: string;
  }>({
    status: "idle",
  });
  const formId = useId();

  async function handleLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLookup({ status: "loading" });
    try {
      const stock = await getStock(sku.trim(), nodeId.trim());
      setLookup({ status: "success", stock });
    } catch (err) {
      setLookup({
        status: "error",
        error:
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Lookup failed.",
      });
    }
  }

  return (
    <>
      <TopBar title="Inventory & Fulfillment Nodes" />
      <p className="page-lede">
        Real data from Inventory Service — nodes, per-SKU stock lookup, and the advisory stock
        pre-check.
      </p>

      <section className="panel">
        <h2>Fulfillment nodes</h2>
        {nodesState.status === "loading" && <LoadingState label="Loading fulfillment nodes…" />}
        {nodesState.status === "error" && (
          <ErrorState
            error={nodesState.error}
            onRetry={nodesState.refetch}
            context="fulfillment nodes"
          />
        )}
        {nodesState.status === "success" && nodesState.data.length === 0 && (
          <EmptyState
            title="No fulfillment nodes configured"
            description="Seed a node via POST /fulfillment-nodes."
          />
        )}
        {nodesState.status === "success" && nodesState.data.length > 0 && (
          <DataTable
            caption="Fulfillment nodes"
            rows={nodesState.data}
            getRowKey={(n) => n.id}
            columns={[
              { key: "name", header: "Name", render: (n) => n.name },
              {
                key: "backlog",
                header: "Backlog",
                numeric: true,
                render: (n) => n.current_backlog,
              },
              {
                key: "capacity",
                header: "Capacity/day",
                numeric: true,
                render: (n) => n.capacity_per_day,
              },
              {
                key: "active",
                header: "Status",
                render: (n) => (
                  <StatusBadge
                    status={n.active ? "ACTIVE" : "inactive"}
                    label={n.active ? "active" : "inactive"}
                  />
                ),
              },
            ]}
          />
        )}
      </section>

      <section className="panel">
        <h2>Stock lookup</h2>
        <form className="form form--inline" onSubmit={handleLookup}>
          <label htmlFor={`${formId}-sku`} className="visually-hidden">
            SKU
          </label>
          <input
            id={`${formId}-sku`}
            placeholder="SKU"
            required
            value={sku}
            onChange={(e) => setSku(e.target.value)}
          />
          <label htmlFor={`${formId}-node`} className="visually-hidden">
            Node ID
          </label>
          <input
            id={`${formId}-node`}
            placeholder="Node UUID"
            required
            value={nodeId}
            onChange={(e) => setNodeId(e.target.value)}
          />
          <button
            type="submit"
            className="btn btn--secondary"
            disabled={lookup.status === "loading"}
          >
            {lookup.status === "loading" ? "Looking up…" : "Look up stock"}
          </button>
        </form>
        {lookup.status === "error" && (
          <ErrorState error={new Error(lookup.error)} context="stock lookup" />
        )}
        {lookup.status === "success" && lookup.stock && (
          <dl className="definition-grid">
            <dt>Available</dt>
            <dd>{lookup.stock.available_qty}</dd>
            <dt>Reserved</dt>
            <dd>{lookup.stock.reserved_qty}</dd>
            <dt>Committed</dt>
            <dd>{lookup.stock.committed_qty}</dd>
            <dt>Reorder threshold</dt>
            <dd>{lookup.stock.reorder_threshold}</dd>
            <dt>Stockout risk</dt>
            <dd>
              {lookup.stock.available_qty <= lookup.stock.reorder_threshold ? (
                <StatusBadge status="warning" label="at or below reorder threshold" />
              ) : (
                <StatusBadge status="good" label="healthy" />
              )}
            </dd>
          </dl>
        )}
      </section>

      <section className="panel">
        <h2>Advisory stock pre-check</h2>
        <p className="text-muted">
          Mirrors the saga&rsquo;s own POST /stock/check step (multi-item, single node).
        </p>
        {nodesState.status === "success" && nodesState.data.length > 0 ? (
          <StockCheckForm nodes={nodesState.data} />
        ) : (
          <p className="text-muted">Load fulfillment nodes above first.</p>
        )}
      </section>
    </>
  );
}
