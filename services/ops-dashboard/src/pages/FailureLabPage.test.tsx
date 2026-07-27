import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FailureLabPage } from "./FailureLabPage";
import { renderWithAuth as render } from "../test/renderWithAuth";
import * as failureLabApi from "../api/failureLab";
import type { ScenarioDetail } from "../api/types";

function scenario(
  overrides: Partial<ScenarioDetail["catalog"]> = {},
  run: ScenarioDetail["latest_run"] = null,
): ScenarioDetail {
  return {
    catalog: {
      id: "payment-decline",
      name: "Payment hard decline",
      description: "Force the deterministic payment simulator to decline an in-flight order.",
      category: "saga-compensation",
      mechanism_reference: "docs/architecture.md",
      expected_failure_behavior: "compensation runs",
      expected_recovery_behavior: "order reaches FAILED",
      safe_to_rerun: true,
      ...overrides,
    },
    latest_run: run,
    last_reset: null,
    run_count: run ? 1 : 0,
  };
}

describe("FailureLabPage", () => {
  it("shows a loading state, then the real scenario catalog", async () => {
    vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([scenario()]);

    render(<FailureLabPage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText("Payment hard decline")).toBeInTheDocument();
    expect(
      screen.getByText("Force the deterministic payment simulator to decline an in-flight order."),
    ).toBeInTheDocument();
    expect(screen.getByText("never run")).toBeInTheDocument();
  });

  it("shows an error state when the catalog fails to load", async () => {
    vi.spyOn(failureLabApi, "listScenarios").mockRejectedValue(
      new Error("failure-lab unreachable"),
    );

    render(<FailureLabPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("failure-lab unreachable");
  });

  it("shows an empty state when the catalog is empty", async () => {
    vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([]);

    render(<FailureLabPage />);

    expect(await screen.findByText("No scenarios registered")).toBeInTheDocument();
  });

  it("displays the latest run's status, summary, and diagnostics", async () => {
    vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([
      scenario(undefined, {
        id: "run-1",
        scenario_id: "payment-decline",
        run_number: 3,
        status: "PASSED",
        correlation_id: "c1",
        summary: "Order failed via compensation as expected.",
        diagnostics: { saga: { status: "FAILED" } },
        resources: { order_id: "o1" },
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        completed_at: "2026-01-01T00:00:02Z",
      }),
    ]);

    render(<FailureLabPage />);

    expect(
      await screen.findByText(/Order failed via compensation as expected\./),
    ).toBeInTheDocument();
    const card = screen.getByText("Payment hard decline").closest(".scenario-card") as HTMLElement;
    expect(within(card).getByText(/PASSED/)).toBeInTheDocument();
    // Run number is interpolated inline ("#3 — <timestamp>"), split across
    // adjacent text nodes by JSX — textContent concatenates them, a single
    // getByText() match wouldn't.
    expect(card.textContent).toContain("#3");
  });

  it("disables trigger and reset while a run is RUNNING", async () => {
    vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([
      scenario(undefined, {
        id: "run-1",
        scenario_id: "payment-decline",
        run_number: 1,
        status: "RUNNING",
        correlation_id: "c1",
        summary: null,
        diagnostics: {},
        resources: {},
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        completed_at: null,
      }),
    ]);

    render(<FailureLabPage />);

    const runningButton = await screen.findByRole("button", { name: /running/i });
    expect(runningButton).toBeDisabled();
    expect(screen.getByRole("button", { name: /reset/i })).toBeDisabled();
  });

  it("triggering a scenario calls the API and refetches the catalog", async () => {
    const listSpy = vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([scenario()]);
    const triggerSpy = vi.spyOn(failureLabApi, "triggerScenario").mockResolvedValue({
      id: "run-1",
      scenario_id: "payment-decline",
      run_number: 1,
      status: "RUNNING",
      correlation_id: "c1",
      summary: null,
      diagnostics: {},
      resources: {},
      error_message: null,
      started_at: "2026-01-01T00:00:00Z",
      completed_at: null,
    });

    render(<FailureLabPage />);
    await screen.findByText("Payment hard decline");
    const callsBefore = listSpy.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: "Trigger" }));

    await waitFor(() => expect(triggerSpy).toHaveBeenCalledWith("payment-decline"));
    await waitFor(() => expect(listSpy.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("resetting a scenario calls the API and refetches the catalog", async () => {
    const listSpy = vi.spyOn(failureLabApi, "listScenarios").mockResolvedValue([scenario()]);
    const resetSpy = vi.spyOn(failureLabApi, "resetScenario").mockResolvedValue({
      scenario_id: "payment-decline",
      summary: "ok",
      reset_at: "2026-01-01T00:00:00Z",
    });

    render(<FailureLabPage />);
    await screen.findByText("Payment hard decline");
    const callsBefore = listSpy.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => expect(resetSpy).toHaveBeenCalledWith("payment-decline"));
    await waitFor(() => expect(listSpy.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});
