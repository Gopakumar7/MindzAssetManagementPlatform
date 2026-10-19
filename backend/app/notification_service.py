from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import smtplib
from email.message import EmailMessage
from threading import Lock
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AssetAlert,
    CompanyMembership,
    Notification,
    NotificationDelivery,
    Role,
    SystemRoleAssignment,
    User,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CapturedEmail:
    recipient: str
    subject: str
    body: str
    created_at: datetime


class CapturedEmailMailbox:
    """In-memory capture mailbox for tests and local assertion verification."""
    _lock = Lock()
    _messages: list[CapturedEmail] = []

    @classmethod
    def record(cls, recipient: str, subject: str, body: str) -> None:
        with cls._lock:
            cls._messages.append(
                CapturedEmail(
                    recipient=recipient,
                    subject=subject,
                    body=body,
                    created_at=_utc_now(),
                )
            )

    @classmethod
    def get_messages(cls) -> list[CapturedEmail]:
        with cls._lock:
            return list(cls._messages)

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._messages.clear()


class EmailDeliveryService:
    @staticmethod
    def deliver(
        delivery: NotificationDelivery,
        subject: str,
        body: str,
    ) -> bool:
        mode = (settings.notification_email_mode or 'capture').lower()
        now_utc = _utc_now()
        delivery.attempts += 1
        delivery.last_attempt_at = now_utc

        if not settings.notification_email_enabled and mode != 'capture':
            delivery.status = 'pending'
            return False

        if mode == 'capture':
            CapturedEmailMailbox.record(delivery.recipient_address, subject, body)
            delivery.status = 'sent'
            delivery.sent_at = now_utc
            delivery.error_message = None
            return True

        if mode == 'console':
            logger.info(
                f"[NOTIFICATION EMAIL to {delivery.recipient_address}] Subject: {subject}\n{body}"
            )
            delivery.status = 'sent'
            delivery.sent_at = now_utc
            delivery.error_message = None
            return True

        if mode == 'smtp':
            if not settings.smtp_host:
                delivery.status = 'failed'
                delivery.error_message = 'SMTP host not configured'
                return False
            try:
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = settings.email_from
                msg['To'] = delivery.recipient_address
                msg.set_content(body)

                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
                    if settings.smtp_use_tls:
                        s.starttls()
                    if settings.smtp_username and settings.smtp_password:
                        s.login(settings.smtp_username, settings.smtp_password)
                    s.send_message(msg)

                delivery.status = 'sent'
                delivery.sent_at = now_utc
                delivery.error_message = None
                return True
            except Exception as e:
                sanitized_error = str(e)[:500]
                logger.warning(f"Failed to deliver email to {delivery.recipient_address}: {sanitized_error}")
                delivery.error_message = sanitized_error
                if delivery.attempts >= 3:
                    delivery.status = 'failed'
                else:
                    delivery.status = 'pending'
                return False

        return False


class NotificationService:
    @staticmethod
    def get_company_managers(db: Session, company_id: UUID) -> list[User]:
        """Returns active users holding company_administrator or asset_manager roles."""
        return list(
            db.scalars(
                select(User)
                .join(CompanyMembership, CompanyMembership.user_id == User.id)
                .join(Role, Role.id == CompanyMembership.role_id)
                .where(
                    CompanyMembership.company_id == company_id,
                    CompanyMembership.status == 'active',
                    User.is_active == True,
                    Role.code.in_(['company_administrator', 'asset_manager']),
                )
            ).all()
        )

    @staticmethod
    def get_system_administrators(db: Session) -> list[User]:
        """Returns active users assigned system_administrator role."""
        return list(
            db.scalars(
                select(User)
                .join(SystemRoleAssignment, SystemRoleAssignment.user_id == User.id)
                .join(Role, Role.id == SystemRoleAssignment.role_id)
                .where(
                    User.is_active == True,
                    Role.scope == 'system',
                    Role.code == 'system_administrator',
                )
            ).all()
        )

    @staticmethod
    def create_notification(
        db: Session,
        company_id: UUID | None,
        recipient_user: User,
        notification_type: str,
        title: str,
        message: str,
        severity: str,
        dedup_key: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        target_route: str | None = None,
        auto_deliver: bool = True,
    ) -> Notification | None:
        """Creates an in-app notification and delivery record idempotently using dedup_key."""
        try:
            existing = db.scalar(
                select(Notification.id).where(Notification.dedup_key == dedup_key)
            )
            if existing:
                return None

            notification = Notification(
                company_id=company_id,
                recipient_user_id=recipient_user.id,
                notification_type=notification_type,
                title=title,
                message=message,
                severity=severity,
                entity_type=entity_type,
                entity_id=entity_id,
                target_route=target_route,
                dedup_key=dedup_key,
                status='unread',
            )
            db.add(notification)
            db.flush()

            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel='email',
                recipient_address=recipient_user.email,
                status='pending',
            )
            db.add(delivery)
            db.flush()

            if auto_deliver:
                try:
                    EmailDeliveryService.deliver(delivery, title, message)
                except Exception as deliv_err:
                    logger.error(f"Error during delivery execution: {deliv_err}")
                    delivery.error_message = str(deliv_err)[:500]

            return notification
        except Exception as e:
            logger.error(f"Failed to create notification with dedup_key '{dedup_key}': {e}")
            return None

    @staticmethod
    def process_alert_notifications(db: Session, company_id: UUID) -> int:
        """Processes notifications for active critical alerts in a company."""
        created_count = 0
        try:
            critical_alerts = db.scalars(
                select(AssetAlert).where(
                    AssetAlert.company_id == company_id,
                    AssetAlert.status.in_(['open', 'acknowledged']),
                    AssetAlert.severity == 'critical',
                )
            ).all()

            for alert in critical_alerts:
                if alert.responsible_user_id:
                    user = db.get(User, alert.responsible_user_id)
                    if user and user.is_active:
                        dedup = f"alert_critical:{user.id}:{alert.id}"
                        notif = NotificationService.create_notification(
                            db=db,
                            company_id=company_id,
                            recipient_user=user,
                            notification_type='alert_critical',
                            title=f"Critical Alert: {alert.title}",
                            message=alert.description or alert.title,
                            severity='critical',
                            dedup_key=dedup,
                            entity_type='asset_alert',
                            entity_id=alert.id,
                            target_route=alert.target_route or 'alerts',
                        )
                        if notif:
                            created_count += 1
                else:
                    managers = NotificationService.get_company_managers(db, company_id)
                    for mgr in managers:
                        dedup = f"alert_critical:{mgr.id}:{alert.id}"
                        notif = NotificationService.create_notification(
                            db=db,
                            company_id=company_id,
                            recipient_user=mgr,
                            notification_type='alert_critical',
                            title=f"Critical Alert: {alert.title}",
                            message=alert.description or alert.title,
                            severity='critical',
                            dedup_key=dedup,
                            entity_type='asset_alert',
                            entity_id=alert.id,
                            target_route=alert.target_route or 'alerts',
                        )
                        if notif:
                            created_count += 1

            db.commit()
        except Exception as ex:
            db.rollback()
            logger.error(f"Error in process_alert_notifications for company {company_id}: {ex}")

        return created_count

    @staticmethod
    def notify_alert_assigned(db: Session, alert: AssetAlert) -> Notification | None:
        """Notifies a user when an alert is assigned to them."""
        try:
            if not alert.responsible_user_id:
                return None
            user = db.get(User, alert.responsible_user_id)
            if not user or not user.is_active:
                return None

            dedup = f"alert_assigned:{user.id}:{alert.id}:{alert.responsible_user_id}"
            notif = NotificationService.create_notification(
                db=db,
                company_id=alert.company_id,
                recipient_user=user,
                notification_type='alert_assigned',
                title=f"Alert Assigned: {alert.title}",
                message=f"You have been assigned to handle alert '{alert.title}' ({alert.severity.upper()}).\n{alert.description or ''}",
                severity=alert.severity,
                dedup_key=dedup,
                entity_type='asset_alert',
                entity_id=alert.id,
                target_route=alert.target_route or 'alerts',
            )
            db.commit()
            return notif
        except Exception as ex:
            db.rollback()
            logger.error(f"Error notifying alert assigned for alert {alert.id}: {ex}")
            return None

    @staticmethod
    def notify_alert_escalated(db: Session, alert: AssetAlert, new_severity: str) -> None:
        """Notifies managers/assigned user when an alert severity is escalated to critical."""
        try:
            if new_severity != 'critical':
                return
            if alert.responsible_user_id:
                user = db.get(User, alert.responsible_user_id)
                if user and user.is_active:
                    dedup = f"alert_escalated:{user.id}:{alert.id}:{new_severity}"
                    NotificationService.create_notification(
                        db=db,
                        company_id=alert.company_id,
                        recipient_user=user,
                        notification_type='alert_severity_escalated',
                        title=f"Alert Escalated: {alert.title}",
                        message=f"Alert '{alert.title}' has escalated to {new_severity.upper()}.\n{alert.description or ''}",
                        severity='critical',
                        dedup_key=dedup,
                        entity_type='asset_alert',
                        entity_id=alert.id,
                        target_route=alert.target_route or 'alerts',
                    )
            else:
                managers = NotificationService.get_company_managers(db, alert.company_id)
                for mgr in managers:
                    dedup = f"alert_escalated:{mgr.id}:{alert.id}:{new_severity}"
                    NotificationService.create_notification(
                        db=db,
                        company_id=alert.company_id,
                        recipient_user=mgr,
                        notification_type='alert_severity_escalated',
                        title=f"Alert Escalated: {alert.title}",
                        message=f"Unassigned alert '{alert.title}' has escalated to {new_severity.upper()}.\n{alert.description or ''}",
                        severity='critical',
                        dedup_key=dedup,
                        entity_type='asset_alert',
                        entity_id=alert.id,
                        target_route=alert.target_route or 'alerts',
                    )
            db.commit()
        except Exception as ex:
            db.rollback()
            logger.error(f"Error notifying alert escalation for alert {alert.id}: {ex}")

    @staticmethod
    def notify_job_failed(db: Session, job_id: UUID, job_name: str, error_message: str) -> None:
        """Notifies system administrators when a scheduled job execution fails."""
        try:
            admins = NotificationService.get_system_administrators(db)
            for admin in admins:
                dedup = f"job_failed:{admin.id}:{job_id}"
                NotificationService.create_notification(
                    db=db,
                    company_id=None,
                    recipient_user=admin,
                    notification_type='job_failed',
                    title=f"Scheduled Job Failed: {job_name}",
                    message=f"The scheduled evaluation job '{job_name}' (ID: {job_id}) encountered a fatal failure:\n{error_message}",
                    severity='critical',
                    dedup_key=dedup,
                    entity_type='scheduled_job_execution',
                    entity_id=job_id,
                    target_route='system',
                )
            db.commit()
        except Exception as ex:
            db.rollback()
            logger.error(f"Error notifying job failure for job {job_id}: {ex}")

