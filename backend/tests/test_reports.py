from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.authentication import password_hasher
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetServiceContract,
    CompanyMembership,
    Department,
    GoodsReceipt,
    GoodsReceiptLine,
    Location,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Site,
    Supplier,
    User,
)


def create_test_company(client, code: str, prefix: str = 'MZREP'):
    response = client.post(
        '/api/v1/companies',
        json={'code': code, 'name': f'{code} Enterprise', 'number_prefix': prefix},
    )
    assert response.status_code == 201, response.text
    return response.json()



def create_user_with_role(db_session, company_id: UUID, email: str, role_code: str) -> User:
    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == role_code))
    user = User(
        email=email,
        password_hash=password_hasher.hash('Test-Password-42!'),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        CompanyMembership(
            company_id=company_id,
            user_id=user.id,
            role_id=role.id,
            status='active',
        )
    )
    db_session.commit()
    return user


def test_empty_company_dashboard_returns_genuine_zeroes(client):
    company = create_test_company(client, 'REP-ZERO')
    res = client.get(f"/api/v1/companies/{company['id']}/dashboard")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data['total_assets'] == 0
    assert data['assets_by_status'] == {}
    assert data['assets_by_category'] == []
    assert data['assets_by_site'] == []
    assert data['assets_by_department'] == []
    assert data['expiring_contracts_count'] == 0
    assert data['expiring_contracts'] == []
    assert data['maintenance_summary'] == {
        'open': 0,
        'in_progress': 0,
        'resolved': 0,
        'closed': 0,
        'total_open_and_in_progress': 0,
    }
    assert data['procurement_summary'] == {
        'total_purchase_orders': 0,
        'orders_by_status': {},
        'total_goods_receipts': 0,
        'total_items_received': 0,
        'total_items_rejected': 0,
    }
    assert isinstance(data['recent_activity'], list)


def test_dashboard_metrics_and_date_boundaries(client, db_session):
    company = create_test_company(client, 'REP-DASH')
    cid = company['id']
    cid_uuid = UUID(cid)

    # Setup categories, site, dept
    cat1 = client.get(f"/api/v1/companies/{cid}/categories").json()[0]
    site_res = client.post(
        f"/api/v1/companies/{cid}/sites",
        json={'code': 'HQ', 'name': 'Headquarters'},
    )
    assert site_res.status_code == 201
    site = site_res.json()

    dept_res = client.post(
        f"/api/v1/companies/{cid}/departments",
        json={'code': 'ENG', 'name': 'Engineering'},
    )
    assert dept_res.status_code == 201
    dept = dept_res.json()

    # Create 3 assets: 2 in_stock, 1 assigned
    a1_res = client.post(
        f"/api/v1/companies/{cid}/assets",
        json={
            'category_id': cat1['id'],
            'model': 'ThinkPad X1',
            'site_id': site['id'],
            'responsible_department_id': dept['id'],
            'status': 'in_stock',
        },
    )
    assert a1_res.status_code == 201
    a1 = a1_res.json()

    a2_res = client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat1['id'], 'model': 'Dell XPS', 'status': 'in_stock'},
    )
    assert a2_res.status_code == 201
    a2 = a2_res.json()

    # Assign a2 via direct DB update to test 'assigned' status
    asset2_obj = db_session.get(Asset, UUID(a2['id']))
    asset2_obj.status = 'assigned'
    asset2_obj.custodian_name = 'worker@mindzen.invalid'
    db_session.commit()

    # Service contracts for date boundary testing
    today = date.today()
    # Contract 1: Expiring in 10 days -> included
    c1 = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        contract_type='warranty',
        reference_number='WAR-10D',
        start_date=today - timedelta(days=300),
        end_date=today + timedelta(days=10),
        status='active',
    )
    # Contract 2: Expiring in exactly 30 days -> included (boundary)
    c2 = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        contract_type='amc',
        reference_number='AMC-30D',
        start_date=today - timedelta(days=300),
        end_date=today + timedelta(days=30),
        status='active',
    )
    # Contract 3: Expiring in 31 days -> NOT included in 30-day window
    c3 = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        contract_type='amc',
        reference_number='AMC-31D',
        start_date=today - timedelta(days=300),
        end_date=today + timedelta(days=31),
        status='active',
    )
    # Contract 4: Already expired yesterday -> NOT included
    c4 = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        contract_type='warranty',
        reference_number='WAR-EXP',
        start_date=today - timedelta(days=400),
        end_date=today - timedelta(days=1),
        status='active',
    )
    # Contract 5: Within 30 days but cancelled -> NOT included
    c5 = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        contract_type='warranty',
        reference_number='WAR-CANC',
        start_date=today - timedelta(days=100),
        end_date=today + timedelta(days=5),
        status='cancelled',
    )
    db_session.add_all([c1, c2, c3, c4, c5])

    # Maintenance requests
    member = create_user_with_role(db_session, cid_uuid, 'tech@mindzen.invalid', 'it_support')
    m_open = MaintenanceRequest(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        requester_id=member.id,
        title='Broken keyboard',
        issue_description='Spacebar sticking',
        status='open',
        reported_date=today,
    )
    m_prog = MaintenanceRequest(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        requester_id=member.id,
        title='Battery check',
        issue_description='Health degraded',
        status='in_progress',
        reported_date=today,
    )
    m_closed = MaintenanceRequest(
        company_id=cid_uuid,
        asset_id=UUID(a1['id']),
        requester_id=member.id,
        title='Fan cleaning',
        issue_description='Noisy fan',
        status='closed',
        reported_date=today - timedelta(days=5),
        completed_date=today - timedelta(days=2),
    )
    db_session.add_all([m_open, m_prog, m_closed])

    # Procurement: supplier, PO, goods receipt
    sup = Supplier(company_id=cid_uuid, code='SUP-TEST', name='Acme Supplies')
    db_session.add(sup)
    db_session.flush()

    po = PurchaseOrder(
        company_id=cid_uuid,
        supplier_id=sup.id,
        order_number='PO-DASH-001',
        status='partially_received',
        ordered_date=today,
    )
    db_session.add(po)
    db_session.flush()

    pol = PurchaseOrderLine(
        company_id=cid_uuid,
        purchase_order_id=po.id,
        category_id=UUID(cat1['id']),
        description='Monitors',
        quantity_ordered=5,
        unit_cost=Decimal('200.00'),
    )
    db_session.add(pol)
    db_session.flush()

    gr = GoodsReceipt(
        company_id=cid_uuid,
        purchase_order_id=po.id,
        receipt_number='GRN-DASH-001',
        received_date=today,
    )
    db_session.add(gr)
    db_session.flush()

    grl = GoodsReceiptLine(
        company_id=cid_uuid,
        goods_receipt_id=gr.id,
        purchase_order_id=po.id,
        purchase_order_line_id=pol.id,
        quantity_received=3,
        quantity_rejected=1,
    )
    db_session.add(grl)
    db_session.commit()

    # Now call dashboard endpoint
    res = client.get(f"/api/v1/companies/{cid}/dashboard")
    assert res.status_code == 200, res.text
    data = res.json()

    # Verify total & status
    assert data['total_assets'] == 2
    assert data['assets_by_status']['in_stock'] == 1
    assert data['assets_by_status']['assigned'] == 1

    # Category breakdown
    assert len(data['assets_by_category']) >= 1
    assert data['assets_by_category'][0]['count'] == 2

    # Site & Department breakdown
    site_names = [s['site_name'] for s in data['assets_by_site']]
    assert 'Headquarters' in site_names
    assert 'Unassigned' in site_names

    dept_names = [d['department_name'] for d in data['assets_by_department']]
    assert 'Engineering' in dept_names
    assert 'Unassigned' in dept_names

    # 30-day expiring contracts boundary verification
    # Exactly c1 (10 days) and c2 (30 days) must be present.
    assert data['expiring_contracts_count'] == 2
    expiring_refs = [c['reference_number'] for c in data['expiring_contracts']]
    assert 'WAR-10D' in expiring_refs
    assert 'AMC-30D' in expiring_refs
    assert 'AMC-31D' not in expiring_refs
    assert 'WAR-EXP' not in expiring_refs
    assert 'WAR-CANC' not in expiring_refs

    # Maintenance summary
    assert data['maintenance_summary']['open'] == 1
    assert data['maintenance_summary']['in_progress'] == 1
    assert data['maintenance_summary']['closed'] == 1
    assert data['maintenance_summary']['total_open_and_in_progress'] == 2

    # Procurement summary
    assert data['procurement_summary']['total_purchase_orders'] == 1
    assert data['procurement_summary']['orders_by_status'] == {'partially_received': 1}
    assert data['procurement_summary']['total_goods_receipts'] == 1
    assert data['procurement_summary']['total_items_received'] == 3
    assert data['procurement_summary']['total_items_rejected'] == 1


def test_asset_register_report_filters(client, db_session):
    company = create_test_company(client, 'REP-ASSETS')
    cid = company['id']
    cat = client.get(f"/api/v1/companies/{cid}/categories").json()[0]

    # Create assets with distinct models and numbers
    client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'MacBook Pro 16', 'manufacturer': 'Apple'},
    )
    client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'Precision 5570', 'manufacturer': 'Dell'},
    )

    # 1. Full register
    res = client.get(f"/api/v1/companies/{cid}/reports/asset-register")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2

    # 2. Search filter
    res_search = client.get(f"/api/v1/companies/{cid}/reports/asset-register?search=MacBook")
    assert res_search.status_code == 200
    search_items = res_search.json()
    assert len(search_items) == 1
    assert search_items[0]['model'] == 'MacBook Pro 16'

    # 3. Status filter
    res_status = client.get(f"/api/v1/companies/{cid}/reports/asset-register?status=in_stock")
    assert res_status.status_code == 200
    assert len(res_status.json()) == 2


def test_asset_allocation_report(client, db_session):
    company = create_test_company(client, 'REP-ALLOC')
    cid = company['id']
    cid_uuid = UUID(cid)
    cat = client.get(f"/api/v1/companies/{cid}/categories").json()[0]

    # Create 1 assigned asset and 1 in-stock asset
    a1 = client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'Assigned ThinkPad'},
    ).json()
    client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'In-Stock ThinkPad'},
    )

    # Mark a1 as assigned
    asset_obj = db_session.get(Asset, UUID(a1['id']))
    asset_obj.status = 'assigned'
    asset_obj.custodian_name = 'dev-alice@mindzen.invalid'
    db_session.commit()

    # Query allocation report
    res = client.get(f"/api/v1/companies/{cid}/reports/asset-allocation")
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    assert items[0]['asset_number'] == a1['asset_number']
    assert items[0]['recipient_email'] == 'dev-alice@mindzen.invalid'
    assert items[0]['status'] == 'assigned'


def test_warranty_expiry_report_computed_coverage_status(client, db_session):
    company = create_test_company(client, 'REP-WAR')
    cid = company['id']
    cid_uuid = UUID(cid)
    cat = client.get(f"/api/v1/companies/{cid}/categories").json()[0]
    a = client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'Workstation'},
    ).json()

    today = date.today()
    c_active = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a['id']),
        contract_type='warranty',
        reference_number='REF-ACTIVE',
        start_date=today - timedelta(days=100),
        end_date=today + timedelta(days=200),
        status='active',
    )
    c_soon = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a['id']),
        contract_type='amc',
        reference_number='REF-SOON',
        start_date=today - timedelta(days=100),
        end_date=today + timedelta(days=15),
        status='active',
    )
    c_exp = AssetServiceContract(
        company_id=cid_uuid,
        asset_id=UUID(a['id']),
        contract_type='warranty',
        reference_number='REF-EXP',
        start_date=today - timedelta(days=200),
        end_date=today - timedelta(days=10),
        status='active',
    )
    db_session.add_all([c_active, c_soon, c_exp])
    db_session.commit()

    # 1. All contracts
    res = client.get(f"/api/v1/companies/{cid}/reports/warranty-expiry")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3

    # 2. Filter by coverage_status=expiring_soon
    res_soon = client.get(f"/api/v1/companies/{cid}/reports/warranty-expiry?coverage_status=expiring_soon")
    assert res_soon.status_code == 200
    soon_items = res_soon.json()
    assert len(soon_items) == 1
    assert soon_items[0]['reference_number'] == 'REF-SOON'
    assert soon_items[0]['coverage_status'] == 'expiring_soon'
    assert 0 <= soon_items[0]['days_remaining'] <= 30

    # 3. Filter by contract_type=warranty
    res_war = client.get(f"/api/v1/companies/{cid}/reports/warranty-expiry?contract_type=warranty")
    assert res_war.status_code == 200
    assert len(res_war.json()) == 2


def test_maintenance_report(client, db_session):
    company = create_test_company(client, 'REP-MNT')
    cid = company['id']
    cid_uuid = UUID(cid)
    cat = client.get(f"/api/v1/companies/{cid}/categories").json()[0]
    a = client.post(
        f"/api/v1/companies/{cid}/assets",
        json={'category_id': cat['id'], 'model': 'Server Rack'},
    ).json()

    user = create_user_with_role(db_session, cid_uuid, 'ops@mindzen.invalid', 'it_support')
    today = date.today()

    m1 = MaintenanceRequest(
        company_id=cid_uuid,
        asset_id=UUID(a['id']),
        requester_id=user.id,
        title='Cooling fan issue',
        issue_description='Rpm drops',
        priority='high',
        status='in_progress',
        reported_date=today,
    )
    m2 = MaintenanceRequest(
        company_id=cid_uuid,
        asset_id=UUID(a['id']),
        requester_id=user.id,
        title='RAM upgrade',
        issue_description='Add 32GB',
        priority='low',
        status='resolved',
        reported_date=today,
        completed_date=today,
        cost=Decimal('150.00'),
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    # Query report
    res = client.get(f"/api/v1/companies/{cid}/reports/maintenance")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2

    # Filter by priority
    res_prio = client.get(f"/api/v1/companies/{cid}/reports/maintenance?priority=high")
    assert res_prio.status_code == 200
    assert len(res_prio.json()) == 1
    assert res_prio.json()[0]['title'] == 'Cooling fan issue'


def test_procurement_report(client, db_session):
    company = create_test_company(client, 'REP-PROC')
    cid = company['id']
    cid_uuid = UUID(cid)
    cat = client.get(f"/api/v1/companies/{cid}/categories").json()[0]

    sup = Supplier(company_id=cid_uuid, code='SUP-PROC', name='Hardware Direct')
    db_session.add(sup)
    db_session.flush()

    po = PurchaseOrder(
        company_id=cid_uuid,
        supplier_id=sup.id,
        order_number='PO-PROC-101',
        status='partially_received',
        ordered_date=date.today(),
    )
    db_session.add(po)
    db_session.flush()

    pol = PurchaseOrderLine(
        company_id=cid_uuid,
        purchase_order_id=po.id,
        category_id=UUID(cat['id']),
        description='Keyboards',
        quantity_ordered=10,
        unit_cost=Decimal('45.00'),
    )
    db_session.add(pol)
    db_session.flush()

    gr = GoodsReceipt(
        company_id=cid_uuid,
        purchase_order_id=po.id,
        receipt_number='GRN-PROC-101',
        received_date=date.today(),
    )
    db_session.add(gr)
    db_session.flush()

    grl = GoodsReceiptLine(
        company_id=cid_uuid,
        goods_receipt_id=gr.id,
        purchase_order_id=po.id,
        purchase_order_line_id=pol.id,
        quantity_received=6,
        quantity_rejected=1,
    )
    db_session.add(grl)
    db_session.commit()

    res = client.get(f"/api/v1/companies/{cid}/reports/procurement")
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) == 1
    order_data = items[0]
    assert order_data['order_number'] == 'PO-PROC-101'
    assert order_data['supplier_name'] == 'Hardware Direct'
    assert order_data['total_ordered_quantity'] == 10
    assert order_data['total_received_quantity'] == 6
    assert order_data['total_outstanding_quantity'] == 4
    assert order_data['receipt_numbers'] == ['GRN-PROC-101']
    assert len(order_data['lines']) == 1
    assert order_data['lines'][0]['quantity_rejected'] == 1


def test_reports_company_isolation(client, db_session):
    c1 = create_test_company(client, 'ISOL-1')
    c2 = create_test_company(client, 'ISOL-2')

    # Add asset to c1
    cat1 = client.get(f"/api/v1/companies/{c1['id']}/categories").json()[0]
    client.post(
        f"/api/v1/companies/{c1['id']}/assets",
        json={'category_id': cat1['id'], 'model': 'Company 1 Asset'},
    )

    # c2 dashboard must not show c1's asset
    res_c2 = client.get(f"/api/v1/companies/{c2['id']}/dashboard")
    assert res_c2.status_code == 200
    assert res_c2.json()['total_assets'] == 0

    # c2 asset register report must be empty
    res_c2_rep = client.get(f"/api/v1/companies/{c2['id']}/reports/asset-register")
    assert res_c2_rep.status_code == 200
    assert len(res_c2_rep.json()) == 0


def test_reports_auth_and_permission_enforcement(client, db_session):
    company = create_test_company(client, 'REP-SEC')
    cid = company['id']
    cid_uuid = UUID(cid)

    # 404 for non-existent company
    fake_id = '00000000-0000-0000-0000-000000000000'
    res_404 = client.get(f'/api/v1/companies/{fake_id}/dashboard')
    assert res_404.status_code == 404

    # 401 when session cookie is missing
    unauth_client = type(client)(client.app)
    res_401 = unauth_client.get(f'/api/v1/companies/{cid}/dashboard')
    assert res_401.status_code == 401

    # Create a user with a role lacking 'maintenance.read' and 'procurement.read'
    # E.g. let's check a user with a custom or restricted company membership
    # We can create a user who only has company.read or no maintenance/procurement permissions
    user = User(
        email='noprivs@mindzen.invalid',
        password_hash=password_hasher.hash('Test-Password-42!'),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    # Create restricted role without maintenance.read or procurement.read
    restricted_role = Role(scope='company', code='restricted_asset_viewer', name='Restricted Viewer')
    db_session.add(restricted_role)
    db_session.flush()

    # Grant only company.read and asset.read
    from app.models import Permission, role_permissions
    perms = db_session.scalars(select(Permission).where(Permission.code.in_(['company.read', 'asset.read']))).all()
    for p in perms:
        db_session.execute(role_permissions.insert().values(role_id=restricted_role.id, permission_id=p.id))

    db_session.add(CompanyMembership(
        company_id=cid_uuid,
        user_id=user.id,
        role_id=restricted_role.id,
        status='active',
    ))
    db_session.commit()

    # Login as restricted user
    with type(client)(client.app) as restricted_client:
        login = restricted_client.post(
            '/api/v1/auth/login',
            json={'email': 'noprivs@mindzen.invalid', 'password': 'Test-Password-42!'},
        )
        assert login.status_code == 200
        restricted_client.headers['X-CSRF-Token'] = restricted_client.cookies['mindzen_csrf']

        # Cannot access dashboard without dashboard.read -> 403
        dash_res = restricted_client.get(f'/api/v1/companies/{cid}/dashboard')
        assert dash_res.status_code == 403

        # Can access asset register (requires asset.read)
        asset_rep = restricted_client.get(f'/api/v1/companies/{cid}/reports/asset-register')
        assert asset_rep.status_code == 200

        # Cannot access warranty-expiry or maintenance (requires maintenance.read) -> 403
        war_rep = restricted_client.get(f'/api/v1/companies/{cid}/reports/warranty-expiry')
        assert war_rep.status_code == 403

        mnt_rep = restricted_client.get(f'/api/v1/companies/{cid}/reports/maintenance')
        assert mnt_rep.status_code == 403

        # Cannot access procurement report (requires procurement.read) -> 403
        proc_rep = restricted_client.get(f'/api/v1/companies/{cid}/reports/procurement')
        assert proc_rep.status_code == 403


def test_dashboard_access_by_default_roles(client, db_session):
    """Verify that only authorized roles (company_administrator, asset_manager, auditor)

    can access the executive dashboard, while read_only_user and it_support are denied (403).
    """
    from app.models import Company, User, CompanyMembership, Role
    from app.authentication import password_hasher
    import uuid

    company = Company(
        id=uuid.uuid4(),
        code='ROLETEST',
        name='Role Dashboard Access Test',
        is_active=True,
    )
    db_session.add(company)
    db_session.flush()

    role_expectations = {
        'company_administrator': 200,
        'asset_manager': 200,
        'auditor': 200,
        'it_support': 403,
        'read_only_user': 403,
    }

    for role_code, expected_status in role_expectations.items():
        role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == role_code))
        assert role is not None, f'Missing seeded role {role_code}'
        user_email = f'{role_code}_{company.code.lower()}@mindzen.invalid'
        user = User(
            id=uuid.uuid4(),
            email=user_email,
            password_hash=password_hasher.hash('Test-Password-42!'),
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        db_session.add(CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            role_id=role.id,
            status='active',
        ))
        db_session.commit()

        with type(client)(client.app) as user_client:
            login = user_client.post(
                '/api/v1/auth/login',
                json={'email': user_email, 'password': 'Test-Password-42!'},
            )
            assert login.status_code == 200, f'Login failed for {role_code}'
            user_client.headers['X-CSRF-Token'] = user_client.cookies['mindzen_csrf']

            res = user_client.get(f'/api/v1/companies/{company.id}/dashboard')
            assert res.status_code == expected_status, (
                f'Role {role_code} expected HTTP {expected_status} for dashboard, got {res.status_code}'
            )


