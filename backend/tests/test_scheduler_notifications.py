from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.authentication import password_hasher
from app.models import (
    Asset,
    AssetAlert,
    AssetCategory,
    AssetServiceContract,
    Company,
    CompanyMembership,
    Notification,
    NotificationDelivery,
    Role,
    ScheduledJobExecution,
    User,
)
from app.notification_service import CapturedEmailMailbox
from app.scheduler import SCHEDULER_ADVISORY_LOCK_ID, evaluate_scheduled_alerts


def _setup_company_and_users(client, db_session, suffix='1'):
    comp_res = client.post('/api/v1/companies', json={'code': f'SCH-CO-{suffix}', 'name': f'Scheduler Co {suffix}'})
    assert comp_res.status_code == 201, comp_res.text
    company_id = UUID(comp_res.json()['id'])

    cats = client.get(f'/api/v1/companies/{company_id}/categories')
    assert cats.status_code == 200
    category_id = UUID(cats.json()[0]['id'])

    # Create an asset manager user
    manager = User(
        email=f'manager-{suffix}@example.invalid',
        password_hash=password_hasher.hash('ManagerPass-123!'),
        is_active=True,
    )
    db_session.add(manager)
    db_session.flush()

    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == 'asset_manager'))
    membership = CompanyMembership(
        company_id=company_id,
        user_id=manager.id,
        role_id=role.id,
        status='active',
    )
    db_session.add(membership)
    db_session.commit()

    return company_id, category_id, manager


def test_advisory_lock_mutual_exclusion_and_release(client, db_session):
    engine = db_session.bind
    is_pg = engine.dialect.name == 'postgresql'

    if is_pg:
        # Acquire lock on dedicated connection 1
        with engine.connect() as conn1:
            acquired = conn1.execute(
                text('SELECT pg_try_advisory_lock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
            assert acquired is True

            # Attempt evaluation while lock is held -> must be skipped
            result = evaluate_scheduled_alerts(engine)
            assert result is None

            # Release lock on connection 1
            released = conn1.execute(
                text('SELECT pg_advisory_unlock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
            conn1.commit()
            assert released is True

        # Now evaluation must succeed and lock should be released afterwards
        result = evaluate_scheduled_alerts(engine)
        assert result is not None
        assert result.status == 'completed'

        # Verify lock is freed
        with engine.connect() as conn2:
            test_lock = conn2.execute(
                text('SELECT pg_try_advisory_lock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
            assert test_lock is True
            conn2.execute(
                text('SELECT pg_advisory_unlock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            )
            conn2.commit()
    else:
        # SQLite fallback test
        result = evaluate_scheduled_alerts(engine)
        assert result is not None
        assert result.status == 'completed'


def test_advisory_lock_released_on_job_failure(client, db_session):
    company_id, _, _ = _setup_company_and_users(client, db_session, suffix='fail-lock')
    engine = db_session.bind
    is_pg = engine.dialect.name == 'postgresql'

    # Monkeypatch sync_company_alerts to raise an exception
    with patch('app.scheduler.sync_company_alerts', side_effect=RuntimeError('Simulated unexpected worker failure')):
        result = evaluate_scheduled_alerts(engine)
        assert result is not None
        assert result.status == 'failed'
        assert 'Simulated unexpected worker failure' in (result.error_message or '')

    if is_pg:
        # Verify lock was freed despite exception
        with engine.connect() as conn:
            acquired = conn.execute(
                text('SELECT pg_try_advisory_lock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            ).scalar()
            assert acquired is True
            conn.execute(
                text('SELECT pg_advisory_unlock(:lock_id)'),
                {'lock_id': SCHEDULER_ADVISORY_LOCK_ID},
            )
            conn.commit()


def test_stale_job_lease_recovery(client, db_session):
    engine = db_session.bind
    now_utc = datetime.now(timezone.utc)
    old_time = now_utc - timedelta(seconds=600)

    # Seed an orphaned/stale job execution whose heartbeat stopped
    stale_execution = ScheduledJobExecution(
        job_name='alert_lifecycle_sync',
        status='running',
        started_at=old_time,
        last_heartbeat_at=old_time,
        node_id='dead-worker-container',
    )
    db_session.add(stale_execution)
    db_session.commit()
    stale_id = stale_execution.id

    # Run scheduler evaluation
    new_execution = evaluate_scheduled_alerts(engine)
    assert new_execution is not None
    assert new_execution.status == 'completed'

    # Verify stale execution was marked failed
    db_session.expire_all()
    recovered = db_session.get(ScheduledJobExecution, stale_id)
    assert recovered.status == 'failed'
    assert 'lease expired without heartbeat' in (recovered.error_message or '').lower()


def test_scheduled_evaluation_notifications_and_email_capture(client, db_session):
    CapturedEmailMailbox.clear()
    company_id, category_id, manager = _setup_company_and_users(client, db_session, suffix='notif-1')
    engine = db_session.bind

    # Create an asset with an expired warranty contract (triggers critical alert)
    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'Dell PowerEdge R740'},
    )
    assert asset_res.status_code == 201
    asset_id = UUID(asset_res.json()['id'])

    expired_contract = AssetServiceContract(
        company_id=company_id,
        asset_id=asset_id,
        contract_type='warranty',
        status='active',
        start_date=date.today() - timedelta(days=400),
        end_date=date.today() - timedelta(days=10),
        reference_number='WAR-CRIT-999',
    )
    db_session.add(expired_contract)
    db_session.commit()

    # Run scheduled evaluation
    result = evaluate_scheduled_alerts(engine)
    assert result is not None
    assert result.status == 'completed'
    assert result.alerts_created >= 1

    # Verify notifications created for manager
    db_session.expire_all()
    notifications = list(
        db_session.scalars(
            select(Notification).where(
                Notification.company_id == company_id,
                Notification.recipient_user_id == manager.id,
            )
        ).all()
    )
    assert len(notifications) >= 1
    crit_notif = notifications[0]
    assert crit_notif.severity == 'critical'
    assert crit_notif.status == 'unread'
    assert crit_notif.dedup_key.startswith(f'alert_critical:{manager.id}:')

    # Verify notification delivery was recorded and marked sent in capture mode
    deliveries = list(
        db_session.scalars(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == crit_notif.id)
        ).all()
    )
    assert len(deliveries) == 1
    assert deliveries[0].status == 'sent'
    assert deliveries[0].recipient_address == manager.email

    # Verify email was captured in CapturedEmailMailbox
    messages = CapturedEmailMailbox.get_messages()
    assert any(m.recipient == manager.email and 'Critical Alert' in m.subject for m in messages)


def test_notification_deduplication_and_anti_resurrection(client, db_session):
    company_id, category_id, manager = _setup_company_and_users(client, db_session, suffix='dedup-1')
    engine = db_session.bind

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'Cisco Catalyst 9300'},
    )
    asset_id = UUID(asset_res.json()['id'])

    expired_contract = AssetServiceContract(
        company_id=company_id,
        asset_id=asset_id,
        contract_type='warranty',
        status='active',
        start_date=date.today() - timedelta(days=400),
        end_date=date.today() - timedelta(days=5),
        reference_number='WAR-DEDUP-1',
    )
    db_session.add(expired_contract)
    db_session.commit()

    # 1. First run generates 1 notification
    evaluate_scheduled_alerts(engine)
    initial_count = db_session.scalar(
        select(Notification)
        .where(Notification.company_id == company_id, Notification.recipient_user_id == manager.id)
    )
    assert initial_count is not None

    total_notifs_1 = len(
        list(
            db_session.scalars(
                select(Notification).where(
                    Notification.company_id == company_id,
                    Notification.recipient_user_id == manager.id,
                )
            ).all()
        )
    )

    # 2. Second run must NOT duplicate
    evaluate_scheduled_alerts(engine)
    total_notifs_2 = len(
        list(
            db_session.scalars(
                select(Notification).where(
                    Notification.company_id == company_id,
                    Notification.recipient_user_id == manager.id,
                )
            ).all()
        )
    )
    assert total_notifs_2 == total_notifs_1

    # 3. Mark notification as read
    notif = db_session.scalar(
        select(Notification).where(
            Notification.company_id == company_id,
            Notification.recipient_user_id == manager.id,
        )
    )
    notif.status = 'read'
    db_session.commit()

    # 4. Third run must NOT resurrect or recreate as unread
    evaluate_scheduled_alerts(engine)
    db_session.expire_all()
    total_notifs_3 = len(
        list(
            db_session.scalars(
                select(Notification).where(
                    Notification.company_id == company_id,
                    Notification.recipient_user_id == manager.id,
                )
            ).all()
        )
    )
    assert total_notifs_3 == total_notifs_1
    notif_recheck = db_session.get(Notification, notif.id)
    assert notif_recheck.status == 'read'


def test_alert_assignment_notification(client, db_session):
    CapturedEmailMailbox.clear()
    company_id, category_id, manager = _setup_company_and_users(client, db_session, suffix='assign-1')

    # Create an alert manually
    alert = AssetAlert(
        company_id=company_id,
        alert_type='maintenance_overdue',
        severity='warning',
        status='open',
        title='Overdue maintenance ticket',
        entity_type='maintenance_request',
        entity_id=uuid4(),
    )
    db_session.add(alert)
    db_session.commit()
    alert_id = alert.id

    # Assign alert to manager
    assign_res = client.post(
        f'/api/v1/companies/{company_id}/alerts/{alert_id}/assign',
        json={'responsible_user_id': str(manager.id)},
    )
    assert assign_res.status_code == 200, assign_res.text

    # Verify notification created for manager
    db_session.expire_all()
    assigned_notif = db_session.scalar(
        select(Notification).where(
            Notification.recipient_user_id == manager.id,
            Notification.notification_type == 'alert_assigned',
        )
    )
    assert assigned_notif is not None
    assert f'alert_assigned:{manager.id}:{alert_id}:{manager.id}' == assigned_notif.dedup_key

    # Verify email capture
    messages = CapturedEmailMailbox.get_messages()
    assert any(m.recipient == manager.email and 'Alert Assigned' in m.subject for m in messages)


def test_job_failed_notification(client, db_session):
    company_id, _, _ = _setup_company_and_users(client, db_session, suffix='fail-notif')
    engine = db_session.bind
    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    assert admin_user is not None

    with patch('app.scheduler.sync_company_alerts', side_effect=RuntimeError('Simulated fatal corruption')):
        result = evaluate_scheduled_alerts(engine)
        assert result.status == 'failed'

    # Check notification sent to system administrator
    db_session.expire_all()
    fail_notif = db_session.scalar(
        select(Notification).where(
            Notification.recipient_user_id == admin_user.id,
            Notification.notification_type == 'job_failed',
        )
    )
    assert fail_notif is not None
    assert fail_notif.severity == 'critical'
    assert 'Simulated fatal corruption' in fail_notif.message


def test_notifications_api_and_user_isolation(client, db_session):
    company_id, category_id, manager = _setup_company_and_users(client, db_session, suffix='api-iso')
    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))

    # Create one notification for manager and one for admin
    notif_manager = Notification(
        company_id=company_id,
        recipient_user_id=manager.id,
        notification_type='alert_critical',
        title='Manager Only Notification',
        message='For manager eyes only',
        severity='critical',
        dedup_key=f'iso_mgr_{uuid4()}',
        status='unread',
    )
    notif_admin = Notification(
        company_id=company_id,
        recipient_user_id=admin_user.id,
        notification_type='alert_critical',
        title='Admin Only Notification',
        message='For admin eyes only',
        severity='critical',
        dedup_key=f'iso_admin_{uuid4()}',
        status='unread',
    )
    db_session.add_all([notif_manager, notif_admin])
    db_session.commit()

    # Client is logged in as admin
    # 1. List notifications -> should only include admin's notification
    list_res = client.get('/api/v1/notifications')
    assert list_res.status_code == 200
    ids = [item['id'] for item in list_res.json()]
    assert str(notif_admin.id) in ids
    assert str(notif_manager.id) not in ids

    # 2. Unread count -> includes only admin's unread
    count_res = client.get('/api/v1/notifications/unread-count')
    assert count_res.status_code == 200
    assert count_res.json()['unread_count'] >= 1

    # 3. Admin attempts to mark manager's notification as read -> 404 forbidden/not found
    bad_read = client.post(f'/api/v1/notifications/{notif_manager.id}/read')
    assert bad_read.status_code == 404

    # 4. Admin marks own notification as read
    read_res = client.post(f'/api/v1/notifications/{notif_admin.id}/read')
    assert read_res.status_code == 200
    assert read_res.json()['status'] == 'read'

    # Verify manager's notification remains unread
    db_session.expire_all()
    mgr_check = db_session.get(Notification, notif_manager.id)
    assert mgr_check.status == 'unread'

    # 5. Mark all read for admin
    mark_all = client.post('/api/v1/notifications/mark-all-read')
    assert mark_all.status_code == 200
    count_res2 = client.get('/api/v1/notifications/unread-count')
    assert count_res2.json()['unread_count'] == 0


def test_last_job_endpoint(client, db_session):
    company_id, category_id, _ = _setup_company_and_users(client, db_session, suffix='last-job')
    engine = db_session.bind

    # Initially or after run
    evaluate_scheduled_alerts(engine)

    last_res = client.get(f'/api/v1/companies/{company_id}/alerts/last-job')
    assert last_res.status_code == 200
    data = last_res.json()
    assert data is not None
    assert data['job_name'] == 'alert_lifecycle_sync'
    assert data['status'] == 'completed'
    assert 'started_at' in data
    assert 'duration_ms' in data
