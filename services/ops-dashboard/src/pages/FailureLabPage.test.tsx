import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FailureLabPage } from "./FailureLabPage";
import { FAILURE_LAB_SCENARIOS } from "../api/mock/failureLab";

describe("FailureLabPage", () => {
  it("renders every planned scenario with a disabled trigger button", () => {
    render(<FailureLabPage />);
    expect(screen.getByText("MOCK DATA")).toBeInTheDocument();

    const triggerButtons = screen.getAllByRole("button", { name: /trigger/i });
    expect(triggerButtons).toHaveLength(FAILURE_LAB_SCENARIOS.length);
    triggerButtons.forEach((button) => expect(button).toBeDisabled());
  });
});
