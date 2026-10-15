from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app import models
from app.authentication import password_hasher
from app.security import digest


def _company(db_session, code: str) -> models.Company:
    company = models.Company(code=code, name=f'{code} company')
    db_session.add(company)
    db_session.commit()
    return company


def _company_user(db_session, company: models.Company) -> models.User:
    role = db_session.scalar(select(models.Role).where(models.Role.code == 'auditor'))
    user = models.User(
        email='auditor@example.invalid',
        password_hash=password_hasher.hash('Company-Auditor-42!'),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))
    db_session.add(
        models.CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            role_id=role.id,
            status='active',
            assigned_by_id=admin.id,
        )
    )
    db_session.commit()
    return user


def _login_as(client, email: str, password: str) -> None:
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']


def test_protected_routes_require_authentication(client):
    assert client.post('/api/v1/auth/logout').status_code == 204
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.get('/api/v1/companies').status_code == 401
    assert client.get('/api/v1/health').status_code == 200


def test_csrf_and_company_role_permissions_are_enforced(client, db_session):
    company_a = _company(db_session, 'COMP-A')
    company_b = _company(db_session, 'COMP-B')
    _company_user(db_session, company_a)
    _login_as(client, 'auditor@example.invalid', 'Company-Auditor-42!')

    assert client.get(f'/api/v1/companies/{company_a.id}/categories').status_code == 200
    assert client.get(f'/api/v1/companies/{company_b.id}/categories').status_code == 404
    client.headers.pop('X-CSRF-Token')
    csrf_failure = client.post(
        f'/api/v1/companies/{company_a.id}/categories',
        json={'code': 'NEW', 'name': 'New category'},
    )
    assert csrf_failure.status_code == 403
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']
    forbidden_write = client.post(
        f'/api/v1/companies/{company_a.id}/categories',
        json={'code': 'NEW', 'name': 'New category'},
    )
    assert forbidden_write.status_code == 403


def test_membership_revocation_is_enforced_on_the_next_request(client, db_session):
    company = _company(db_session, 'REVOKE')
    _company_user(db_session, company)
    _login_as(client, 'auditor@example.invalid', 'Company-Auditor-42!')
    assert client.get(f'/api/v1/companies/{company.id}/categories').status_code == 200

    membership = db_session.scalar(
        select(models.CompanyMembership).where(models.CompanyMembership.company_id == company.id)
    )
    membership.status = 'revoked'
    db_session.commit()
    assert client.get(f'/api/v1/companies/{company.id}/categories').status_code == 404


def test_inactive_users_and_revoked_sessions_cannot_authenticate(client, db_session):
    inactive = models.User(
        email='inactive@example.invalid',
        password_hash=password_hasher.hash('Inactive-Account-42!'),
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()
    assert client.post(
        '/api/v1/auth/login',
        json={'email': inactive.email, 'password': 'Inactive-Account-42!'},
    ).status_code == 401

    session_token = client.cookies['mindzen_session']
    auth_session = db_session.get(models.AuthSession, digest(session_token))
    auth_session.revoked_at = datetime.now(timezone.utc)
    db_session.commit()
    assert client.get('/api/v1/auth/me').status_code == 401


def test_invitation_acceptance_creates_an_audited_membership(client, db_session):
    company = _company(db_session, 'INVITE')
    invitation = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'new.user@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invitation.status_code == 201
    token = invitation.json()['token']
    assert client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'New-User-Password-42!'},
    ).status_code == 200

    _login_as(client, 'new.user@example.invalid', 'New-User-Password-42!')
    current_user = client.get('/api/v1/auth/me')
    assert current_user.status_code == 200
    assert current_user.json()['memberships'][0]['company_id'] == str(company.id)

    events = db_session.scalars(
        select(models.AuditEvent).where(models.AuditEvent.action == 'auth.invitation.accept')
    ).all()
    assert events
    assert all(token not in str(event.changes) for event in events)


def test_invitation_membership_can_be_revoked_and_token_cannot_be_accepted(client, db_session):
    company = _company(db_session, 'REVOKE-INVITE')
    path = f'/api/v1/security/companies/{company.id}/invitations'
    created = client.post(
        path,
        json={'email': 'revoked.invite@example.invalid', 'role_code': 'read_only_user'},
    )
    assert created.status_code == 201
    token = created.json()['token']
    members = client.get(f'/api/v1/security/companies/{company.id}/members')
    assert members.status_code == 200
    assert token not in members.text
    pending = next(member for member in members.json() if member['email'] == 'revoked.invite@example.invalid')

    revoked = client.patch(
        f'/api/v1/security/companies/{company.id}/members/{pending["membership_id"]}',
        json={'status': 'revoked'},
    )
    assert revoked.status_code == 200
    assert revoked.json()['status'] == 'revoked'
    assert client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Revoked-Invite-Password-42!'},
    ).status_code == 400

    invitation_row = db_session.scalar(
        select(models.UserInvitation).where(
            models.UserInvitation.membership_id == UUID(pending['membership_id'])
        )
    )
    assert invitation_row.revoked_at is not None


def test_company_user_cannot_invite_or_read_another_company(client, db_session):
    company_a = _company(db_session, 'INVITE-A')
    company_b = _company(db_session, 'INVITE-B')
    _company_user(db_session, company_a)
    _login_as(client, 'auditor@example.invalid', 'Company-Auditor-42!')

    payload = {'email': 'unauthorized.invite@example.invalid', 'role_code': 'read_only_user'}
    assert client.post(f'/api/v1/security/companies/{company_a.id}/invitations', json=payload).status_code == 403
    assert client.get(f'/api/v1/security/companies/{company_b.id}/members').status_code == 404
    assert client.post(f'/api/v1/security/companies/{company_b.id}/invitations', json=payload).status_code == 404


def test_reissuing_invitation_invalidates_the_previous_token(client, db_session):
    company = _company(db_session, 'REISSUE')
    path = f'/api/v1/security/companies/{company.id}/invitations'
    first = client.post(path, json={'email': 'reissued@example.invalid', 'role_code': 'read_only_user'})
    second = client.post(path, json={'email': 'reissued@example.invalid', 'role_code': 'auditor'})
    assert first.status_code == second.status_code == 201
    assert first.json()['token'] != second.json()['token']
    assert client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': first.json()['token'], 'password': 'Reissued-User-42!'},
    ).status_code == 400
    assert client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': second.json()['token'], 'password': 'Reissued-User-42!'},
    ).status_code == 200


def test_audit_events_reject_orm_mutation(db_session):
    audit_event = models.AuditEvent(action='test', entity_type='Test', outcome='success')
    db_session.add(audit_event)
    db_session.commit()
    audit_event.outcome = 'changed'
    try:
        db_session.commit()
    except ValueError as exc:
        assert str(exc) == 'Audit events are append-only'
        db_session.rollback()
    else:
        raise AssertionError('Audit event mutation unexpectedly committed')

    saved = db_session.get(models.AuditEvent, audit_event.id)
    assert saved.outcome == 'success'


def test_audit_write_failure_rolls_back_the_business_change(db_session):
    company = _company(db_session, 'ATOMIC')
    duplicate_id = uuid4()
    db_session.add(
        models.AuditEvent(
            id=duplicate_id,
            action='existing',
            entity_type='Test',
            outcome='success',
        )
    )
    db_session.commit()

    company.name = 'Mutation must roll back'
    db_session.add(
        models.AuditEvent(
            id=duplicate_id,
            action='duplicate',
            entity_type='Test',
            outcome='success',
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.refresh(company)
    assert company.name == 'ATOMIC company'
