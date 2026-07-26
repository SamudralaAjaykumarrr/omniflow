import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataQualityPage } from "./DataQualityPage";

describe("DataQualityPage", () => {
  it("renders the mock-data notice and the reconciliation table", () => {
    render(<DataQualityPage />);
    expect(screen.getByText("MOCK DATA")).toBeInTheDocument();
    expect(screen.getByText("order.created")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Bronze count" })).toBeInTheDocument();
  });
});
