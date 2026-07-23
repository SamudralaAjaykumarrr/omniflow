import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DeadLetterEvent, SagaInstance
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
