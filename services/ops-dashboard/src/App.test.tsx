import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { seedAuth } from "./test/renderWithAuth";

describe("App routing", () => {
  // This is a routing smoke test, not a data test — every screen's own
  // fetch calls are stubbed to reject immediately so pages settle into a
  // deterministic error state instead of leaving unmocked, uncontrolled
  // network calls pending across tests/unmounts.
  //
  // Phase 9 (JWT/RBAC): every route below is now gated behind RequireAuth,
  // so an unauthenticated render would redirect straight to /login instead
  // of ever reaching these screens — seed an already-authenticated session
  // first; the login gate itself is covered separately in
  // auth/RequireAuth.test.tsx.
  beforeEach(() => {
    seedAuth();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("stubbed — not under test here")));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Overview screen by default with all 10 nav links present", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    // Let the (stubbed, rejecting) overview data fetch settle before the test
    // ends, so its state update lands inside this test's act() scope.
    await screen.findByRole("alert");
    [
      "Overview",
      "Orders",
      "Inventory & Nodes",
      "Saga Monitor",
      "Dead Letter Queue",
      "Observability",
      "Data Quality",
      "Data Platform",
      "Demand Forecasting",
      "Failure Laboratory",
    ].forEach((label) => {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    });
  });

  it("navigates to the Data Quality screen when its nav link is clicked", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByRole("alert"); // let the initial Overview fetch settle first
    await userEvent.click(screen.getByRole("link", { name: /data quality/i }));
    expect(screen.getByRole("heading", { level: 1, name: "Data Quality" })).toBeInTheDocument();
  });

  it("renders the not-found page for an unknown route", () => {
    render(
      <MemoryRouter initialEntries={["/does-not-exist"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
