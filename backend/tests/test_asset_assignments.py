from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.routes import assets as asset_routes
from app.authentication import password_hasher
from app.models import (
    AssetAssignment,
    AuditEvent,
    CompanyMembership,
    Role,
    User,
)


def company_and_asset(client, code: str, status: str = 'in_stock'):
    company = client.post(
        '/api/v1/companies',
        json={'code': code, 'name': f'{code} Ltd', 'number_prefix': code},
    ).json()
    category = client.get(f"/api/v1/companies/{company['id']}/categories").json()[0]
    asset = client.post(
        f"/api/v1/companies/{company['id']}/assets",
        json={'category_id': category['id'], 'status': status},
    )
    assert asset.status_code == 201, asset.text
    return company, asset.json()


def add_member(db_session, company_id, email: str, role_code: str = 'read_only_user') -> User:
    company_id = UUID(str(company_id))
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
            company_id=company_id,
            user_id=user.id,
            role_id=role.id,
            status='active',
        )
    )
    db_session.commit()
    return user


def test_assignment_handover_transfer_return_history_and_audit(client, db_session):
    company, asset = company_and_asset(client, 'ASG1')
    first = add_member(db_session, company['id'], 'first-recipient@example.invalid')
    second = add_member(db_session, company['id'], 'second-recipient@example.invalid')
    department = client.post(
        f"/api/v1/companies/{company['id']}/departments",
        json={'code': 'OPS', 'name': 'Operations'},
    ).json()
    site = client.post(
        f"/api/v1/companies/{company['id']}/sites",
        json={'code': 'HQ', 'name': 'Head Office'},
    ).json()
    location = client.post(
        f"/api/v1/companies/{company['id']}/sites/{site['id']}/locations",
        json={'code': 'R1', 'name': 'Room 1'},
    ).json()
    asset_url = f"/api/v1/companies/{company['id']}/assets/{asset['id']}"

    assignment_response = client.post(
        f'{asset_url}/assignments',
        json={
            'recipient_id': str(first.id),
            'effective_date': '2026-10-15',
            'responsible_department_id': department['id'],
            'location_id': location['id'],
            'reference': 'REQ-100',
        },
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assignment = assignment_response.json()
    assert assignment['recipient_email'] == first.email
    assert assignment['status'] == 'active'
    assert client.get(asset_url).json()['status'] == 'assigned'

    duplicate = client.post(
        f'{asset_url}/assignments',
        json={'recipient_id': str(second.id), 'effective_date': '2026-10-15'},
    )
    assert duplicate.status_code == 409

    handover = client.post(
        f"{asset_url}/assignments/{assignment['id']}/handover",
        json={
            'handover_date': '2026-10-15',
            'condition': 'good',
            'included_items': 'Laptop, charger, bag',
            'acknowledgement': 'Received in good order',
            'notes': 'Standard issue',
        },
    )
    assert handover.status_code == 200, handover.text
    assert handover.json()['handover_condition'] == 'good'
    assert client.post(
        f"{asset_url}/assignments/{assignment['id']}/handover",
        json={'handover_date': '2026-10-15'},
    ).status_code == 409

    transfer = client.post(
        f"{asset_url}/assignments/{assignment['id']}/transfer",
        json={
            'recipient_id': str(second.id),
            'effective_date': '2026-10-16',
            'reason': 'Team change',
            'responsible_department_id': department['id'],
            'location_id': location['id'],
            'acknowledgement': 'Received from previous custodian',
        },
    )
    assert transfer.status_code == 201, transfer.text
    new_assignment = transfer.json()
    assert new_assignment['recipient_id'] == str(second.id)
    assert new_assignment['previous_assignment_id'] == assignment['id']
    assert new_assignment['handover_date'] == '2026-10-16'
    assert client.get(f"{asset_url}/assignments").json()[1]['status'] == 'transferred'

    returned = client.post(
        f"{asset_url}/assignments/{new_assignment['id']}/return",
        json={
            'return_date': '2026-10-17',
            'condition': 'fair',
            'notes': 'Returned to stores',
            'issue_details': 'Minor screen mark',
            'next_asset_status': 'maintenance',
        },
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()['status'] == 'returned'
    assert client.get(asset_url).json()['status'] == 'maintenance'
    assert client.get(asset_url).json()['custodian_name'] is None
    assert client.post(
        f"{asset_url}/assignments/{new_assignment['id']}/return",
        json={'return_date': '2026-10-17', 'next_asset_status': 'in_stock'},
    ).status_code == 409

    history = client.get(f'{asset_url}/assignments')
    assert history.status_code == 200
    assert {item['status'] for item in history.json()} == {'transferred', 'returned'}
    events = client.get(f'{asset_url}/history').json()
    assert {item['event_type'] for item in events} >= {
        'assignment_created',
        'assignment_handover',
        'assignment_transferred',
        'assignment_returned',
    }
    audit_actions = set(
        db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.entity_type == 'AssetAssignment',
                AuditEvent.company_id == UUID(company['id']),
            )
        ).all()
    )
    assert {
        'asset.assignment.created',
        'asset.assignment.handover',
        'asset.assignment.transferred',
        'asset.assignment.returned',
    } <= audit_actions


def test_assignment_rejects_ineligible_asset_and_cross_company_recipient(client, db_session):
    company, asset = company_and_asset(client, 'ASG2', status='maintenance')
    other_company, _ = company_and_asset(client, 'ASG3')
    outside_recipient = add_member(db_session, other_company['id'], 'outside@example.invalid')
    response = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/assignments",
        json={'recipient_id': str(outside_recipient.id), 'effective_date': '2026-10-15'},
    )
    assert response.status_code == 409

    stock_company, stock_asset = company_and_asset(client, 'ASG4')
    outside_recipient = add_member(db_session, other_company['id'], 'outside-2@example.invalid')
    response = client.post(
        f"/api/v1/companies/{stock_company['id']}/assets/{stock_asset['id']}/assignments",
        json={'recipient_id': str(outside_recipient.id), 'effective_date': '2026-10-15'},
    )
    assert response.status_code == 422


def test_assignment_requires_permission_and_company_scope(client, db_session):
    company, asset = company_and_asset(client, 'ASG5')
    read_only = add_member(db_session, company['id'], 'reader@example.invalid')
    login = client.post(
        '/api/v1/auth/login',
        json={'email': read_only.email, 'password': 'Correct-Horse-42!'},
    )
    assert login.status_code == 200, login.text
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']
    denied = client.post(
        f"/api/v1/companies/{company['id']}/assets/{asset['id']}/assignments",
        json={'recipient_id': str(read_only.id), 'effective_date': '2026-10-15'},
    )
    assert denied.status_code == 403


def test_database_prevents_duplicate_active_assignment(client, db_session):
    company, asset = company_and_asset(client, 'ASG6')
    recipient = add_member(db_session, company['id'], 'unique-recipient@example.invalid')
    asset_id = asset['id']
    assignment = AssetAssignment(
        id=uuid4(),
        company_id=UUID(company['id']),
        asset_id=UUID(asset_id),
        recipient_id=recipient.id,
        effective_date=date(2026, 10, 15),
        status='active',
    )
    db_session.add(assignment)
    db_session.commit()
    duplicate = AssetAssignment(
        id=uuid4(),
        company_id=UUID(company['id']),
        asset_id=UUID(asset_id),
        recipient_id=recipient.id,
        effective_date=date(2026, 10, 15),
        status='active',
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_assignment_and_lifecycle_mutations_reject_invalid_transitions(client, db_session):
    company, asset = company_and_asset(client, 'ASG7')
    recipient = add_member(db_session, company['id'], 'transition-recipient@example.invalid')
    url = f"/api/v1/companies/{company['id']}/assets/{asset['id']}"
    assignment = client.post(
        f'{url}/assignments',
        json={'recipient_id': str(recipient.id), 'effective_date': '2026-10-15'},
    ).json()
    assert client.patch(url, json={'status': 'in_stock'}).status_code == 409
    assert client.patch(url, json={'custodian_name': 'Unrelated custodian'}).status_code == 409
    assert client.post(
        f"{url}/assignments/{assignment['id']}/return",
        json={'return_date': '2026-10-14', 'next_asset_status': 'in_stock'},
    ).status_code == 422
    assert client.post(
        f"{url}/assignments/{assignment['id']}/transfer",
        json={
            'recipient_id': str(recipient.id),
            'effective_date': '2026-10-14',
            'reason': 'Invalid earlier date',
        },
    ).status_code == 422


def test_assignment_and_audit_are_rolled_back_together(client, db_session, monkeypatch):
    company, asset = company_and_asset(client, 'ASG8')
    recipient = add_member(db_session, company['id'], 'atomic-recipient@example.invalid')
    duplicate_event_id = uuid4()
    db_session.add(
        AuditEvent(
            id=duplicate_event_id,
            action='existing',
            entity_type='Test',
            outcome='success',
        )
    )
    db_session.commit()

    def conflicting_audit(db, **_kwargs):
        db.add(
            AuditEvent(
                id=duplicate_event_id,
                action='conflict',
                entity_type='AssetAssignment',
                outcome='success',
            )
        )

    monkeypatch.setattr(asset_routes, 'record_security_event', conflicting_audit)
    asset_url = f"/api/v1/companies/{company['id']}/assets/{asset['id']}"
    response = client.post(
        f'{asset_url}/assignments',
        json={'recipient_id': str(recipient.id), 'effective_date': '2026-10-15'},
    )
    assert response.status_code == 409
    assert client.get(asset_url).json()['status'] == 'in_stock'
    assert client.get(f'{asset_url}/assignments').json() == []
