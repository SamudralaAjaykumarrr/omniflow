import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CancelOrderForm } from "./CancelOrderForm";
import * as ordersApi from "../../api/orders";
import type { Order } from "../../api/types";

function makeOrder(overrides: Partial<Order>): Order {
  return {
    id: "order-1",
    customer_id: "cust-1",
    status: "CREATED",
    version: 1,
    correlation_id: "corr-1",
    assigned_node_id: null,
    order_total: 10,
    currency: "USD",
    items: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CancelOrderForm", () => {
  it("renders a cancel form for a cancellable order", () => {
    render(<CancelOrderForm order={makeOrder({ status: "CREATED" })} onCancelled={vi.fn()} />);
    expect(screen.getByRole("button", { name: /cancel order/i })).toBeInTheDocument();
  });

  it("renders a note instead of a form for a terminal order", () => {
    render(<CancelOrderForm order={makeOrder({ status: "SHIPPED" })} onCancelled={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /cancel order/i })).not.toBeInTheDocument();
    expect(screen.getByText(/can no longer be cancelled/i)).toBeInTheDocument();
  });

  it("submits the reason and expected_version, then calls onCancelled", async () => {
    const order = makeOrder({ status: "CREATED", version: 3 });
    const cancelled = makeOrder({ status: "CANCELLED", version: 4 });
    const cancelOrderSpy = vi.spyOn(ordersApi, "cancelOrder").mockResolvedValue(cancelled);
    const onCancelled = vi.fn();

    render(<CancelOrderForm order={order} onCancelled={onCancelled} />);
    await userEvent.type(
      screen.getByPlaceholderText(/reason for cancellation/i),
      "changed my mind",
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel order/i }));

    expect(cancelOrderSpy).toHaveBeenCalledWith("order-1", {
      reason: "changed my mind",
      expected_version: 3,
    });
    expect(onCancelled).toHaveBeenCalledWith(cancelled);
  });
});
