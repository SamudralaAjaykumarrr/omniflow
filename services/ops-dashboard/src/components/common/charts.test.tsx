import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BarChart } from "./BarChart";
import { LineChart } from "./LineChart";

describe("BarChart", () => {
  it("renders an accessible title and one labeled bar group per datum", () => {
    render(
      <BarChart
        title="Orders by node"
        data={[
          { label: "node-a", value: 10 },
          { label: "node-b", value: 20 },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: "Orders by node" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "node-a: 10" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "node-b: 20" })).toBeInTheDocument();
  });
});

describe("LineChart", () => {
  it("renders a legend only when there are 2+ series", () => {
    const { rerender } = render(
      <LineChart
        title="Single series"
        xLabels={["a", "b"]}
        series={[{ name: "one", colorVar: "red", values: [1, 2] }]}
      />,
    );
    expect(screen.queryByText("one")).not.toBeInTheDocument();

    rerender(
      <LineChart
        title="Two series"
        xLabels={["a", "b"]}
        series={[
          { name: "actual", colorVar: "red", values: [1, 2] },
          { name: "forecast", colorVar: "blue", values: [1, 2] },
        ]}
      />,
    );
    expect(screen.getByText("actual")).toBeInTheDocument();
    expect(screen.getByText("forecast")).toBeInTheDocument();
  });

  it("breaks the line at null values rather than interpolating", () => {
    render(
      <LineChart
        title="With gaps"
        xLabels={["a", "b", "c"]}
        series={[{ name: "s", colorVar: "red", values: [1, null, 3] }]}
      />,
    );
    // Two disconnected "M" segments in the path data, not one continuous line.
    const path = document.querySelector("path");
    expect(path?.getAttribute("d")?.trim().match(/M/g)).toHaveLength(2);
  });
});
