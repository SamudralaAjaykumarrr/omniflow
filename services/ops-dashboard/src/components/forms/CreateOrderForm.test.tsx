import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CreateOrderForm } from "./CreateOrderForm";
import * as ordersApi from "../../api/orders";
import type { Order } from "../../api/types";

const MOCK_ORDER: Order = {
  id: "order-1",
  customer_id: "cust-1",
  status: "CREATED",
  version: 1,
  correlation_id: "corr-1",
  assigned_node_id: null,
  order_total: 10,
  currency: "USD",
  items: [{ sku: "SKU-1", qty: 1, unit_price: 10 }],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("CreateOrderForm", () => {
  it("submits with the entered SKU and calls onCreated with the resulting order", async () => {
    const createOrderSpy = vi.spyOn(ordersApi, "createOrder").mockResolvedValue(MOCK_ORDER);
    const onCreated = vi.fn();
    render(<CreateOrderForm onCreated={onCreated} />);

    await userEvent.type(screen.getByPlaceholderText("SKU"), "SKU-1");
    await userEvent.click(screen.getByRole("button", { name: /create order/i }));

    expect(createOrderSpy).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: /create order/i })).toBeEnabled();
    expect(onCreated).toHaveBeenCalledWith(MOCK_ORDER);
  });

  it("shows a validation error instead of submitting when a SKU is only whitespace", async () => {
    // The SKU input also has the native `required` attribute, which blocks
    // submission for a literally-empty value before React ever sees the
    // submit event — so this exercises the custom trim() check specifically
    // (a whitespace-only value passes native validation but not this one).
    const createOrderSpy = vi.spyOn(ordersApi, "createOrder").mockResolvedValue(MOCK_ORDER);
    render(<CreateOrderForm onCreated={vi.fn()} />);

    await userEvent.type(screen.getByPlaceholderText("SKU"), "   ");
    await userEvent.click(screen.getByRole("button", { name: /create order/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/needs a sku/i);
    expect(createOrderSpy).not.toHaveBeenCalled();
  });

  it("surfaces the backend's error message when creation fails", async () => {
    vi.spyOn(ordersApi, "createOrder").mockRejectedValue(new Error("gateway unreachable"));
    render(<CreateOrderForm onCreated={vi.fn()} />);

    await userEvent.type(screen.getByPlaceholderText("SKU"), "SKU-1");
    await userEvent.click(screen.getByRole("button", { name: /create order/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("gateway unreachable");
  });
});
