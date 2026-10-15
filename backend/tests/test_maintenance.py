from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select

from app.authentication import password_hasher
from app.models import AssetServiceContract, AuditEvent, CompanyMembership, MaintenanceRequest, Role, Supplier, User


def company_asset(client, code: str, vendor_reference: str | None = None):
    company = client.post(
        '/api/v1/companies',
        json={'code': code, 'name': f'{code} Ltd', 'number_prefix': code},
    ).json()
    category = client.get(f"/api/v1/companies/{company['id']}/categories").json()[0]
    response = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': category['id'], 'vendor_reference': vendor_reference},
    )
    assert response.status_code == 201, response.text
    return company, response.json()


def add_company_member(db_session, company_id: str, email: str, role_code: str = 'it_support') -> User:
    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == role_code))
    user = User(
        email=email,
        password_hash=password_hasher.hash('Correct-Horse-42!'),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        CompanyMembership(
            company_id=UUID(company_id),
            user_id=user.id,
            role_id=role.id,
            status='active',
        )
    )
    db_session.commit()
    return user


def test_service_contracts_auto_link_supplier_and_calculate_date_status(client, db_session):
    company, asset = company_asset(client, 'MNT1', 'SUP-WARRANTY')
    supplier_response = client.post(
        f"/api/v1/companies/{company['id']}/suppliers",
        json={'code': 'SUP-WARRANTY', 'name': 'Warranty Provider'},
    )
    assert supplier_response.status_code == 201, supplier_response.text
    supplier = supplier_response.json()
    today = date.today()

    def create_contract(reference: str, start: date, end: date):
        return client.post(
            f"/api/v1/companies/{company['id']}/assets/{asset['id']}/service-contracts",
            json={
                'contract_type': 'warranty',
                'reference_number': reference,
                'start_date': start.isoformat(),
                'end_date': end.isoformat(),
                'coverage_description': 'Parts and labour',
            },
        )

    active = create_contract('WR-1', today - timedelta(days=60), today + timedelta(days=90))
    soon = create_contract('WR-2', today - timedelta(days=60), today + timedelta(days=20))
    upcoming = create_contract('WR-3', today + timedelta(days=5), today + timedelta(days=100))
    expired = create_contract('WR-4', today - timedelta(days=100), today - timedelta(days=1))
    threshold = create_contract('WR-5', today - timedelta(days=30), today + timedelta(days=30))
    threshold_plus_one = create_contract('WR-6', today - timedelta(days=30), today + timedelta(days=31))
    last_coverage_day = create_contract('WR-7', today, today)
    for response in (active, soon, upcoming, expired, threshold, threshold_plus_one, last_coverage_day):
        assert response.status_code == 201, response.text
    assert active.json()['supplier_id'] == supplier['id']
    assert active.json()['provider_name'] == 'Warranty Provider'
    assert active.json()['coverage_status'] == 'active'
    assert soon.json()['coverage_status'] == 'expiring_soon'
    assert upcoming.json()['coverage_status'] == 'upcoming'
    assert expired.json()['coverage_status'] == 'expired'
    assert threshold.json()['coverage_status'] == 'expiring_soon'
    assert threshold_plus_one.json()['coverage_status'] == 'active'
    assert last_coverage_day.json()['coverage_status'] == 'expiring_soon'
    foreign_company, _ = company_asset(client, 'MNT1B')
    foreign_supplier = client.post(
        f"/api/v1/companies/{foreign_company['id']}/suppliers",
        json={'code': 'SUP-FOREIGN', 'name': 'Foreign provider'},
    ).json()
    cross_company_supplier = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/service-contracts",
        json={
            'contract_type': 'amc',
            'supplier_id': foreign_supplier['id'],
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=10)).isoformat(),
        },
    )
    assert cross_company_supplier.status_code == 422
    assert client.get(
        f"/api/v1/companies/{foreign_company['id']}/assets/{asset['id']}/service-contracts"
    ).status_code == 404

    cancelled = client.patch(
        f"/api/v1/companies/{company['id']}/service-contracts/{upcoming.json()['id']}/cancel",
        json={},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['coverage_status'] == 'cancelled'
    assert len(client.get(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/service-contracts"
    ).json()) == 7

    invalid = create_contract('WR-INVALID', today, today - timedelta(days=1))
    assert invalid.status_code == 422
    assert client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/service-contracts",
        json={
            'contract_type': 'amc',
            'reference_number': 'WR-1',
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=5)).isoformat(),
        },
    ).status_code == 409

    db_session.expire_all()
    assert db_session.scalar(
        select(AssetServiceContract.id).where(
            AssetServiceContract.company_id == UUID(company['id']),
            AssetServiceContract.reference_number == 'WR-1',
        )
    ) is not None
    cancellation_audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(company['id']),
            AuditEvent.entity_type == 'AssetServiceContract',
            AuditEvent.entity_id == cancelled.json()['id'],
            AuditEvent.action == 'service_contract_cancelled',
        )
    )
    assert cancellation_audit is not None
    stored = db_session.scalar(
        select(AssetServiceContract).where(AssetServiceContract.reference_number == 'WR-1')
    )
    assert stored.supplier_id == UUID(supplier['id'])
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(company['id']),
            AuditEvent.entity_type == 'AssetServiceContract',
            AuditEvent.action == 'service_contract_created',
            AuditEvent.entity_id == str(stored.id),
        )
    )
    assert audit is not None
    assert audit.changes['contract_type'] == 'warranty'


def test_maintenance_request_lifecycle_assignment_isolation_and_audit(client, db_session):
    company, asset = company_asset(client, 'MNT2')
    other_company, other_asset = company_asset(client, 'MNT3')
    support_user = add_company_member(db_session, company['id'], 'support-mnt@example.invalid')
    other_support = add_company_member(db_session, other_company['id'], 'support-other@example.invalid')
    base_url = f"/api/v1/companies/{company['id']}"

    cross_company_asset = client.post(
        f'{base_url}/maintenance-requests',
        json={
            'asset_id': other_asset['id'],
            'title': 'Cross-company request',
            'issue_description': 'Must be rejected',
            'reported_date': date.today().isoformat(),
        },
    )
    assert cross_company_asset.status_code == 404

    cross_company_assignee = client.post(
        f'{base_url}/maintenance-requests',
        json={
            'asset_id': asset['id'],
            'title': 'Invalid assignee',
            'issue_description': 'Assignee belongs to another company',
            'reported_date': date.today().isoformat(),
            'assignee_id': str(other_support.id),
        },
    )
    assert cross_company_assignee.status_code == 422

    created = client.post(
        f'{base_url}/maintenance-requests',
        json={
            'asset_id': asset['id'],
            'title': 'Laptop will not start',
            'issue_description': 'Power light flashes and the laptop shuts down.',
            'priority': 'high',
            'reported_date': date.today().isoformat(),
            'assignee_id': str(support_user.id),
        },
    )
    assert created.status_code == 201, created.text
    request = created.json()
    assert request['status'] == 'open'
    assert request['requester_email'] == 'test-admin@example.invalid'
    assert request['assignee_email'] == support_user.email

    invalid_jump = client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={'status': 'resolved', 'completed_date': date.today().isoformat(), 'resolution_notes': 'Fixed'},
    )
    assert invalid_jump.status_code == 422
    in_progress = client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={'status': 'in_progress', 'diagnosis': 'Battery fault'},
    )
    assert in_progress.status_code == 200, in_progress.text
    missing_resolution = client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={'status': 'resolved', 'completed_date': date.today().isoformat()},
    )
    assert missing_resolution.status_code == 422
    resolved = client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={
            'status': 'resolved',
            'completed_date': date.today().isoformat(),
            'work_performed': 'Replaced the battery',
            'resolution_notes': 'Boot and power test passed.',
            'cost': '85.50',
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['status'] == 'resolved'
    assert resolved.json()['cost'] == '85.50'
    closed = client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={'status': 'closed'},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()['status'] == 'closed'
    assert client.patch(
        f"{base_url}/maintenance-requests/{request['id']}",
        json={'status': 'in_progress'},
    ).status_code == 409

    history = client.get(f'{base_url}/maintenance-requests', params={'asset_id': asset['id']})
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]['resolution_notes'] == 'Boot and power test passed.'
    db_session.expire_all()
    persisted = db_session.get(MaintenanceRequest, UUID(request['id']))
    assert persisted.status == 'closed'
    assert persisted.completed_date == date.today()
    events = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(company['id']),
            AuditEvent.entity_type == 'MaintenanceRequest',
            AuditEvent.entity_id == str(persisted.id),
            AuditEvent.action.in_(['maintenance_request_created', 'maintenance_request_updated']),
        )
    ).all()
    assert len(events) == 4
    assert {event.action for event in events} == {
        'maintenance_request_created',
        'maintenance_request_updated',
    }


def test_maintenance_read_only_role_cannot_create_request(client, db_session):
    company, asset = company_asset(client, 'MNT4')
    add_company_member(db_session, company['id'], 'maintenance-auditor@example.invalid', 'auditor')
    client.post('/api/v1/auth/logout')
    login = client.post(
        '/api/v1/auth/login',
        json={'email': 'maintenance-auditor@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    assert login.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']
    url = f"/api/v1/companies/{company['id']}"
    assert client.get(f'{url}/maintenance-requests').status_code == 200
    response = client.post(
        f'{url}/maintenance-requests',
        json={
            'asset_id': asset['id'],
            'title': 'Not allowed',
            'issue_description': 'Read-only users cannot create requests',
            'reported_date': date.today().isoformat(),
        },
    )
    assert response.status_code == 403
    assert client.get(
        f"{url}/assets/{asset['id']}/service-contracts"
    ).status_code == 200
