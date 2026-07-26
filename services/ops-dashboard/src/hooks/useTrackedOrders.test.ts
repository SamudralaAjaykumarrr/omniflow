import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useTrackedOrders } from "./useTrackedOrders";

describe("useTrackedOrders", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts empty when nothing is stored", () => {
    const { result } = renderHook(() => useTrackedOrders());
    expect(result.current.ids).toEqual([]);
  });

  it("adds an order id and persists it to localStorage", () => {
    const { result } = renderHook(() => useTrackedOrders());
    act(() => result.current.addOrder("order-1"));
    expect(result.current.ids).toEqual(["order-1"]);
    expect(JSON.parse(window.localStorage.getItem("omniflow.trackedOrderIds") ?? "[]")).toEqual([
      "order-1",
    ]);
  });

  it("does not duplicate an already-tracked id", () => {
    const { result } = renderHook(() => useTrackedOrders());
    act(() => {
      result.current.addOrder("order-1");
      result.current.addOrder("order-1");
    });
    expect(result.current.ids).toEqual(["order-1"]);
  });

  it("removes a tracked id", () => {
    const { result } = renderHook(() => useTrackedOrders());
    act(() => result.current.addOrder("order-1"));
    act(() => result.current.removeOrder("order-1"));
    expect(result.current.ids).toEqual([]);
  });
});
