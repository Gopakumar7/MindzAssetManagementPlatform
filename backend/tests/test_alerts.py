from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.authentication import password_hasher
from app.models import (
    Asset,
    AssetAlert,
    AssetCategory,
    AssetDepreciationEntry,
    AssetFinancial,
    AssetServiceContract,
    AuditEvent,
    Company,
    CompanyMembership,
    MaintenanceRequest,
    PurchaseOrder,
    Role,
    Supplier,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationObservation,
)


def _setup_company_and_category(client, company_code='ALT-CO-1'):
    comp_res = client.post('/api/v1/companies', json={'code': company_code, 'name': f'Alerts Co {company_code}'})
    assert comp_res.status_code == 201, comp_res.text
    comp_id = UUID(comp_res.json()['id'])

    cats = client.get(f'/api/v1/companies/{comp_id}/categories')
    assert cats.status_code == 200
    cat_id = UUID(cats.json()[0]['id'])
    return comp_id, cat_id


def test_alert_rules_evaluation_and_sync(client, db_session):
    """Test all 8 alert rules evaluation and generation via sync."""
    company_id, category_id = _setup_company_and_category(client, 'ALT-RULE-1')
    today = date.today()

    # Create test assets
    asset1_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'Dell Latitude 7420'},
    )
    assert asset1_res.status_code == 201
    asset1_id = UUID(asset1_res.json()['id'])
    asset1_num = asset1_res.json()['asset_number']

    asset2_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'ThinkPad X1 Carbon'},
    )
    assert asset2_res.status_code == 201
    asset2_id = UUID(asset2_res.json()['id'])
    asset2_num = asset2_res.json()['asset_number']

    # 1. Warranty expiring in 15 days (warning)
    contract_warn = AssetServiceContract(
        company_id=company_id,
        asset_id=asset1_id,
        contract_type='warranty',
        provider_name='Dell ProSupport',
        reference_number='WRN-DELL-001',
        start_date=today - timedelta(days=350),
        end_date=today + timedelta(days=15),
        status='active',
    )
    # 2. Warranty expired 5 days ago (critical)
    contract_crit = AssetServiceContract(
        company_id=company_id,
        asset_id=asset2_id,
        contract_type='warranty',
        provider_name='Lenovo Care',
        reference_number='WRN-LEN-002',
        start_date=today - timedelta(days=370),
        end_date=today - timedelta(days=5),
        status='active',
    )
    # AMC expiring in 25 days (warning)
    contract_amc = AssetServiceContract(
        company_id=company_id,
        asset_id=asset1_id,
        contract_type='amc',
        provider_name='Facility AMC',
        reference_number='AMC-FAC-003',
        start_date=today - timedelta(days=340),
        end_date=today + timedelta(days=25),
        status='active',
    )
    db_session.add_all([contract_warn, contract_crit, contract_amc])

    # 3. Urgent maintenance request reported 3 days ago (SLA 2d -> overdue, critical)
    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    maint_req = MaintenanceRequest(
        company_id=company_id,
        asset_id=asset1_id,
        requester_id=admin_user.id,
        title='Liquid spill on keyboard',
        issue_description='Keys sticking after coffee spill',
        priority='urgent',
        status='open',
        reported_date=today - timedelta(days=3),
    )
    db_session.add(maint_req)

    # 4. Physical verification discrepancy (missing asset, critical)
    # Create campaign
    camp = VerificationCampaign(
        company_id=company_id,
        campaign_reference='VC-2026-01',
        name='Annual Audit Campaign',
        start_date=today - timedelta(days=20),
        end_date=today - timedelta(days=2),  # also overdue campaign! (rule 5)
        status='in_progress',
        created_by_id=admin_user.id,
    )
    db_session.add(camp)
    db_session.flush()

    disc = VerificationDiscrepancy(
        company_id=company_id,
        campaign_id=camp.id,
        asset_id=asset2_id,
        discrepancy_type='missing',
        notes='Asset not located at scheduled desk',
        status='open',
        created_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db_session.add(disc)

    # 6. Fully depreciated asset in service (warning)
    fin_deprec = AssetFinancial(
        company_id=company_id,
        asset_id=asset1_id,
        capitalised_cost=Decimal('1200.00'),
        currency='USD',
        depreciation_method='straight_line',
        useful_life_months=12,
        residual_value=Decimal('0.00'),
        depreciation_start_date=today - timedelta(days=400),
        accumulated_depreciation=Decimal('1200.00'),
        current_book_value=Decimal('0.00'),
        financial_status='fully_depreciated',
    )
    db_session.add(fin_deprec)

    # 7. Approaching EOL: active asset with 2 months remaining (warning/info)
    fin_eol = AssetFinancial(
        company_id=company_id,
        asset_id=asset2_id,
        capitalised_cost=Decimal('2400.00'),
        currency='USD',
        depreciation_method='straight_line',
        useful_life_months=24,
        residual_value=Decimal('0.00'),
        depreciation_start_date=today - timedelta(days=660),
        accumulated_depreciation=Decimal('2200.00'),
        current_book_value=Decimal('200.00'),
        financial_status='active',
    )
    db_session.add(fin_eol)
    db_session.flush()

    # Insert 22 posted entries for asset2 so remaining_months = 24 - 22 = 2
    for i in range(22):
        entry = AssetDepreciationEntry(
            company_id=company_id,
            asset_id=asset2_id,
            period=f'2024-{i+1:02d}' if i < 12 else f'2025-{i-11:02d}',
            period_start_date=today - timedelta(days=700 - i * 30),
            period_end_date=today - timedelta(days=670 - i * 30),
            depreciation_amount=Decimal('100.00'),
            accumulated_depreciation_after=Decimal((i + 1) * 100),
            book_value_after=Decimal(2400 - (i + 1) * 100),
            method='straight_line',
            posted_by_id=admin_user.id,
        )
        db_session.add(entry)

    # 8. Purchase order delivery overdue (critical, > 7 days)
    supp = Supplier(
        company_id=company_id,
        code='SUPP-01',
        name='Tech Hardware Inc',
    )
    db_session.add(supp)
    db_session.flush()

    po = PurchaseOrder(
        company_id=company_id,
        supplier_id=supp.id,
        order_number='PO-2026-999',
        status='open',
        ordered_date=today - timedelta(days=30),
        expected_date=today - timedelta(days=10),
    )
    db_session.add(po)
    db_session.commit()

    # Trigger Alert Sync
    sync_res = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert sync_res.status_code == 200, sync_res.text
    sync_data = sync_res.json()
    assert sync_data['synced'] is True
    # 8 distinct alert scenarios created:
    # 2 warranty (1 expired, 1 soon) + 1 amc + 1 maintenance + 1 discrepancy + 1 campaign + 1 fully_deprec + 1 eol + 1 po = 9 alerts
    assert sync_data['created_count'] >= 8

    # Query alert summary
    sum_res = client.get(f'/api/v1/companies/{company_id}/alerts/summary')
    assert sum_res.status_code == 200
    summary = sum_res.json()
    assert summary['total_open'] >= 8
    assert summary['critical_count'] >= 4  # expired warranty, urgent maintenance, missing discrepancy, campaign overdue, po overdue
    assert summary['warning_count'] >= 3   # warranty soon, amc soon, fully depreciated
    assert 'warranty_expiry' in summary['by_type']
    assert 'maintenance_overdue' in summary['by_type']
    assert 'verification_discrepancy' in summary['by_type']
    assert 'verification_campaign_due' in summary['by_type']
    assert 'fully_depreciated_in_use' in summary['by_type']
    assert 'approaching_eol' in summary['by_type']
    assert 'purchase_order_overdue' in summary['by_type']

    # Query alert list
    list_res = client.get(f'/api/v1/companies/{company_id}/alerts')
    assert list_res.status_code == 200
    alerts = list_res.json()
    assert len(alerts) >= 8

    # Test filtering by severity
    crit_res = client.get(f'/api/v1/companies/{company_id}/alerts?severity=critical')
    assert crit_res.status_code == 200
    crit_alerts = crit_res.json()
    assert all(a['severity'] == 'critical' for a in crit_alerts)

    # Test filtering by alert_type
    po_res = client.get(f'/api/v1/companies/{company_id}/alerts?alert_type=purchase_order_overdue')
    assert po_res.status_code == 200
    po_alerts = po_res.json()
    assert len(po_alerts) == 1
    assert 'PO-2026-999' in po_alerts[0]['title']
    assert po_alerts[0]['target_route'] == 'procurement'


def test_alert_idempotency_and_auto_resolution(client, db_session):
    """Test idempotent repeat syncs and automatic resolution when underlying condition clears."""
    company_id, category_id = _setup_company_and_category(client, 'ALT-IDEMP-1')
    today = date.today()

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'Server Blade R740'},
    )
    assert asset_res.status_code == 201
    asset_id = UUID(asset_res.json()['id'])

    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    maint_req = MaintenanceRequest(
        company_id=company_id,
        asset_id=asset_id,
        requester_id=admin_user.id,
        title='Fan failure in blade 2',
        issue_description='Excessive vibration reported',
        priority='high',
        status='open',
        reported_date=today - timedelta(days=10),
    )
    db_session.add(maint_req)
    db_session.commit()

    # 1. Initial Sync creates the alert
    res1 = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert res1.status_code == 200
    assert res1.json()['created_count'] == 1

    # 2. Second Sync is idempotent: 0 created, 1 updated
    res2 = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert res2.status_code == 200
    assert res2.json()['created_count'] == 0
    assert res2.json()['updated_count'] == 1
    assert res2.json()['auto_resolved_count'] == 0

    # Verify 1 active alert exists
    active_res = client.get(f'/api/v1/companies/{company_id}/alerts?status=open')
    assert active_res.status_code == 200
    open_alerts = active_res.json()
    assert len(open_alerts) == 1
    alert_id = open_alerts[0]['id']

    # 3. Clear source condition: Maintenance request is completed/resolved
    maint_req.status = 'resolved'
    maint_req.completed_date = today
    maint_req.work_performed = 'Replaced blower fan module'
    db_session.commit()

    # 4. Third Sync auto-resolves the alert
    res3 = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert res3.status_code == 200
    assert res3.json()['auto_resolved_count'] == 1
    assert res3.json()['active_count'] == 0

    # Verify alert is resolved with source_resolved reason
    resolved_res = client.get(f'/api/v1/companies/{company_id}/alerts?status=resolved')
    assert resolved_res.status_code == 200
    resolved_alerts = resolved_res.json()
    assert len(resolved_alerts) == 1
    assert resolved_alerts[0]['id'] == alert_id
    assert resolved_alerts[0]['resolution_reason'] == 'source_resolved'


def test_alert_lifecycle_actions_and_anti_resurrection(client, db_session):
    """Test Acknowledge, Assign, Resolve, Dismiss, and prevention of re-alerting."""
    company_id, category_id = _setup_company_and_category(client, 'ALT-ACT-1')
    today = date.today()

    asset_res = client.post(
        f'/api/v1/companies/{company_id}/assets',
        json={'category_id': str(category_id), 'model': 'Mac Studio'},
    )
    asset_id = UUID(asset_res.json()['id'])

    # Create expiring warranty & overdue PO
    contract = AssetServiceContract(
        company_id=company_id,
        asset_id=asset_id,
        contract_type='warranty',
        provider_name='AppleCare+',
        reference_number='AC-STUDIO-101',
        start_date=today - timedelta(days=340),
        end_date=today + timedelta(days=10),
        status='active',
    )
    supp = Supplier(company_id=company_id, code='APPLE-01', name='Apple Direct')
    db_session.add_all([contract, supp])
    db_session.flush()

    po = PurchaseOrder(
        company_id=company_id,
        supplier_id=supp.id,
        order_number='PO-APPLE-101',
        status='open',
        ordered_date=today - timedelta(days=20),
        expected_date=today - timedelta(days=5),
    )
    db_session.add(po)

    # Create an extra user to test assignment
    support_user = User(
        email='it-support@example.invalid',
        password_hash=password_hasher.hash('Support-Pass-42!'),
        is_active=True,
    )
    db_session.add(support_user)
    db_session.flush()

    it_role = db_session.scalar(select(Role).where(Role.code == 'it_support', Role.scope == 'company'))
    membership = CompanyMembership(
        company_id=company_id,
        user_id=support_user.id,
        role_id=it_role.id,
        status='active',
    )
    db_session.add(membership)
    db_session.commit()

    # Sync alerts
    sync_res = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert sync_res.status_code == 200
    assert sync_res.json()['created_count'] == 2

    alerts = client.get(f'/api/v1/companies/{company_id}/alerts').json()
    warranty_alert = next(a for a in alerts if a['alert_type'] == 'warranty_expiry')
    po_alert = next(a for a in alerts if a['alert_type'] == 'purchase_order_overdue')

    # 1. Test Acknowledge
    ack_res = client.post(
        f'/api/v1/companies/{company_id}/alerts/{warranty_alert["id"]}/acknowledge',
        json={'notes': 'Renewal quote requested from procurement'},
    )
    assert ack_res.status_code == 200, ack_res.text
    ack_data = ack_res.json()
    assert ack_data['status'] == 'acknowledged'
    assert ack_data['acknowledged_at'] is not None
    assert ack_data['resolution_notes'] == 'Renewal quote requested from procurement'

    # 2. Test Assign
    assign_res = client.post(
        f'/api/v1/companies/{company_id}/alerts/{warranty_alert["id"]}/assign',
        json={'responsible_user_id': str(support_user.id)},
    )
    assert assign_res.status_code == 200, assign_res.text
    assign_data = assign_res.json()
    assert assign_data['responsible_user_id'] == str(support_user.id)
    assert assign_data['responsible_user_email'] == 'it-support@example.invalid'

    # 3. Test Manual Resolve
    resolve_res = client.post(
        f'/api/v1/companies/{company_id}/alerts/{warranty_alert["id"]}/resolve',
        json={'resolution_reason': 'manual_resolution', 'resolution_notes': 'Extended contract received'},
    )
    assert resolve_res.status_code == 200, resolve_res.text
    res_data = resolve_res.json()
    assert res_data['status'] == 'resolved'
    assert res_data['resolution_reason'] == 'manual_resolution'
    assert res_data['resolution_notes'] == 'Extended contract received'

    # 4. Test Dismiss on PO alert
    dismiss_res = client.post(
        f'/api/v1/companies/{company_id}/alerts/{po_alert["id"]}/dismiss',
        json={'resolution_notes': 'Vendor informed backlog delay of 2 days'},
    )
    assert dismiss_res.status_code == 200, dismiss_res.text
    dismiss_data = dismiss_res.json()
    assert dismiss_data['status'] == 'dismissed'
    assert dismiss_data['resolution_reason'] == 'dismissed'

    # 5. Subsequent Sync must NOT resurrect manually resolved or dismissed alerts!
    res_sync2 = client.post(f'/api/v1/companies/{company_id}/alerts/sync')
    assert res_sync2.status_code == 200
    assert res_sync2.json()['created_count'] == 0
    assert res_sync2.json()['active_count'] == 0


def test_alert_company_isolation_and_rbac(client, db_session):
    """Test cross-company isolation and permission enforcement."""
    comp1_id, _ = _setup_company_and_category(client, 'ALT-ISO-1')
    comp2_id, _ = _setup_company_and_category(client, 'ALT-ISO-2')

    # Create user belonging ONLY to Company 2
    comp2_user = User(
        email='co2-manager@example.invalid',
        password_hash=password_hasher.hash('Manager-Pass-42!'),
        is_active=True,
    )
    db_session.add(comp2_user)
    db_session.flush()

    mgr_role = db_session.scalar(select(Role).where(Role.code == 'asset_manager', Role.scope == 'company'))
    membership2 = CompanyMembership(
        company_id=comp2_id,
        user_id=comp2_user.id,
        role_id=mgr_role.id,
        status='active',
    )
    db_session.add(membership2)
    db_session.commit()

    # Login as Company 2 manager
    login_res = client.post(
        '/api/v1/auth/login',
        json={'email': 'co2-manager@example.invalid', 'password': 'Manager-Pass-42!'},
    )
    assert login_res.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']

    # Manager of Company 2 CAN access Company 2 alerts
    c2_res = client.get(f'/api/v1/companies/{comp2_id}/alerts')
    assert c2_res.status_code == 200

    # Manager of Company 2 CANNOT access Company 1 alerts (404 Not Found to prevent tenant enumeration)
    c1_res = client.get(f'/api/v1/companies/{comp1_id}/alerts')
    assert c1_res.status_code == 404

    # Switch to auditor in Company 2 (auditor has alerts.read but NOT alerts.manage)
    auditor_user = User(
        email='co2-auditor@example.invalid',
        password_hash=password_hasher.hash('Auditor-Pass-42!'),
        is_active=True,
    )
    db_session.add(auditor_user)
    db_session.flush()

    auditor_role = db_session.scalar(select(Role).where(Role.code == 'auditor', Role.scope == 'company'))
    membership_aud = CompanyMembership(
        company_id=comp2_id,
        user_id=auditor_user.id,
        role_id=auditor_role.id,
        status='active',
    )
    db_session.add(membership_aud)
    db_session.commit()

    # Login as auditor
    client.post(
        '/api/v1/auth/login',
        json={'email': 'co2-auditor@example.invalid', 'password': 'Auditor-Pass-42!'},
    )
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']

    # Auditor CAN read alerts
    aud_get = client.get(f'/api/v1/companies/{comp2_id}/alerts')
    assert aud_get.status_code == 200

    # Auditor CANNOT trigger sync (403 Forbidden)
    aud_sync = client.post(f'/api/v1/companies/{comp2_id}/alerts/sync')
    assert aud_sync.status_code == 403

    # Verify audit event for alert operations
    # Login back as admin to check audit
    client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']

    # Generate an alert in comp2 and acknowledge it as admin
    client.post(f'/api/v1/companies/{comp2_id}/alerts/sync')
    alerts = client.get(f'/api/v1/companies/{comp2_id}/alerts').json()
    if alerts:
        a_id = alerts[0]['id']
        client.post(f'/api/v1/companies/{comp2_id}/alerts/{a_id}/acknowledge', json={'notes': 'Audited'})
        audit_records = db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.company_id == comp2_id,
                AuditEvent.action == 'asset_alert.acknowledged',
            )
        ).all()
        assert len(audit_records) >= 1
