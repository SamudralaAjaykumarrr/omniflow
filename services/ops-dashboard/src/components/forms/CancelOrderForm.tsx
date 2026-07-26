import { useId, useState } from "react";
import type { FormEvent } from "react";
import { cancelOrder } from "../../api/orders";
import { ApiError } from "../../api/client";
import type { Order } from "../../api/types";

interface CancelOrderFormProps {
  order: Order;
  onCancelled: (order: Order) => void;
}

const CANCELLABLE_STATUSES = new Set([
  "CREATED",
  "VALIDATED",
  "INVENTORY_PENDING",
  "INVENTORY_RESERVED",
  "FULFILLMENT_ASSIGNED",
  "PROCESSING",
]);

export function CancelOrderForm({ order, onCancelled }: CancelOrderFormProps) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const formId = useId();

  const cancellable = CANCELLABLE_STATUSES.has(order.status);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const updated = await cancelOrder(order.id, { reason, expected_version: order.version });
      onCancelled(updated);
      setReason("");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to cancel order.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (!cancellable) {
    return (
      <p className="form__note">
        Order is {order.status.toLowerCase()} and can no longer be cancelled.
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="form form--inline">
      <label htmlFor={`${formId}-reason`} className="visually-hidden">
        Cancellation reason
      </label>
      <input
        id={`${formId}-reason`}
        placeholder="Reason for cancellation"
        required
        minLength={1}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button type="submit" className="btn btn--danger" disabled={submitting}>
        {submitting ? "Cancelling…" : "Cancel order"}
      </button>
      {error && (
        <p className="form__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
