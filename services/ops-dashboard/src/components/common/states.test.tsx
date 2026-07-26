import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoadingState } from "./LoadingState";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { MockDataNotice } from "./MockDataNotice";
import { ApiError, NetworkError } from "../../api/client";

describe("LoadingState", () => {
  it("announces itself via role=status", () => {
    render(<LoadingState label="Loading orders…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading orders…");
  });
});

describe("EmptyState", () => {
  it("renders title, description, and an action", () => {
    render(
      <EmptyState
        title="Nothing here"
        description="Try creating one."
        action={<button>Create</button>}
      />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Try creating one.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("describes a NetworkError distinctly from a generic error", () => {
    render(<ErrorState error={new NetworkError(new Error("offline"))} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not reach the backend/i);
  });

  it("describes an ApiError with its status code", () => {
    render(<ErrorState error={new ApiError(404, "order not found")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/404/);
    expect(screen.getByRole("alert")).toHaveTextContent(/order not found/);
  });

  it("calls onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new Error("boom")} onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not render a retry button when onRetry is omitted", () => {
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("MockDataNotice", () => {
  it("always renders a visible MOCK DATA badge with the given reason", () => {
    render(<MockDataNotice reason="No read API exists yet." />);
    expect(screen.getByText("MOCK DATA")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("No read API exists yet.");
  });
});
