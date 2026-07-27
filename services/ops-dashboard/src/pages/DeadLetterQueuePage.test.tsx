import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DeadLetterQueuePage } from "./DeadLetterQueuePage";
import { renderWithAuth as render } from "../test/renderWithAuth";
import * as orchestratorApi from "../api/orchestrator";
import type { DeadLetterEvent } from "../api/types";

function deadLetter(overrides: Partial<DeadLetterEvent> = {}): DeadLetterEvent {
  return {
    id: "dl-1",
    original_event_id: "evt-1",
    event_type: "order.validated",
    failed_consumer: "fulfillment-orchestrator",
    error_type: "RemoteServiceError",
    error_message: "503 Service Unavailable",
    attempt_count: 5,
    payload: { data: { order_id: "order-1" } },
    first_failed_at: "2026-01-01T00:00:00Z",
    last_failed_at: "2026-01-01T00:00:05Z",
    replayed_at: null,
    ...overrides,
  };
}

describe("DeadLetterQueuePage", () => {
  it("shows an empty state when there are no dead letters", async () => {
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([]);
    render(<DeadLetterQueuePage />);
    expect(await screen.findByText("No dead-lettered events")).toBeInTheDocument();
  });

  it("selecting a row shows a working Replay button for an unreplayed event", async () => {
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([deadLetter()]);
    const replaySpy = vi
      .spyOn(orchestratorApi, "replayDeadLetter")
      .mockResolvedValue(deadLetter({ replayed_at: "2026-01-01T00:10:00Z" }));

    render(<DeadLetterQueuePage />);
    const row = await screen.findByText("order.validated");
    await userEvent.click(row);

    const replayButton = await screen.findByRole("button", { name: "Replay" });
    await userEvent.click(replayButton);

    expect(replaySpy).toHaveBeenCalledWith("dl-1");
    expect(await screen.findByText(/Replayed at/)).toBeInTheDocument();
  });

  it("already-replayed events show the timestamp instead of a Replay button", async () => {
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([
      deadLetter({ replayed_at: "2026-01-01T00:10:00Z" }),
    ]);

    render(<DeadLetterQueuePage />);
    const row = await screen.findByText("order.validated");
    await userEvent.click(row);

    expect(await screen.findByText(/Replayed at/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("shows an error state if replay fails", async () => {
    vi.spyOn(orchestratorApi, "listDeadLetters").mockResolvedValue([deadLetter()]);
    vi.spyOn(orchestratorApi, "replayDeadLetter").mockRejectedValue(new Error("replay boom"));

    render(<DeadLetterQueuePage />);
    const row = await screen.findByText("order.validated");
    await userEvent.click(row);
    await userEvent.click(await screen.findByRole("button", { name: "Replay" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("replay boom");
  });
});
