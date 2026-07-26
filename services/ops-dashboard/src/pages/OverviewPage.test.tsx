import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";
import * as orchestratorApi from "../api/orchestrator";
import * as clientApi from "../api/client";
import type { SagaInstance, DeadLetterEvent } from "../api/types";

function saga(overrides: Partial<SagaInstance>): SagaInstance {
  return {
    id: "s1",
    order_id: "o1",
    correlation_id: "c1",
    current_step: "SELECT_AND_RESERVE",
    status: "RUNNING",
    attempt_count: 1,
    last_error: null,
    context: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("OverviewPage", () => {
  it("shows a loading state, then the computed saga/DLQ stat cards", async () => {
    vi.spyOn(clientApi, "get").mockResolvedValue({ status: "ready" });
    vi.spyOn(orchestratorApi, "listSagaInstances").mockResolvedValue([
      saga({ id: "s1", status: "RUNNING" }),
      saga({ id: "s2", status: "COMPLETED" }),
      saga({ id: "s3", status: "FAILED" }),
    ]);
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([] as DeadLetterEvent[]);

    render(<OverviewPage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    const runningCard = (await screen.findByText("Sagas running")).closest(".stat-card");
    expect(runningCard).not.toBeNull();
    expect(within(runningCard as HTMLElement).getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Unreplayed dead letters")).toBeInTheDocument();
  });

  it("shows an error state when the overview fails to load", async () => {
    vi.spyOn(clientApi, "get").mockResolvedValue({ status: "ready" });
    vi.spyOn(orchestratorApi, "listSagaInstances").mockRejectedValue(
      new Error("orchestrator down"),
    );
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([]);

    render(<OverviewPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("orchestrator down");
  });
});
