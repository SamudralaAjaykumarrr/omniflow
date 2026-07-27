import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.clients import InventoryServiceClient, OrderServiceClient
from app.config import get_settings
from app.db import get_db
from app.kafka_producer import get_producer
from app.models import DeadLetterEvent, SagaInstance
from app.replay import replay_one
from app.saga import STATUS_RUNNING, advance_saga
from app.schemas import DeadLetterEventResponse, SagaInstanceResponse

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/saga-instances", response_model=list[SagaInstanceResponse])
def list_saga_instances(status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(SagaInstance).order_by(SagaInstance.created_at.desc())
    if status is not None:
        stmt = stmt.where(SagaInstance.status == status)
    return [SagaInstanceResponse.model_validate(s) for s in db.scalars(stmt)]


@router.get("/saga-instances/{order_id}", response_model=SagaInstanceResponse)
def get_saga_instance(order_id: uuid.UUID, db: Session = Depends(get_db)):
    saga = db.execute(
        select(SagaInstance).where(SagaInstance.order_id == order_id)
    ).scalar_one_or_none()
    if saga is None:
        raise HTTPException(status_code=404, detail=f"no saga for order {order_id}")
    return SagaInstanceResponse.model_validate(saga)


@router.get("/dead-letters", response_model=list[DeadLetterEventResponse])
def list_dead_letters(unreplayed_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(DeadLetterEvent).order_by(DeadLetterEvent.first_failed_at.desc())
    if unreplayed_only:
        stmt = stmt.where(DeadLetterEvent.replayed_at.is_(None))
    return [DeadLetterEventResponse.model_validate(d) for d in db.scalars(stmt)]


@router.post("/dead-letters/{dead_letter_id}/replay", response_model=DeadLetterEventResponse)
def replay_dead_letter_route(dead_letter_id: uuid.UUID, db: Session = Depends(get_db)):
    """Re-publishes a dead-lettered event's original envelope back onto its
    original topic — the same operation `app.replay`'s CLI already
    performed (`make replay ARGS="--id ..."`), now also reachable over HTTP.
    Added for Phase 8's downstream-outage scenario, which needs to trigger
    recovery from a real dashboard/API action rather than only a shell
    command; genuinely useful independent of the failure lab too (this was
    a documented gap — docs/phase-7-ops-dashboard.md "Limitations": "DLQ
    replay is shown as a CLI command, not a working button")."""
    dead_letter = db.get(DeadLetterEvent, dead_letter_id)
    if dead_letter is None:
        raise HTTPException(status_code=404, detail=f"no dead letter {dead_letter_id}")
    if dead_letter.replayed_at is not None:
        raise HTTPException(
            status_code=409, detail=f"dead letter {dead_letter_id} already replayed"
        )
    replay_one(get_producer(), db, dead_letter)
    return DeadLetterEventResponse.model_validate(dead_letter)


@router.post(
    "/internal/failure-lab/saga-crash-resume/{order_id}/resume",
    response_model=SagaInstanceResponse,
)
def resume_saga_route(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Drives one specific order's saga forward via the real `advance_saga`
    — the identical function `app.saga.resume_incomplete_sagas` calls for
    every RUNNING row at real process startup — targeted at one order on
    demand instead of requiring an actual process restart. Added for
    Phase 8's saga-crash-resume scenario (app.saga's
    CRASH_SIMULATION_SKU pauses a saga mid-flight; this is how the scenario
    then resumes it)."""
    saga = db.execute(
        select(SagaInstance).where(SagaInstance.order_id == order_id)
    ).scalar_one_or_none()
    if saga is None:
        raise HTTPException(status_code=404, detail=f"no saga for order {order_id}")
    if saga.status != STATUS_RUNNING:
        raise HTTPException(
            status_code=409, detail=f"saga for order {order_id} is {saga.status}, not RUNNING"
        )
    settings = get_settings()
    order_client = OrderServiceClient(settings.order_service_url)
    inventory_client = InventoryServiceClient(settings.inventory_service_url)
    advance_saga(db, order_client, inventory_client, saga)
    db.refresh(saga)
    return SagaInstanceResponse.model_validate(saga)
