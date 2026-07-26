import { TopBar } from "../components/layout/TopBar";
import { MockDataNotice } from "../components/common/MockDataNotice";
import { FAILURE_LAB_SCENARIOS } from "../api/mock/failureLab";

export function FailureLabPage() {
  return (
    <>
      <TopBar title="Failure Laboratory" />
      <MockDataNotice reason="Phase 8 (Failure laboratory) is listed “Not started” in PROJECT_STATUS.md — there is no backend to trigger these scenarios yet. This is an inert preview of the planned catalog, not a working control panel." />

      <ul className="scenario-grid">
        {FAILURE_LAB_SCENARIOS.map((scenario) => (
          <li key={scenario.id} className="scenario-card">
            <h2>{scenario.name}</h2>
            <p>{scenario.description}</p>
            <p className="text-muted">
              <strong>Exercises:</strong> {scenario.exercises}
            </p>
            <p className="text-muted">
              <strong>Reference:</strong> {scenario.reference}
            </p>
            <button
              type="button"
              className="btn btn--secondary"
              disabled
              title="Phase 8 not yet implemented"
            >
              Trigger (Phase 8)
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
