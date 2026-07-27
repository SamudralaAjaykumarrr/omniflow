import { API_BASE, get, post } from "./client";
import type { ScenarioDetail, ScenarioResetResult, ScenarioRun } from "./types";

const BASE = API_BASE.failureLab;

/** GET /scenarios — real Phase 8 failure-lab catalog + latest-run/reset summary per scenario. */
export function listScenarios() {
  return get<ScenarioDetail[]>(BASE, "/scenarios");
}

/** GET /scenarios/{id} */
export function getScenario(scenarioId: string) {
  return get<ScenarioDetail>(BASE, `/scenarios/${scenarioId}`);
}

/** POST /scenarios/{id}/trigger — starts a run; returns immediately with status RUNNING. */
export function triggerScenario(scenarioId: string) {
  return post<ScenarioRun>(BASE, `/scenarios/${scenarioId}/trigger`);
}

/** GET /scenarios/{id}/runs/{runId} — poll target while a run is RUNNING. */
export function getScenarioRun(scenarioId: string, runId: string) {
  return get<ScenarioRun>(BASE, `/scenarios/${scenarioId}/runs/${runId}`);
}

/** GET /scenarios/{id}/runs — recent run history, most recent first. */
export function listScenarioRuns(scenarioId: string) {
  return get<ScenarioRun[]>(BASE, `/scenarios/${scenarioId}/runs`);
}

/** POST /scenarios/{id}/reset — scenario-specific cleanup so it can be rerun cleanly. */
export function resetScenario(scenarioId: string) {
  return post<ScenarioResetResult>(BASE, `/scenarios/${scenarioId}/reset`);
}
