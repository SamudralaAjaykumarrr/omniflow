import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getScenario,
  getScenarioRun,
  listScenarioRuns,
  listScenarios,
  resetScenario,
  triggerScenario,
} from "./failureLab";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/failureLab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listScenarios GETs /failure-lab-api/scenarios", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse([{ catalog: { id: "payment-decline" } }]));
    vi.stubGlobal("fetch", fetchMock);

    const result = await listScenarios();

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result[0].catalog.id).toBe("payment-decline");
  });

  it("getScenario GETs /failure-lab-api/scenarios/{id}", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ catalog: { id: "payment-decline" } }));
    vi.stubGlobal("fetch", fetchMock);

    await getScenario("payment-decline");

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios/payment-decline",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("triggerScenario POSTs /failure-lab-api/scenarios/{id}/trigger", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "run-1", status: "RUNNING" }, 202));
    vi.stubGlobal("fetch", fetchMock);

    const run = await triggerScenario("payment-decline");

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios/payment-decline/trigger",
      expect.objectContaining({ method: "POST" }),
    );
    expect(run.status).toBe("RUNNING");
  });

  it("getScenarioRun GETs /failure-lab-api/scenarios/{id}/runs/{runId}", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "run-1", status: "PASSED" }));
    vi.stubGlobal("fetch", fetchMock);

    const run = await getScenarioRun("payment-decline", "run-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios/payment-decline/runs/run-1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(run.status).toBe("PASSED");
  });

  it("listScenarioRuns GETs /failure-lab-api/scenarios/{id}/runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([{ id: "run-1" }]));
    vi.stubGlobal("fetch", fetchMock);

    await listScenarioRuns("payment-decline");

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios/payment-decline/runs",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("resetScenario POSTs /failure-lab-api/scenarios/{id}/reset", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ scenario_id: "payment-decline", summary: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await resetScenario("payment-decline");

    expect(fetchMock).toHaveBeenCalledWith(
      "/failure-lab-api/scenarios/payment-decline/reset",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.summary).toBe("ok");
  });
});
