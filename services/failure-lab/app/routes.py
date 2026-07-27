import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app import runner
from app.db import get_db, get_engine
from app.models import ScenarioRun
from app.runner import UnknownScenarioError
from app.scenarios.registry import REGISTRY, SCENARIO_ORDER
from app.schemas import (
    ScenarioCatalogEntry,
    ScenarioDetailResponse,
    ScenarioResetResponse,
    ScenarioRunResponse,
)
from app.security import require_ops, require_viewer

router = APIRouter()

_session_factory = sessionmaker(bind=get_engine(), future=True)


def _catalog_entry(scenario_id: str) -> ScenarioCatalogEntry:
    entry = REGISTRY[scenario_id]
    return ScenarioCatalogEntry(
        id=entry.id,
        name=entry.name,
        description=entry.description,
        category=entry.category,
        mechanism_reference=entry.mechanism_reference,
        expected_failure_behavior=entry.expected_failure_behavior,
        expected_recovery_behavior=entry.expected_recovery_behavior,
        safe_to_rerun=entry.safe_to_rerun,
    )


def _detail(db: Session, scenario_id: str) -> ScenarioDetailResponse:
    latest = runner.latest_run(db, scenario_id)
    last_reset = runner.latest_reset(db, scenario_id)
    return ScenarioDetailResponse(
        catalog=_catalog_entry(scenario_id),
        latest_run=ScenarioRunResponse.model_validate(latest) if latest else None,
        last_reset=ScenarioResetResponse.model_validate(last_reset) if last_reset else None,
        run_count=runner.run_count(db, scenario_id),
    )


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get(
    "/scenarios",
    response_model=list[ScenarioDetailResponse],
    dependencies=[Depends(require_viewer)],
)
def list_scenarios(db: Session = Depends(get_db)):
    return [_detail(db, scenario_id) for scenario_id in SCENARIO_ORDER]


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioDetailResponse,
    dependencies=[Depends(require_viewer)],
)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    if scenario_id not in REGISTRY:
        raise HTTPException(status_code=404, detail=f"no such scenario: {scenario_id!r}")
    return _detail(db, scenario_id)


@router.post(
    "/scenarios/{scenario_id}/trigger",
    response_model=ScenarioRunResponse,
    status_code=202,
    dependencies=[Depends(require_ops)],
)
def trigger_scenario(scenario_id: str, db: Session = Depends(get_db)):
    try:
        run = runner.trigger(db, _session_factory, scenario_id)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScenarioRunResponse.model_validate(run)


@router.get(
    "/scenarios/{scenario_id}/runs",
    response_model=list[ScenarioRunResponse],
    dependencies=[Depends(require_viewer)],
)
def list_scenario_runs(scenario_id: str, limit: int = 20, db: Session = Depends(get_db)):
    if scenario_id not in REGISTRY:
        raise HTTPException(status_code=404, detail=f"no such scenario: {scenario_id!r}")
    return [
        ScenarioRunResponse.model_validate(r) for r in runner.run_history(db, scenario_id, limit)
    ]


@router.get(
    "/scenarios/{scenario_id}/runs/{run_id}",
    response_model=ScenarioRunResponse,
    dependencies=[Depends(require_viewer)],
)
def get_scenario_run(scenario_id: str, run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = db.get(ScenarioRun, run_id)
    if run is None or run.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
    return ScenarioRunResponse.model_validate(run)


@router.post(
    "/scenarios/{scenario_id}/reset",
    response_model=ScenarioResetResponse,
    dependencies=[Depends(require_ops)],
)
def reset_scenario(scenario_id: str, db: Session = Depends(get_db)):
    try:
        row = runner.reset(db, scenario_id)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ScenarioResetResponse.model_validate(row)
