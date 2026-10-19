from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification
from app.schemas import NotificationRead, NotificationUnreadCount
from app.security import CurrentActor, current_actor

router = APIRouter(
    prefix='/notifications',
    tags=['notifications'],
    dependencies=[Depends(current_actor)],
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    '',
    response_model=list[NotificationRead],
)
def list_user_notifications(
    status_filter: str | None = Query(default=None, alias='status'),
    company_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    """Lists notifications for the authenticated user."""
    stmt = select(Notification).where(Notification.recipient_user_id == actor.user.id)
    if status_filter:
        stmt = stmt.where(Notification.status == status_filter)
    if company_id:
        stmt = stmt.where(Notification.company_id == company_id)

    stmt = stmt.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


@router.get(
    '/unread-count',
    response_model=NotificationUnreadCount,
)
def get_unread_count(
    company_id: UUID | None = Query(default=None),
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    """Returns the unread notifications count for the authenticated user."""
    stmt = select(func.count(Notification.id)).where(
        Notification.recipient_user_id == actor.user.id,
        Notification.status == 'unread',
    )
    if company_id:
        stmt = stmt.where(Notification.company_id == company_id)

    count = db.scalar(stmt) or 0
    return NotificationUnreadCount(unread_count=count)


@router.post(
    '/{notification_id}/read',
    response_model=NotificationRead,
)
def mark_notification_read(
    notification_id: UUID,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    """Marks a single notification as read for the authenticated user.
    
    Strictly verifies ownership: users can only mark their own notifications as read.
    Marking a notification as read never resolves or alters underlying alerts or entities.
    """
    notif = db.scalar(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.recipient_user_id == actor.user.id,
        )
        .with_for_update()
    )
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Notification not found',
        )

    if notif.status == 'unread':
        notif.status = 'read'
        notif.read_at = _utc_now()
        db.commit()
        db.refresh(notif)

    return notif


@router.post(
    '/mark-all-read',
    response_model=NotificationUnreadCount,
)
def mark_all_notifications_read(
    company_id: UUID | None = Query(default=None),
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    """Marks all unread notifications for the authenticated user as read."""
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_user_id == actor.user.id,
            Notification.status == 'unread',
        )
    )
    if company_id:
        stmt = stmt.where(Notification.company_id == company_id)

    stmt = stmt.values(status='read', read_at=_utc_now())
    db.execute(stmt)
    db.commit()

    return NotificationUnreadCount(unread_count=0)

