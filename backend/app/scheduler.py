from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import socket
from threading import Lock
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.alert_service import sync_company_alerts
from app.core.config import settings
from app.models import Company, ScheduledJobExecution
from app.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Advisory lock 64-bit int ID for scheduler mutual exclusion
SCHEDULER_ADVISORY_LOCK_ID = 882349172635412984
_local_lock = Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_scheduled_alerts(engine: Engine) -> ScheduledJobExecution | None:
    """Executes scheduled alert evaluation across all active companies with distributed advisory locking.
    
    Guarantees mutual exclusion across processes/containers via PostgreSQL advisory lock.
    Recovers any stale executions using heartbeat lease.
    Records full job metrics in scheduled_job_executions.
    """
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    with engine.connect() as lock_conn:
        is_pg = lock_conn.dialect.name == 'postgresql'
        if is_pg:
            acquired = lock_conn.execute(
                text('SELECT pg_try_advisory_lock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
            if not acquired:
                logger.info('Scheduler lock held by another instance; skipping execution.')
                return None
        else:
            if not _local_lock.acquire(blocking=False):
                logger.info('Scheduler local lock held; skipping execution.')
                return None

        try:
            with SessionLocal() as db:
                # 1. Recover stale executions if any lease expired
                stale_cutoff = _utc_now() - timedelta(seconds=settings.alert_job_lease_expiry_seconds)
                stale_jobs = db.scalars(
                    select(ScheduledJobExecution).where(
                        ScheduledJobExecution.status == 'running',
                        ScheduledJobExecution.last_heartbeat_at < stale_cutoff,
                    )
                ).all()
                for stale in stale_jobs:
                    stale.status = 'failed'
                    stale.completed_at = _utc_now()
                    stale.error_message = (
                        f"Job lease expired without heartbeat (last heartbeat: {stale.last_heartbeat_at.isoformat()}). "
                        'Recovered by scheduler runner.'
                    )
                    logger.warning(f"Recovered stale job execution {stale.id}")
                if stale_jobs:
                    db.commit()

                # 2. Record new execution starting
                start_time = _utc_now()
                execution = ScheduledJobExecution(
                    job_name='alert_lifecycle_sync',
                    status='running',
                    started_at=start_time,
                    last_heartbeat_at=start_time,
                    node_id=socket.gethostname(),
                )
                db.add(execution)
                db.commit()
                db.refresh(execution)

                try:
                    companies = db.scalars(
                        select(Company).where(Company.is_active == True).order_by(Company.created_at)
                    ).all()

                    for company in companies:
                        sync_res = sync_company_alerts(db, company.id)
                        NotificationService.process_alert_notifications(db, company.id)

                        execution.total_companies_processed += 1
                        execution.alerts_created += sync_res.created_count
                        execution.alerts_updated += sync_res.updated_count
                        execution.alerts_auto_resolved += sync_res.auto_resolved_count
                        execution.last_heartbeat_at = _utc_now()
                        db.commit()

                    completed_time = _utc_now()
                    execution.status = 'completed'
                    execution.completed_at = completed_time
                    execution.duration_ms = int((completed_time - start_time).total_seconds() * 1000)
                    db.commit()
                    db.refresh(execution)
                    logger.info(
                        f"Scheduled alert evaluation completed in {execution.duration_ms}ms. "
                        f"Companies: {execution.total_companies_processed}, Created: {execution.alerts_created}, "
                        f"Updated: {execution.alerts_updated}, Auto-resolved: {execution.alerts_auto_resolved}"
                    )
                    return execution

                except Exception as inner_ex:
                    db.rollback()
                    completed_time = _utc_now()
                    sanitized_error = str(inner_ex)[:500]
                    execution.status = 'failed'
                    execution.completed_at = completed_time
                    execution.duration_ms = int((completed_time - start_time).total_seconds() * 1000)
                    execution.error_message = sanitized_error
                    db.commit()
                    db.refresh(execution)

                    logger.error(f"Scheduled alert evaluation failed: {sanitized_error}")
                    try:
                        NotificationService.notify_job_failed(
                            db=db,
                            job_id=execution.id,
                            job_name=execution.job_name,
                            error_message=sanitized_error,
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to notify admins of job failure: {notify_err}")

                    return execution

        finally:
            if is_pg:
                try:
                    lock_conn.execute(
                        text('SELECT pg_advisory_unlock(:lock_id)'),
                        {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
                    )
                    lock_conn.commit()
                except Exception as unlock_err:
                    logger.error(f"Failed to release advisory lock: {unlock_err}")
            else:
                _local_lock.release()


async def run_scheduler_loop(engine: Engine, stop_event: asyncio.Event) -> None:
    """Runs the alert evaluation periodically until stop_event is set."""
    startup_delay = settings.alert_schedule_startup_delay_seconds
    interval = settings.alert_schedule_interval_seconds

    logger.info(f"Starting alert scheduler loop. Startup delay: {startup_delay}s, interval: {interval}s")

    if startup_delay > 0:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=startup_delay)
            return
        except asyncio.TimeoutError:
            pass

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(evaluate_scheduled_alerts, engine)
        except Exception as exc:
            logger.error(f"Scheduler loop execution encountered error: {exc}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            continue

    logger.info("Alert scheduler loop shut down cleanly.")
