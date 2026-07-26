import { useId, useState } from "react";
import type { FormEvent } from "react";
import { createOrder } from "../../api/orders";
import { ApiError } from "../../api/client";
import type { CreateOrderItemInput, Order } from "../../api/types";

interface CreateOrderFormProps {
  onCreated: (order: Order) => void;
}

interface ItemRow extends CreateOrderItemInput {
  key: string;
}

function newItemRow(): ItemRow {
  return { key: crypto.randomUUID(), sku: "", qty: 1, unit_price: 0 };
}

export function CreateOrderForm({ onCreated }: CreateOrderFormProps) {
  const [customerId] = useState(() => crypto.randomUUID());
  const [email, setEmail] = useState("demo.customer@example.com");
  const [displayName, setDisplayName] = useState("Demo Customer");
  const [items, setItems] = useState<ItemRow[]>([newItemRow()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const formId = useId();

  function updateItem(key: string, patch: Partial<ItemRow>) {
    setItems((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  function removeItem(key: string) {
    setItems((prev) => (prev.length > 1 ? prev.filter((row) => row.key !== key) : prev));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (items.some((row) => !row.sku.trim())) {
      setError("Every line item needs a SKU.");
      return;
    }

    setSubmitting(true);
    try {
      const order = await createOrder(
        {
          customer_id: customerId,
          customer_email: email,
          customer_display_name: displayName,
          items: items.map(({ sku, qty, unit_price }) => ({ sku: sku.trim(), qty, unit_price })),
          currency: "USD",
        },
        crypto.randomUUID(),
      );
      onCreated(order);
      setItems([newItemRow()]);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Failed to create order.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="form"
      aria-describedby={error ? `${formId}-error` : undefined}
    >
      <div className="form__row">
        <label htmlFor={`${formId}-email`}>Customer email</label>
        <input
          id={`${formId}-email`}
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="form__row">
        <label htmlFor={`${formId}-name`}>Customer name</label>
        <input
          id={`${formId}-name`}
          type="text"
          required
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>

      <fieldset className="form__fieldset">
        <legend>Line items</legend>
        {items.map((row, index) => (
          <div className="form__item-row" key={row.key}>
            <label htmlFor={`${formId}-sku-${index}`} className="visually-hidden">
              SKU for item {index + 1}
            </label>
            <input
              id={`${formId}-sku-${index}`}
              placeholder="SKU"
              required
              value={row.sku}
              onChange={(e) => updateItem(row.key, { sku: e.target.value })}
            />
            <label htmlFor={`${formId}-qty-${index}`} className="visually-hidden">
              Quantity for item {index + 1}
            </label>
            <input
              id={`${formId}-qty-${index}`}
              type="number"
              min={1}
              required
              value={row.qty}
              onChange={(e) => updateItem(row.key, { qty: Number(e.target.value) })}
            />
            <label htmlFor={`${formId}-price-${index}`} className="visually-hidden">
              Unit price for item {index + 1}
            </label>
            <input
              id={`${formId}-price-${index}`}
              type="number"
              min={0}
              step="0.01"
              required
              value={row.unit_price}
              onChange={(e) => updateItem(row.key, { unit_price: Number(e.target.value) })}
            />
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => removeItem(row.key)}
              disabled={items.length === 1}
              aria-label={`Remove item ${index + 1}`}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn--secondary"
          onClick={() => setItems((prev) => [...prev, newItemRow()])}
        >
          Add item
        </button>
      </fieldset>

      {error && (
        <p id={`${formId}-error`} className="form__error" role="alert">
          {error}
        </p>
      )}

      <button type="submit" className="btn btn--primary" disabled={submitting}>
        {submitting ? "Creating…" : "Create order"}
      </button>
    </form>
  );
}
