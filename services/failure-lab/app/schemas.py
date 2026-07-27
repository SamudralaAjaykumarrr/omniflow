import uuid
from datetime import datetime

from pydantic import BaseModel


class ScenarioCatalogEntry(BaseModel):
    """Static metadata for one scenario — the catalog the dashboard renders
    (requirement: "have a stable scenario identifier and clear human-readable
    description ... include expected failure behavior ... include expected
    recovery or remediation behavior")."""

    id: str
    name: str
    description: str
    category: str
    mechanism_reference: str
    expected_failure_behavior: str
    expected_recovery_behavior: str
    safe_to_rerun: bool = True


class ScenarioRunResponse(BaseModel):
    id: uuid.UUID
    scenario_id: str
    run_number: int
    status: str
    correlation_id: uuid.UUID
    summary: str | None
    diagnostics: dict
    resources: dict
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ScenarioResetResponse(BaseModel):
    scenario_id: str
    summary: str
    reset_at: datetime

    model_config = {"from_attributes": True}


class ScenarioDetailResponse(BaseModel):
    catalog: ScenarioCatalogEntry
    latest_run: ScenarioRunResponse | None
    last_reset: ScenarioResetResponse | None
    run_count: int


class TriggerScenarioRequest(BaseModel):
    """Empty for now — every scenario is self-contained and needs no
    caller-supplied parameters. A typed body (rather than no body at all)
    keeps the endpoint forward-compatible without a breaking-change route
    rename if a scenario ever needs an input."""


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None
