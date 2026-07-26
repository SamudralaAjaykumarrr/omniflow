import { useId, useState } from "react";
import type { FormEvent } from "react";
import { checkStock } from "../../api/inventory";
import { ApiError } from "../../api/client";
import type { FulfillmentNode, StockCheckResult } from "../../api/types";

interface StockCheckFormProps {
  nodes: FulfillmentNode[];
}

export function StockCheckForm({ nodes }: StockCheckFormProps) {
  const [nodeId, setNodeId] = useState(nodes[0]?.id ?? "");
  const [sku, setSku] = useState("");
  const [qty, setQty] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StockCheckResult | null>(null);
  const formId = useId();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const response = await checkStock(nodeId, [{ sku: sku.trim(), qty }]);
      setResult(response);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Stock check failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="form form--inline">
      <label htmlFor={`${formId}-node`} className="visually-hidden">
        Fulfillment node
      </label>
      <select
        id={`${formId}-node`}
        value={nodeId}
        onChange={(e) => setNodeId(e.target.value)}
        required
      >
        {nodes.map((node) => (
          <option key={node.id} value={node.id}>
            {node.name}
          </option>
        ))}
      </select>
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
      <label htmlFor={`${formId}-qty`} className="visually-hidden">
        Quantity
      </label>
      <input
        id={`${formId}-qty`}
        type="number"
        min={1}
        required
        value={qty}
        onChange={(e) => setQty(Number(e.target.value))}
      />
      <button type="submit" className="btn btn--secondary" disabled={submitting || !nodeId}>
        {submitting ? "Checking…" : "Check stock"}
      </button>

      {error && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
      {result && (
        <p
          className={`form__note ${result.sufficient ? "form__note--good" : "form__note--warning"}`}
          role="status"
        >
          {result.sufficient
            ? "Sufficient stock at this node."
            : `Insufficient stock: ${result.shortfalls
                .map((s) => `${s.sku} (requested ${s.requested_qty}, available ${s.available_qty})`)
                .join(", ")}`}
        </p>
      )}
    </form>
  );
}
