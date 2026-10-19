from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alert_service import (
    acknowledge_alert,
    assign_alert,
    dismiss_alert,
    get_alert_summary,
    get_alerts,
    resolve_alert,
    sync_company_alerts,
)
from app.database import get_db
from app.models import ScheduledJobExecution
from app.schemas import (
    AlertAcknowledgeRequest,
    AlertAssignRequest,
    AlertDismissRequest,
    AlertResolveRequest,
    AlertSyncResponse,
    AssetAlertRead,
    AssetAlertSummary,
    ScheduledJobExecutionRead,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company

router = APIRouter(
    prefix='/companies/{company_id}/alerts',
    tags=['alerts'],
    dependencies=[Depends(current_actor)],
)


@router.get(
    '',
    response_model=list[AssetAlertRead],
    dependencies=[Depends(require_permission('alerts.read'))],
)
def list_company_alerts(
    company_id: UUID,
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    auto_sync: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    if auto_sync:
        sync_company_alerts(db, company_id)
    return get_alerts(
        db=db,
        company_id=company_id,
        status_filter=status,
        severity=severity,
        alert_type=alert_type,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get(
    '/summary',
    response_model=AssetAlertSummary,
    dependencies=[Depends(require_permission('alerts.read'))],
)
def get_company_alert_summary(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return get_alert_summary(db=db, company_id=company_id)


@router.get(
    '/last-job',
    response_model=ScheduledJobExecutionRead | None,
    dependencies=[Depends(require_permission('alerts.read'))],
)
def get_last_alert_job(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return db.scalar(
        select(ScheduledJobExecution)
        .where(ScheduledJobExecution.job_name == 'alert_lifecycle_sync')
        .order_by(ScheduledJobExecution.started_at.desc())
        .limit(1)
    )


@router.post(
    '/sync',
    response_model=AlertSyncResponse,
    dependencies=[Depends(require_permission('alerts.manage'))],
)
def sync_alerts(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return sync_company_alerts(db=db, company_id=company_id)


@router.post(
    '/{alert_id}/acknowledge',
    response_model=AssetAlertRead,
    dependencies=[Depends(require_permission('alerts.manage'))],
)
def acknowledge_company_alert(
    company_id: UUID,
    alert_id: UUID,
    payload: AlertAcknowledgeRequest,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return acknowledge_alert(
        db=db,
        company_id=company_id,
        alert_id=alert_id,
        user_id=actor.user.id,
        payload=payload,
    )


@router.post(
    '/{alert_id}/assign',
    response_model=AssetAlertRead,
    dependencies=[Depends(require_permission('alerts.manage'))],
)
def assign_company_alert(
    company_id: UUID,
    alert_id: UUID,
    payload: AlertAssignRequest,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return assign_alert(
        db=db,
        company_id=company_id,
        alert_id=alert_id,
        user_id=actor.user.id,
        payload=payload,
    )


@router.post(
    '/{alert_id}/resolve',
    response_model=AssetAlertRead,
    dependencies=[Depends(require_permission('alerts.manage'))],
)
def resolve_company_alert(
    company_id: UUID,
    alert_id: UUID,
    payload: AlertResolveRequest,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return resolve_alert(
        db=db,
        company_id=company_id,
        alert_id=alert_id,
        user_id=actor.user.id,
        payload=payload,
    )


@router.post(
    '/{alert_id}/dismiss',
    response_model=AssetAlertRead,
    dependencies=[Depends(require_permission('alerts.manage'))],
)
def dismiss_company_alert(
    company_id: UUID,
    alert_id: UUID,
    payload: AlertDismissRequest,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return dismiss_alert(
        db=db,
        company_id=company_id,
        alert_id=alert_id,
        user_id=actor.user.id,
        payload=payload,
    )
