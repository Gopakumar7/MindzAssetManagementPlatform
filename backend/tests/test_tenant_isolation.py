"""Multi-tenant isolation and security boundary tests for MindZen ALCM/ITAM.

Verifies strict cross-company tenant isolation across all functional domains:
1. Asset read isolation
2. Asset write isolation
3. Procurement isolation (Suppliers, Purchase Orders, Goods Receipts)
4. Maintenance and service contracts isolation
5. Financial lifecycle isolation (Profiles, Depreciation Schedules, Runs, Disposals)
6. Physical verification isolation (Campaigns, Reconciliations, Discrepancies)
7. Alerts and notifications isolation (Company-scoped alerts, user-scoped notifications)
8. Dashboard and reporting isolation (Operational, Financial, JSON and CSV exports)
9. URL and entity ID manipulation safety (Safe 404 denials without oracle disclosure)
10. Background jobs isolation (Scheduled alert evaluation, notifications)
11. Company membership revocation immediate enforcement
12. Unauthenticated and unauthorized access matrix
13. User management, invitation lifecycle, and privilege escalation prevention
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app import models
from app.alert_service import sync_company_alerts
from app.authentication import password_hasher
from app.notification_service import NotificationService
from app.services import create_company, create_asset
from app.schemas import CompanyCreate, AssetCreate, BatchDepreciationRequest


def _login_as(client, email: str, password: str) -> None:
    res = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert res.status_code == 200, f'Login failed for {email}: {res.text}'
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']


def _logout(client) -> None:
    client.post('/api/v1/auth/logout')
    client.cookies.clear()
    client.headers.pop('X-CSRF-Token', None)


@pytest.fixture
def isolation_data(client, db_session):
    """Sets up two isolated companies (Company A and Company B) with dedicated users and domain data."""
    # 1. Create Company A and Company B via System Admin (client default)
    comp_a_res = client.post('/api/v1/companies', json={'code': 'COMP-A', 'name': 'Company Alpha Corp', 'number_prefix': 'COA'})
    assert comp_a_res.status_code == 201, comp_a_res.text
    comp_a_id = UUID(comp_a_res.json()['id'])

    comp_b_res = client.post('/api/v1/companies', json={'code': 'COMP-B', 'name': 'Company Beta Inc', 'number_prefix': 'COB'})
    assert comp_b_res.status_code == 201, comp_b_res.text
    comp_b_id = UUID(comp_b_res.json()['id'])

    # Retrieve categories
    cat_a = db_session.scalars(select(models.AssetCategory).where(models.AssetCategory.company_id == comp_a_id)).first()
    cat_b = db_session.scalars(select(models.AssetCategory).where(models.AssetCategory.company_id == comp_b_id)).first()

    # 2. Roles
    role_admin = db_session.scalar(select(models.Role).where(models.Role.code == 'company_administrator'))
    role_auditor = db_session.scalar(select(models.Role).where(models.Role.code == 'auditor'))
    role_manager = db_session.scalar(select(models.Role).where(models.Role.code == 'asset_manager'))
    sys_admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))

    # 3. Create Users
    # User A Admin
    user_a_admin = models.User(
        email='admin-a@example.invalid',
        password_hash=password_hasher.hash('Admin-Pass-Alpha-42!'),
        is_active=True,
    )
    db_session.add(user_a_admin)
    db_session.flush()
    membership_a_admin = models.CompanyMembership(
        company_id=comp_a_id,
        user_id=user_a_admin.id,
        role_id=role_admin.id,
        status='active',
        assigned_by_id=sys_admin.id,
    )
    db_session.add(membership_a_admin)

    # User A Auditor (read-only role in Company A)
    user_a_auditor = models.User(
        email='auditor-a@example.invalid',
        password_hash=password_hasher.hash('Auditor-Pass-Alpha-42!'),
        is_active=True,
    )
    db_session.add(user_a_auditor)
    db_session.flush()
    membership_a_auditor = models.CompanyMembership(
        company_id=comp_a_id,
        user_id=user_a_auditor.id,
        role_id=role_auditor.id,
        status='active',
        assigned_by_id=sys_admin.id,
    )
    db_session.add(membership_a_auditor)

    # User B Admin
    user_b_admin = models.User(
        email='admin-b@example.invalid',
        password_hash=password_hasher.hash('Admin-Pass-Beta-42!'),
        is_active=True,
    )
    db_session.add(user_b_admin)
    db_session.flush()
    membership_b_admin = models.CompanyMembership(
        company_id=comp_b_id,
        user_id=user_b_admin.id,
        role_id=role_admin.id,
        status='active',
        assigned_by_id=sys_admin.id,
    )
    db_session.add(membership_b_admin)

    # Dual User (Member of both Company A and Company B)
    dual_user = models.User(
        email='dual-user@example.invalid',
        password_hash=password_hasher.hash('Dual-User-Pass-42!'),
        is_active=True,
    )
    db_session.add(dual_user)
    db_session.flush()
    membership_dual_a = models.CompanyMembership(
        company_id=comp_a_id,
        user_id=dual_user.id,
        role_id=role_manager.id,
        status='active',
        assigned_by_id=sys_admin.id,
    )
    membership_dual_b = models.CompanyMembership(
        company_id=comp_b_id,
        user_id=dual_user.id,
        role_id=role_manager.id,
        status='active',
        assigned_by_id=sys_admin.id,
    )
    db_session.add_all([membership_dual_a, membership_dual_b])

    # Outsider User (Active user with no company memberships)
    outsider_user = models.User(
        email='outsider@example.invalid',
        password_hash=password_hasher.hash('Outsider-Pass-42!'),
        is_active=True,
    )
    db_session.add(outsider_user)

    # 4. Domain Data for Company A
    # Asset A1
    asset_a1 = models.Asset(
        company_id=comp_a_id,
        category_id=cat_a.id,
        asset_number='COA-000001',
        serial_number='SN-A100',
        model='ThinkPad T14 Alpha',
        status='in_use',
        acquisition_date=date.today() - timedelta(days=120),
        acquisition_cost=Decimal('2000.00'),
    )
    db_session.add(asset_a1)
    db_session.flush()

    # Supplier A
    supplier_a = models.Supplier(
        company_id=comp_a_id,
        code='SUP-A',
        name='Alpha Tech Supplies',
        email='alice@supplier-alpha.invalid',
        is_active=True,
    )
    db_session.add(supplier_a)
    db_session.flush()

    # Purchase Order A
    po_a = models.PurchaseOrder(
        company_id=comp_a_id,
        supplier_id=supplier_a.id,
        order_number='PO-A-001',
        status='open',
        ordered_date=date.today() - timedelta(days=30),
    )
    db_session.add(po_a)
    db_session.flush()

    po_line_a = models.PurchaseOrderLine(
        company_id=comp_a_id,
        purchase_order_id=po_a.id,
        category_id=cat_a.id,
        description='Company A Laptops',
        quantity_ordered=5,
        unit_cost=Decimal('1000.00'),
    )
    db_session.add(po_line_a)
    db_session.flush()

    # Service Contract A (Warranty)
    contract_a = models.AssetServiceContract(
        company_id=comp_a_id,
        asset_id=asset_a1.id,
        contract_type='warranty',
        provider_name='Lenovo Support Alpha',
        reference_number='WRN-A-001',
        start_date=date.today() - timedelta(days=100),
        end_date=date.today() + timedelta(days=265),
        status='active',
    )
    db_session.add(contract_a)

    # Maintenance Request A
    maint_a = models.MaintenanceRequest(
        company_id=comp_a_id,
        asset_id=asset_a1.id,
        requester_id=user_a_admin.id,
        title='Keyboard key loose on Alpha laptop',
        issue_description='Spacebar sticking',
        priority='normal',
        status='open',
        reported_date=date.today() - timedelta(days=2),
    )
    db_session.add(maint_a)

    # Verification Campaign A
    campaign_a = models.VerificationCampaign(
        company_id=comp_a_id,
        campaign_reference='VCA-2026-01',
        name='Alpha Annual Verification 2026',
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() + timedelta(days=20),
        status='in_progress',
        created_by_id=user_a_admin.id,
    )
    db_session.add(campaign_a)
    db_session.flush()

    discrepancy_a = models.VerificationDiscrepancy(
        company_id=comp_a_id,
        campaign_id=campaign_a.id,
        asset_id=asset_a1.id,
        discrepancy_type='condition_mismatch',
        status='open',
        observed_data={'notes': 'Key loose on keyboard'},
    )
    db_session.add(discrepancy_a)

    # Financial Profile A
    financial_a = models.AssetFinancial(
        company_id=comp_a_id,
        asset_id=asset_a1.id,
        depreciation_method='straight_line',
        useful_life_months=36,
        capitalised_cost=Decimal('2000.00'),
        residual_value=Decimal('200.00'),
        depreciation_start_date=date.today() - timedelta(days=90),
        current_book_value=Decimal('2000.00'),
        accumulated_depreciation=Decimal('0.00'),
        financial_status='active',
        currency='USD',
    )
    db_session.add(financial_a)

    # Asset Alert A
    alert_a = models.AssetAlert(
        company_id=comp_a_id,
        asset_id=asset_a1.id,
        entity_type='asset',
        entity_id=asset_a1.id,
        alert_type='warranty_expiring_soon',
        severity='warning',
        title='Warranty expiring for Alpha asset',
        description='Warranty expires in 265 days',
        status='open',
    )
    db_session.add(alert_a)

    # Notification A for User A Admin
    notif_a = models.Notification(
        company_id=comp_a_id,
        recipient_user_id=user_a_admin.id,
        notification_type='alert_warning',
        title='Alpha Alert: Warranty Expiring',
        message='Review warranty status for Asset COA-000001',
        severity='warning',
        dedup_key='test:notif:a1',
        status='unread',
    )
    db_session.add(notif_a)

    # 5. Domain Data for Company B
    # Asset B1
    asset_b1 = models.Asset(
        company_id=comp_b_id,
        category_id=cat_b.id,
        asset_number='COB-000001',
        serial_number='SN-B100',
        model='Dell Latitude 5520 Beta',
        status='in_use',
        acquisition_date=date.today() - timedelta(days=200),
        acquisition_cost=Decimal('3000.00'),
    )
    db_session.add(asset_b1)
    db_session.flush()

    # Supplier B
    supplier_b = models.Supplier(
        company_id=comp_b_id,
        code='SUP-B',
        name='Beta Enterprise Hardware',
        email='bob@supplier-beta.invalid',
        is_active=True,
    )
    db_session.add(supplier_b)
    db_session.flush()

    # Purchase Order B
    po_b = models.PurchaseOrder(
        company_id=comp_b_id,
        supplier_id=supplier_b.id,
        order_number='PO-B-001',
        status='open',
        ordered_date=date.today() - timedelta(days=60),
    )
    db_session.add(po_b)
    db_session.flush()

    po_line_b = models.PurchaseOrderLine(
        company_id=comp_b_id,
        purchase_order_id=po_b.id,
        category_id=cat_b.id,
        description='Company B Servers',
        quantity_ordered=2,
        unit_cost=Decimal('1500.00'),
    )
    db_session.add(po_line_b)
    db_session.flush()

    # Service Contract B (AMC)
    contract_b = models.AssetServiceContract(
        company_id=comp_b_id,
        asset_id=asset_b1.id,
        contract_type='amc',
        provider_name='Dell ProCare Beta',
        reference_number='AMC-B-001',
        start_date=date.today() - timedelta(days=150),
        end_date=date.today() + timedelta(days=215),
        status='active',
    )
    db_session.add(contract_b)

    # Maintenance Request B
    maint_b = models.MaintenanceRequest(
        company_id=comp_b_id,
        asset_id=asset_b1.id,
        requester_id=user_b_admin.id,
        title='Screen flickering on Beta laptop',
        issue_description='Display issues after driver update',
        priority='urgent',
        status='open',
        reported_date=date.today() - timedelta(days=5),
    )
    db_session.add(maint_b)

    # Verification Campaign B
    campaign_b = models.VerificationCampaign(
        company_id=comp_b_id,
        campaign_reference='VCB-2026-01',
        name='Beta Q1 Verification',
        start_date=date.today() - timedelta(days=15),
        end_date=date.today() + timedelta(days=15),
        status='in_progress',
        created_by_id=user_b_admin.id,
    )
    db_session.add(campaign_b)
    db_session.flush()

    discrepancy_b = models.VerificationDiscrepancy(
        company_id=comp_b_id,
        campaign_id=campaign_b.id,
        asset_id=asset_b1.id,
        discrepancy_type='missing',
        status='open',
        observed_data={'notes': 'Asset not found at designated desk'},
    )
    db_session.add(discrepancy_b)

    # Financial Profile B
    financial_b = models.AssetFinancial(
        company_id=comp_b_id,
        asset_id=asset_b1.id,
        depreciation_method='straight_line',
        useful_life_months=48,
        capitalised_cost=Decimal('3000.00'),
        residual_value=Decimal('300.00'),
        depreciation_start_date=date.today() - timedelta(days=180),
        current_book_value=Decimal('3000.00'),
        accumulated_depreciation=Decimal('0.00'),
        financial_status='active',
        currency='USD',
    )
    db_session.add(financial_b)

    # Asset Alert B
    alert_b = models.AssetAlert(
        company_id=comp_b_id,
        asset_id=asset_b1.id,
        entity_type='asset',
        entity_id=asset_b1.id,
        alert_type='maintenance_overdue',
        severity='critical',
        title='Critical maintenance overdue for Beta asset',
        description='Urgent ticket pending for 5 days',
        status='open',
    )
    db_session.add(alert_b)

    # Notification B for User B Admin
    notif_b = models.Notification(
        company_id=comp_b_id,
        recipient_user_id=user_b_admin.id,
        notification_type='alert_critical',
        title='Beta Alert: Urgent Maintenance Overdue',
        message='Screen flicker ticket requires immediate attention',
        severity='critical',
        dedup_key='test:notif:b1',
        status='unread',
    )
    db_session.add(notif_b)

    db_session.commit()

    return {
        'comp_a_id': comp_a_id,
        'comp_b_id': comp_b_id,
        'cat_a_id': cat_a.id,
        'cat_b_id': cat_b.id,
        'user_a_admin': user_a_admin,
        'user_a_auditor': user_a_auditor,
        'user_b_admin': user_b_admin,
        'dual_user': dual_user,
        'outsider_user': outsider_user,
        'asset_a1': asset_a1,
        'asset_b1': asset_b1,
        'supplier_a': supplier_a,
        'supplier_b': supplier_b,
        'po_a': po_a,
        'po_b': po_b,
        'po_line_a': po_line_a,
        'po_line_b': po_line_b,
        'contract_a': contract_a,
        'contract_b': contract_b,
        'maint_a': maint_a,
        'maint_b': maint_b,
        'campaign_a': campaign_a,
        'campaign_b': campaign_b,
        'discrepancy_a': discrepancy_a,
        'discrepancy_b': discrepancy_b,
        'financial_a': financial_a,
        'financial_b': financial_b,
        'alert_a': alert_a,
        'alert_b': alert_b,
        'notif_a': notif_a,
        'notif_b': notif_b,
        'membership_a_admin': membership_a_admin,
        'membership_b_admin': membership_b_admin,
        'membership_dual_a': membership_dual_a,
        'membership_dual_b': membership_dual_b,
    }


# ==============================================================================
# 1. Asset Read Isolation
# ==============================================================================

def test_tenant_asset_read_isolation(client, isolation_data):
    """Scenario 1: Company A user cannot list, search or retrieve Company B assets."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Company A user lists assets for Company A -> gets Asset A1
    res_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets")
    assert res_a.status_code == 200
    asset_ids_a = [UUID(a['id']) for a in res_a.json()['items']]
    assert data['asset_a1'].id in asset_ids_a
    assert data['asset_b1'].id not in asset_ids_a

    # Company A user attempts to list assets for Company B -> 404 Not Found (safe denial)
    res_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/assets")
    assert res_b.status_code == 404

    # Company A user retrieves Asset A1 -> 200 OK
    res_asset_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_a1'].id}")
    assert res_asset_a.status_code == 200
    assert res_asset_a.json()['serial_number'] == 'SN-A100'

    # Company A user attempts to retrieve Asset B1 under Company B URL -> 404 Not Found
    res_asset_b_via_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/assets/{data['asset_b1'].id}")
    assert res_asset_b_via_b.status_code == 404

    # Company A user attempts to retrieve Asset B1 under Company A URL (ID hijacking) -> 404 Not Found
    res_asset_b_via_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}")
    assert res_asset_b_via_a.status_code == 404
    assert 'not found' in res_asset_b_via_a.json()['detail'].lower()


# ==============================================================================
# 2. Asset Write Isolation
# ==============================================================================

def test_tenant_asset_write_isolation(client, isolation_data, db_session):
    """Scenario 2: Company A user cannot create, update, reassign or retire Company B assets."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # 1. Attempt to create asset under Company B -> 404
    create_b = client.post(
        f"/api/v1/companies/{data['comp_b_id']}/assets",
        json={'category_id': str(data['cat_b_id']), 'model': 'Illicit Laptop', 'serial_number': 'HACK-001'},
    )
    assert create_b.status_code == 404

    # 2. Attempt to update Asset B1 under Company B -> 404
    patch_b = client.patch(
        f"/api/v1/companies/{data['comp_b_id']}/assets/{data['asset_b1'].id}",
        json={'model': 'Tampered Model'},
    )
    assert patch_b.status_code == 404

    # 3. Attempt to update Asset B1 under Company A -> 404
    patch_b_via_a = client.patch(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}",
        json={'model': 'Tampered Model via A'},
    )
    assert patch_b_via_a.status_code == 404

    # 4. Attempt to assign Asset B1 under Company A -> 404
    assign_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/assignments",
        json={'recipient_id': str(data['user_a_admin'].id), 'effective_date': str(date.today())},
    )
    assert assign_b.status_code == 404

    # 5. Attempt to record usage for Asset B1 under Company A -> 404
    usage_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/usages",
        json={'start_date': str(date.today()), 'department_id': str(uuid4())},
    )
    assert usage_b.status_code == 404

    # Verify DB: Asset B1 remains untouched
    db_session.expire_all()
    b1_in_db = db_session.get(models.Asset, data['asset_b1'].id)
    assert b1_in_db.model == 'Dell Latitude 5520 Beta'
    assert b1_in_db.status == 'in_use'


# ==============================================================================
# 3. Procurement Isolation
# ==============================================================================

def test_tenant_procurement_isolation(client, isolation_data, db_session):
    """Scenario 3: Purchase orders, goods receipts and suppliers cannot cross company boundaries."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Suppliers isolation
    sups_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/suppliers")
    assert sups_a.status_code == 200
    sup_codes_a = [s['code'] for s in sups_a.json()]
    assert 'SUP-A' in sup_codes_a
    assert 'SUP-B' not in sup_codes_a

    sups_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/suppliers")
    assert sups_b.status_code == 404

    # Cross-tenant supplier creation
    sup_b_create = client.post(
        f"/api/v1/companies/{data['comp_b_id']}/suppliers",
        json={'code': 'SUP-HACK', 'name': 'Hacker Supplier'},
    )
    assert sup_b_create.status_code == 404

    # Purchase Orders isolation
    pos_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/purchase-orders")
    assert pos_a.status_code == 200
    po_nums_a = [p['order_number'] for p in pos_a.json()]
    assert 'PO-A-001' in po_nums_a
    assert 'PO-B-001' not in po_nums_a

    pos_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/purchase-orders")
    assert pos_b.status_code == 404

    # Retrieve PO B under Company A -> 404
    po_b_via_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/purchase-orders/{data['po_b'].id}")
    assert po_b_via_a.status_code == 404

    # PO creation with cross-tenant Supplier ID -> 422 Unprocessable Entity
    po_cross_supplier = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/purchase-orders",
        json={
            'supplier_id': str(data['supplier_b'].id),
            'order_number': 'PO-A-CROSS-1',
            'ordered_date': str(date.today()),
            'lines': [{
                'category_id': str(data['cat_a_id']),
                'description': 'Laptops',
                'quantity_ordered': 1,
                'unit_cost': '1000.00',
            }],
        },
    )
    assert po_cross_supplier.status_code == 422
    assert 'supplier must be active in this company' in po_cross_supplier.json()['detail'].lower()

    # PO creation with cross-tenant Category ID -> 422
    po_cross_category = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/purchase-orders",
        json={
            'supplier_id': str(data['supplier_a'].id),
            'order_number': 'PO-A-CROSS-2',
            'ordered_date': str(date.today()),
            'lines': [{
                'category_id': str(data['cat_b_id']),
                'description': 'Laptops',
                'quantity_ordered': 1,
                'unit_cost': '1000.00',
            }],
        },
    )
    assert po_cross_category.status_code == 422
    assert 'category must be active in this company' in po_cross_category.json()['detail'].lower()

    # Goods receipt receiving Company B PO -> 404
    gr_cross_po = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/purchase-orders/{data['po_b'].id}/goods-receipts",
        json={
            'receipt_number': 'GR-HACK-01',
            'received_date': str(date.today()),
            'lines': [{
                'purchase_order_line_id': str(data['po_line_b'].id),
                'quantity_received': 1,
            }],
        },
    )
    assert gr_cross_po.status_code == 404


# ==============================================================================
# 4. Maintenance and Service Contracts Isolation
# ==============================================================================

def test_tenant_maintenance_and_service_isolation(client, isolation_data, db_session):
    """Scenario 4: Maintenance requests, warranty contracts and AMC records cannot cross company boundaries."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Service Contracts listing
    contracts_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_a1'].id}/service-contracts")
    assert contracts_a.status_code == 200
    assert len(contracts_a.json()) == 1
    assert contracts_a.json()[0]['provider_name'] == 'Lenovo Support Alpha'

    # Cannot read contracts of Asset B
    contracts_b_via_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/service-contracts")
    assert contracts_b_via_a.status_code == 404

    contracts_b_via_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/assets/{data['asset_b1'].id}/service-contracts")
    assert contracts_b_via_b.status_code == 404

    # Cannot create contract on Asset B
    create_contract_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/service-contracts",
        json={
            'contract_type': 'warranty',
            'provider_name': 'Hacker Care',
            'start_date': str(date.today()),
            'end_date': str(date.today() + timedelta(days=365)),
        },
    )
    assert create_contract_b.status_code == 404

    # Maintenance Requests listing
    maint_list_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/maintenance-requests")
    assert maint_list_a.status_code == 200
    maint_titles_a = [m['title'] for m in maint_list_a.json()]
    assert 'Keyboard key loose on Alpha laptop' in maint_titles_a
    assert 'Screen flickering on Beta laptop' not in maint_titles_a

    maint_list_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/maintenance-requests")
    assert maint_list_b.status_code == 404

    # Maintenance ticket creation targeting Asset B under Company A -> 404
    maint_cross_asset = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/maintenance-requests",
        json={
            'asset_id': str(data['asset_b1'].id),
            'title': 'Cross-company issue',
            'issue_description': 'Attempting maintenance on other tenant asset',
            'priority': 'normal',
            'reported_date': str(date.today()),
        },
    )
    assert maint_cross_asset.status_code == 404

    # Maintenance ticket creation targeting User B as assignee -> 422
    maint_cross_user = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/maintenance-requests",
        json={
            'asset_id': str(data['asset_a1'].id),
            'assignee_id': str(data['user_b_admin'].id),
            'title': 'Cross-tenant assignment issue',
            'issue_description': 'Assigning to User B',
            'priority': 'normal',
            'reported_date': str(date.today()),
        },
    )
    assert maint_cross_user.status_code == 422
    assert 'active member' in maint_cross_user.json()['detail'].lower()


# ==============================================================================
# 5. Financial Lifecycle Isolation
# ==============================================================================

def test_tenant_financial_lifecycle_isolation(client, isolation_data, db_session):
    """Scenario 5: Asset financial profiles, depreciation schedules, runs and disposals are strictly isolated."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Financial Profile Read
    fin_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_a1'].id}/financial")
    assert fin_a.status_code == 200
    assert Decimal(str(fin_a.json()['capitalised_cost'])) == Decimal('2000.00')

    fin_b_via_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/financial")
    assert fin_b_via_a.status_code == 404

    fin_b_via_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/assets/{data['asset_b1'].id}/financial")
    assert fin_b_via_b.status_code == 404

    # Financial Profile Configure
    put_fin_b = client.put(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/financial",
        json={
            'depreciation_method': 'straight_line',
            'useful_life_months': 36,
            'capitalised_cost': 5000.0,
            'residual_value': 100.0,
            'depreciation_start_date': str(date.today()),
        },
    )
    assert put_fin_b.status_code == 404

    # Depreciation schedule of Asset B -> 404
    sched_b = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/depreciation-schedule")
    assert sched_b.status_code == 404

    # Batch depreciation execution on Company A
    batch_res = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/depreciation-entries/batch",
        json={'period': date.today().strftime('%Y-%m')},
    )
    assert batch_res.status_code == 200

    # Verify DB: Only Company A has depreciation entries; Company B has none
    db_session.expire_all()
    entries_a = db_session.scalars(
        select(models.AssetDepreciationEntry).where(models.AssetDepreciationEntry.company_id == data['comp_a_id'])
    ).all()
    entries_b = db_session.scalars(
        select(models.AssetDepreciationEntry).where(models.AssetDepreciationEntry.company_id == data['comp_b_id'])
    ).all()
    assert len(entries_a) >= 1
    assert len(entries_b) == 0

    # Disposal isolation
    dispose_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}/dispose",
        json={
            'disposal_date': str(date.today()),
            'disposal_reason': 'sold',
            'disposal_method': 'sale',
            'sale_proceeds': '500.00',
        },
    )
    assert dispose_b.status_code == 404


# ==============================================================================
# 6. Verification Isolation
# ==============================================================================

def test_tenant_verification_isolation(client, isolation_data, db_session):
    """Scenario 6: Verification campaigns, reconciliations and discrepancies are strictly isolated."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Verification Campaigns listing
    camps_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns")
    assert camps_a.status_code == 200
    refs_a = [c['campaign_reference'] for c in camps_a.json()]
    assert 'VCA-2026-01' in refs_a
    assert 'VCB-2026-01' not in refs_a

    camps_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/verification-campaigns")
    assert camps_b.status_code == 404

    # Retrieve Campaign B -> 404
    camp_b_via_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns/{data['campaign_b'].id}")
    assert camp_b_via_a.status_code == 404

    # Discrepancies listing
    discs_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns/{data['campaign_a'].id}/discrepancies")
    assert discs_a.status_code == 200
    disc_ids_a = [UUID(d['id']) for d in discs_a.json()]
    assert data['discrepancy_a'].id in disc_ids_a
    assert data['discrepancy_b'].id not in disc_ids_a

    # Resolve Discrepancy B under Company A -> 404
    resolve_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns/{data['campaign_a'].id}/discrepancies/{data['discrepancy_b'].id}/resolve",
        json={'resolution_action': 'dismiss', 'resolution_notes': 'Cross-company resolution attempt'},
    )
    assert resolve_b.status_code == 404


# ==============================================================================
# 7. Alerts and Notifications Isolation
# ==============================================================================

def test_tenant_alerts_and_notifications_isolation(client, isolation_data, db_session):
    """Scenario 7: Alerts generated for Company A are never visible to Company B.
    Notifications are strictly delivered to intended recipients and isolated by user and company.
    """
    data = isolation_data

    # User A Admin tests Alerts
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    alerts_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/alerts")
    assert alerts_a.status_code == 200
    alert_ids_a = [UUID(a['id']) for a in alerts_a.json()]
    assert data['alert_a'].id in alert_ids_a
    assert data['alert_b'].id not in alert_ids_a

    alerts_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/alerts")
    assert alerts_b.status_code == 404

    # Cannot acknowledge Alert B
    ack_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/alerts/{data['alert_b'].id}/acknowledge",
        json={'notes': 'Unauthorized acknowledgement'},
    )
    assert ack_b.status_code == 404

    # Cannot resolve Alert B
    res_b = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/alerts/{data['alert_b'].id}/resolve",
        json={'notes': 'Unauthorized resolution'},
    )
    assert res_b.status_code == 404

    # Notifications feed for User A Admin
    notifs_a = client.get('/api/v1/notifications')
    assert notifs_a.status_code == 200
    notif_ids_a = [UUID(n['id']) for n in notifs_a.json()]
    assert data['notif_a'].id in notif_ids_a
    assert data['notif_b'].id not in notif_ids_a

    unread_count_a = client.get('/api/v1/notifications/unread-count')
    assert unread_count_a.status_code == 200
    assert unread_count_a.json()['unread_count'] == 1

    # User A Admin attempts to mark User B's notification as read -> 404
    mark_b = client.post(f"/api/v1/notifications/{data['notif_b'].id}/read")
    assert mark_b.status_code == 404

    # User B Admin logs in
    _login_as(client, 'admin-b@example.invalid', 'Admin-Pass-Beta-42!')

    notifs_b = client.get('/api/v1/notifications')
    assert notifs_b.status_code == 200
    notif_ids_b = [UUID(n['id']) for n in notifs_b.json()]
    assert data['notif_b'].id in notif_ids_b
    assert data['notif_a'].id not in notif_ids_b

    # User B Admin marks their own notification as read -> 200
    mark_own = client.post(f"/api/v1/notifications/{data['notif_b'].id}/read")
    assert mark_own.status_code == 200
    assert mark_own.json()['status'] == 'read'


# ==============================================================================
# 8. Dashboard and Reporting Isolation
# ==============================================================================

def test_tenant_dashboard_and_reporting_isolation(client, isolation_data):
    """Scenario 8: Operational metrics, financial summaries and exported reports include only active company's data."""
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # Operational Dashboard
    dash_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/dashboard")
    assert dash_a.status_code == 200
    dash_json = dash_a.json()
    assert dash_json['total_assets'] == 1  # Only Asset A1, not 2
    assert dash_json['assets_by_status']['in_use'] == 1

    dash_b = client.get(f"/api/v1/companies/{data['comp_b_id']}/dashboard")
    assert dash_b.status_code == 404

    # Financial Dashboard
    fin_dash_a = client.get(f"/api/v1/companies/{data['comp_a_id']}/dashboard/financial")
    assert fin_dash_a.status_code == 200
    fin_dash_json = fin_dash_a.json()
    # Company A capitalised cost is 2000.00; Company B is 3000.00; should not be aggregated to 5000.00
    assert Decimal(str(fin_dash_json['total_capitalised_cost'])) == Decimal('2000.00')

    # Reports: Assets
    rep_assets = client.get(f"/api/v1/companies/{data['comp_a_id']}/reports/asset-register")
    assert rep_assets.status_code == 200
    rep_serials = [a['serial_number'] for a in rep_assets.json()]
    assert 'SN-A100' in rep_serials
    assert 'SN-B100' not in rep_serials

    # Company B reports cannot be accessed
    assert client.get(f"/api/v1/companies/{data['comp_b_id']}/reports/asset-register").status_code == 404

    # Reports: Verification Campaigns CSV Export
    rep_csv = client.get(f"/api/v1/companies/{data['comp_a_id']}/reports/verification-campaigns?format=csv")
    assert rep_csv.status_code == 200
    assert 'text/csv' in rep_csv.headers['content-type']
    csv_text = rep_csv.text
    assert 'VCA-2026-01' in csv_text
    assert 'VCB-2026-01' not in csv_text


# ==============================================================================
# 9. URL and Entity ID Manipulation Safety
# ==============================================================================

def test_tenant_url_and_id_manipulation_safety(client, isolation_data):
    """Scenario 9: Substituting Company B ID into Company A URL fails safely with 404
    without disclosing the existence or details of the other company's data (anti-oracle).
    """
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')
    non_existent_id = uuid4()

    test_endpoints = [
        (f"/api/v1/companies/{data['comp_a_id']}/assets/{data['asset_b1'].id}",
         f"/api/v1/companies/{data['comp_a_id']}/assets/{non_existent_id}"),
        (f"/api/v1/companies/{data['comp_a_id']}/suppliers/{data['supplier_b'].id}",
         f"/api/v1/companies/{data['comp_a_id']}/suppliers/{non_existent_id}"),
        (f"/api/v1/companies/{data['comp_a_id']}/purchase-orders/{data['po_b'].id}",
         f"/api/v1/companies/{data['comp_a_id']}/purchase-orders/{non_existent_id}"),
        (f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns/{data['campaign_b'].id}",
         f"/api/v1/companies/{data['comp_a_id']}/verification-campaigns/{non_existent_id}"),
    ]

    for cross_url, random_url in test_endpoints:
        res_cross = client.get(cross_url)
        res_random = client.get(random_url)
        # Both must return 404
        assert res_cross.status_code == 404
        assert res_random.status_code == 404
        # Response detail must not reveal that cross_url entity actually exists in another company
        assert res_cross.json() == res_random.json()


# ==============================================================================
# 10. Background Jobs Isolation
# ==============================================================================

def test_tenant_background_jobs_isolation(client, isolation_data, db_session):
    """Scenario 10: Scheduled alert evaluation and notification processing isolate companies."""
    data = isolation_data

    # Alert evaluation for Company A
    res_a = sync_company_alerts(db_session, data['comp_a_id'])
    assert res_a is not None

    # Verify all alerts in db for Company A belong to Company A
    alerts_a = db_session.scalars(
        select(models.AssetAlert).where(models.AssetAlert.company_id == data['comp_a_id'])
    ).all()
    for alert in alerts_a:
        assert alert.company_id == data['comp_a_id']

    # Process alert notifications for Company A
    created = NotificationService.process_alert_notifications(db_session, data['comp_a_id'])
    # Any created notification must belong to Company A and have a recipient from Company A
    notifs = db_session.scalars(
        select(models.Notification).where(models.Notification.company_id == data['comp_a_id'])
    ).all()
    for notif in notifs:
        assert notif.recipient_user_id in {data['user_a_admin'].id, data['user_a_auditor'].id, data['dual_user'].id}
        assert notif.recipient_user_id != data['user_b_admin'].id


# ==============================================================================
# 11. Company Membership Revocation Immediate Enforcement
# ==============================================================================

def test_tenant_membership_revocation_immediate_enforcement(client, isolation_data, db_session):
    """Scenario 11: When user membership in Company A is revoked, their access to Company A is immediately
    terminated, while their access to Company B continues uninterrupted.
    """
    data = isolation_data
    _login_as(client, 'dual-user@example.invalid', 'Dual-User-Pass-42!')

    # Dual user can initially access both companies
    assert client.get(f"/api/v1/companies/{data['comp_a_id']}/assets").status_code == 200
    assert client.get(f"/api/v1/companies/{data['comp_b_id']}/assets").status_code == 200

    # Revoke Dual user's membership in Company A
    membership_a = db_session.get(models.CompanyMembership, data['membership_dual_a'].id)
    membership_a.status = 'revoked'
    db_session.commit()

    # Immediate access check without relogin:
    # Company A returns 404 immediately
    res_a_after = client.get(f"/api/v1/companies/{data['comp_a_id']}/assets")
    assert res_a_after.status_code == 404

    # Company B remains 200 OK
    res_b_after = client.get(f"/api/v1/companies/{data['comp_b_id']}/assets")
    assert res_b_after.status_code == 200


# ==============================================================================
# 12. Unauthenticated and Unauthorized Matrix
# ==============================================================================

def test_tenant_unauthenticated_and_unauthorized_matrix(client, isolation_data):
    """Scenario 12: Unauthenticated and unauthorized access matrix."""
    data = isolation_data

    # 1. Unauthenticated requests
    _logout(client)
    assert client.get(f"/api/v1/companies/{data['comp_a_id']}/assets").status_code == 401
    assert client.post(f"/api/v1/companies/{data['comp_a_id']}/assets", json={}).status_code == 401
    assert client.get('/api/v1/notifications').status_code == 401
    assert client.get('/api/v1/auth/me').status_code == 401

    # 2. Authenticated Outsider user (no company memberships)
    _login_as(client, 'outsider@example.invalid', 'Outsider-Pass-42!')
    me_res = client.get('/api/v1/auth/me')
    assert me_res.status_code == 200
    assert me_res.json()['memberships'] == []

    # Accessing company returns 404 (prevents company enumeration)
    assert client.get(f"/api/v1/companies/{data['comp_a_id']}/assets").status_code == 404
    assert client.post(f"/api/v1/companies/{data['comp_a_id']}/assets", json={}).status_code == 404

    # 3. Authenticated Auditor in Company A (read-only role)
    _login_as(client, 'auditor-a@example.invalid', 'Auditor-Pass-Alpha-42!')
    # Read is allowed
    assert client.get(f"/api/v1/companies/{data['comp_a_id']}/assets").status_code == 200
    # Write is forbidden (403)
    write_res = client.post(
        f"/api/v1/companies/{data['comp_a_id']}/assets",
        json={'category_id': str(data['cat_a_id']), 'model': 'Unauthorized Laptop'},
    )
    assert write_res.status_code == 403


# ==============================================================================
# 13. User Management, Invitation Lifecycle, and Privilege Escalation Prevention
# ==============================================================================

def test_tenant_user_management_and_privilege_escalation_prevention(client, isolation_data, db_session):
    """User and Company Management verification:
    - Company admin can invite members for their company
    - Company admin cannot invite members for another company
    - Company admin cannot grant system administrator privileges
    - Company admin cannot modify their own membership
    - Invitation lifecycle: bound to company, cannot be reused, audited
    """
    data = isolation_data
    _login_as(client, 'admin-a@example.invalid', 'Admin-Pass-Alpha-42!')

    # 1. Company A Admin invites a new user to Company A
    invite_res = client.post(
        f"/api/v1/security/companies/{data['comp_a_id']}/invitations",
        json={'email': 'new-hire@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invite_res.status_code == 201
    invite_data = invite_res.json()
    raw_token = invite_data['token']
    assert raw_token is not None

    # 2. Company A Admin cannot invite to Company B -> 404
    invite_b_res = client.post(
        f"/api/v1/security/companies/{data['comp_b_id']}/invitations",
        json={'email': 'spy@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invite_b_res.status_code == 404

    # 3. Company A Admin cannot grant system administrator role -> 422
    priv_escalate = client.post(
        f"/api/v1/security/companies/{data['comp_a_id']}/invitations",
        json={'email': 'escalate@example.invalid', 'role_code': 'system_administrator'},
    )
    assert priv_escalate.status_code == 422
    assert 'unknown company role' in priv_escalate.json()['detail'].lower()

    # 4. Company A Admin cannot modify their own membership -> 403
    own_mod = client.patch(
        f"/api/v1/security/companies/{data['comp_a_id']}/members/{data['membership_a_admin'].id}",
        json={'role_code': 'read_only_user'},
    )
    assert own_mod.status_code == 403
    assert 'cannot change your own membership' in own_mod.json()['detail'].lower()

    # 5. Company A Admin cannot modify membership of Company B user -> 404
    mod_b = client.patch(
        f"/api/v1/security/companies/{data['comp_a_id']}/members/{data['membership_b_admin'].id}",
        json={'status': 'revoked'},
    )
    assert mod_b.status_code == 404

    # 6. Invitation acceptance lifecycle
    _logout(client)
    accept_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': raw_token, 'password': 'NewUser-SecurePass-42!'},
        headers={'Origin': 'http://localhost:4200'},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()['status'] == 'invitation_accepted'

    # Cannot accept same invitation token again (single-use)
    reaccept_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': raw_token, 'password': 'AnotherPassword-42!'},
        headers={'Origin': 'http://localhost:4200'},
    )
    assert reaccept_res.status_code == 400

    # 7. Verify security audit events recorded for user and membership actions
    db_session.expire_all()
    audit_events = db_session.scalars(
        select(models.AuditEvent).where(
            models.AuditEvent.action.in_(['security.member.invited', 'auth.invitation.accept'])
        )
    ).all()
    actions = [e.action for e in audit_events]
    assert 'security.member.invited' in actions
    assert 'auth.invitation.accept' in actions
