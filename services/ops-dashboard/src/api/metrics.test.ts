import { afterEach, describe, expect, it, vi } from "vitest";
import { firstValue, instantQuery, sumValues } from "./metrics";

function prometheusResponse(result: unknown[]) {
  return new Response(
    JSON.stringify({ status: "success", data: { resultType: "vector", result } }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

describe("api/metrics", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("instantQuery returns the result array on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          prometheusResponse([{ metric: { job: "api-gateway" }, value: [1690000000, "3.5"] }]),
        ),
    );
    const result = await instantQuery("sum(rate(http_requests_total[5m]))");
    expect(result).toHaveLength(1);
    expect(result[0].metric.job).toBe("api-gateway");
  });

  it("instantQuery throws when Prometheus reports an error status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "error",
            error: "bad query",
            data: { resultType: "", result: [] },
          }),
          {
            status: 200,
          },
        ),
      ),
    );
    await expect(instantQuery("bad{")).rejects.toThrow("bad query");
  });

  it("firstValue returns undefined for an empty result set", () => {
    expect(firstValue([])).toBeUndefined();
  });

  it("firstValue parses the first sample's value as a number", () => {
    expect(firstValue([{ metric: {}, value: [0, "42.5"] }])).toBe(42.5);
  });

  it("sumValues adds every sample's value", () => {
    expect(
      sumValues([
        { metric: {}, value: [0, "1.5"] },
        { metric: {}, value: [0, "2.5"] },
      ]),
    ).toBe(4);
  });
});
