import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders a good tone for a terminal success status", () => {
    render(<StatusBadge status="SHIPPED" />);
    expect(screen.getByText(/SHIPPED/)).toHaveClass("status-badge--good");
  });

  it("renders a critical tone for FAILED", () => {
    render(<StatusBadge status="FAILED" />);
    expect(screen.getByText(/FAILED/)).toHaveClass("status-badge--critical");
  });

  it("renders a warning tone for an in-progress status", () => {
    render(<StatusBadge status="PROCESSING" />);
    expect(screen.getByText(/PROCESSING/)).toHaveClass("status-badge--warning");
  });

  it("uses the provided label over the raw status", () => {
    render(<StatusBadge status="ACTIVE" label="active" />);
    expect(screen.getByText(/active/)).toBeInTheDocument();
  });
});
