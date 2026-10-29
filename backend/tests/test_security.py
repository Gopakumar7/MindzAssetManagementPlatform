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


def test_system_admin_can_invite_any_company_role(client, db_session):
    company = _company(db_session, 'SYSADMIN-INVITE')
    path = f'/api/v1/security/companies/{company.id}/invitations'
    res = client.post(path, json={'email': 'sysadmin.invited@example.invalid', 'role_code': 'company_administrator'})
    assert res.status_code == 201
    assert res.json()['email'] == 'sysadmin.invited@example.invalid'
    assert res.json()['token'] is not None


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


def test_origin_validation_semantics():
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.api.v1.routes.auth import _validate_origin

    def build_request(headers: dict[str, str]) -> Request:
        raw_headers = [(k.lower().encode('latin-1'), v.encode('latin-1')) for k, v in headers.items()]
        scope = {'type': 'http', 'headers': raw_headers, 'method': 'POST'}
        return Request(scope)

    # 1. Request without an Origin header preserves existing behaviour (accepted)
    req_no_origin = build_request({})
    _validate_origin(req_no_origin)

    # 2. An explicitly configured origin is accepted
    req_configured = build_request({'origin': 'http://localhost:4200'})
    _validate_origin(req_configured)

    # 3. Same-origin request using EC2 public IP without hardcoding IP (via forwarded headers)
    ec2_ip_port = '198.51.100.42:4200'
    req_ec2_same_origin = build_request({
        'origin': f'http://{ec2_ip_port}',
        'x-forwarded-host': ec2_ip_port,
        'x-forwarded-proto': 'http',
    })
    _validate_origin(req_ec2_same_origin)

    # HTTPS EC2 / custom domain same-origin test
    req_https_same_origin = build_request({
        'origin': 'https://ec2-demo.example.com',
        'x-forwarded-host': 'ec2-demo.example.com',
        'x-forwarded-proto': 'https',
    })
    _validate_origin(req_https_same_origin)

    # Standard Nginx $host forwarding (e.g. EC2 public IP without port)
    req_nginx_host_same_origin = build_request({
        'origin': 'http://198.51.100.42',
        'x-forwarded-host': '198.51.100.42',
        'x-forwarded-proto': 'http',
    })
    _validate_origin(req_nginx_host_same_origin)

    # Multi-proxy comma-separated X-Forwarded-Host / X-Forwarded-Proto
    req_multi_proxy = build_request({
        'origin': 'https://demo.example.com',
        'x-forwarded-host': 'demo.example.com, internal-proxy.local',
        'x-forwarded-proto': 'https, http',
    })
    _validate_origin(req_multi_proxy)

    # Case-insensitive host matching and trailing slash
    req_case_insensitive = build_request({
        'origin': 'https://DEMO.EXAMPLE.COM/',
        'x-forwarded-host': 'demo.example.com',
        'x-forwarded-proto': 'https',
    })
    _validate_origin(req_case_insensitive)

    # 4. Genuinely different origin is rejected with HTTP 403
    req_untrusted = build_request({'origin': 'https://evil.attacker.example.invalid'})
    with pytest.raises(HTTPException) as exc_info:
        _validate_origin(req_untrusted)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == 'Request origin is not allowed'

    # 5. Genuinely different origin even if x-forwarded headers are present
    req_mismatched = build_request({
        'origin': 'https://evil.attacker.example.invalid',
        'x-forwarded-host': '198.51.100.42:4200',
        'x-forwarded-proto': 'http',
    })
    with pytest.raises(HTTPException) as exc_info:
        _validate_origin(req_mismatched)
    assert exc_info.value.status_code == 403


def test_login_origin_validation_endpoint(client):
    # 1. Explicitly configured origin -> 200
    res_allowed = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={'Origin': 'http://localhost:4200'},
    )
    assert res_allowed.status_code == 200

    # 2. EC2 public IP same-origin forwarded by Nginx ($host without port) -> 200
    res_nginx_host = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={
            'Origin': 'http://198.51.100.42',
            'X-Forwarded-Host': '198.51.100.42',
            'X-Forwarded-Proto': 'http',
        },
    )
    assert res_nginx_host.status_code == 200

    # 3. HTTPS custom domain forwarded by Nginx -> 200
    res_nginx_domain = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={
            'Origin': 'https://demo.example.com',
            'X-Forwarded-Host': 'demo.example.com',
            'X-Forwarded-Proto': 'https',
        },
    )
    assert res_nginx_domain.status_code == 200

    # 4. EC2 public IP same-origin forwarded with port -> 200
    res_ec2 = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={
            'Origin': 'http://198.51.100.42:4200',
            'X-Forwarded-Host': '198.51.100.42:4200',
            'X-Forwarded-Proto': 'http',
        },
    )
    assert res_ec2.status_code == 200

    # 3. Untrusted origin -> 403
    res_forbidden = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={'Origin': 'https://attacker.example.invalid'},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.json()['detail'] == 'Request origin is not allowed'

    # 4. No Origin header -> 200
    res_no_origin = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    assert res_no_origin.status_code == 200


def test_invitation_acceptance_origin_validation_endpoint(client, db_session):
    company = _company(db_session, 'INV-ORIGIN')
    invitation = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'origin.accept@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invitation.status_code == 201
    token = invitation.json()['token']

    # 1. Untrusted origin -> 403
    res_forbidden = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Origin-User-42!'},
        headers={'Origin': 'https://attacker.example.invalid'},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.json()['detail'] == 'Request origin is not allowed'

    # 2. Same-origin forwarded by Nginx ($host) -> 200
    res_same_origin = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Origin-User-42!'},
        headers={
            'Origin': 'http://198.51.100.42',
            'X-Forwarded-Host': '198.51.100.42',
            'X-Forwarded-Proto': 'http',
        },
    )
    assert res_same_origin.status_code == 200
    assert res_same_origin.json()['status'] == 'invitation_accepted'


def test_logout_origin_validation_endpoint(client, db_session):
    login_res = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
        headers={
            'Origin': 'http://198.51.100.42',
            'X-Forwarded-Host': '198.51.100.42',
            'X-Forwarded-Proto': 'http',
        },
    )
    assert login_res.status_code == 200

    csrf_cookie = client.cookies.get('mindzen_csrf')
    headers_base = {'X-CSRF-Token': csrf_cookie} if csrf_cookie else {}

    # 1. Untrusted origin -> 403
    res_forbidden = client.post(
        '/api/v1/auth/logout',
        headers={**headers_base, 'Origin': 'https://attacker.example.invalid'},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.json()['detail'] == 'Request origin is not allowed'

    # 2. Same-origin forwarded by Nginx ($host) -> 204
    res_same_origin = client.post(
        '/api/v1/auth/logout',
        headers={
            **headers_base,
            'Origin': 'http://198.51.100.42',
            'X-Forwarded-Host': '198.51.100.42',
            'X-Forwarded-Proto': 'http',
        },
    )
    assert res_same_origin.status_code == 204


def test_nginx_configuration_forwarded_host_headers():
    import re
    from pathlib import Path

    nginx_conf_path = Path(__file__).resolve().parents[2] / 'frontend' / 'nginx.conf'
    if not nginx_conf_path.exists():
        pytest.skip(f'nginx.conf not found at {nginx_conf_path} (skipped inside container environment)')
    content = nginx_conf_path.read_text(encoding='utf-8')

    api_exact = re.search(r'location\s*=\s*/api/v1\s*\{(.*?)\}', content, re.DOTALL)
    api_prefix = re.search(r'location\s*\^~\s*/api/v1/\s*\{(.*?)\}', content, re.DOTALL)

    assert api_exact is not None, 'location = /api/v1 not found in nginx.conf'
    assert api_prefix is not None, 'location ^~ /api/v1/ not found in nginx.conf'

    for block in [api_exact.group(1), api_prefix.group(1)]:
        assert 'proxy_set_header Host $host;' in block
        assert 'proxy_set_header X-Forwarded-Host $host;' in block
        assert 'proxy_set_header X-Forwarded-Proto $scheme;' in block
        assert '$http_host' not in block


SECURE_PROD_DB = 'postgresql+psycopg://mindzen_prod:S3cur3Pr0dP@ssw0rd!@db.internal:5432/mindzen'


@pytest.mark.parametrize(
    ('app_env', 'cookie_secure_setting', 'expected'),
    [
        ('production', None, True),
        ('production', True, True),
        ('development', None, False),
        ('test', None, False),
        ('dev', None, False),
        ('development', True, True),
        ('development', False, False),
        ('staging', None, True),
    ],
)
def test_cookie_secure_configuration_matrix(app_env, cookie_secure_setting, expected):
    from app.core.config import Settings
    extra = {'DATABASE_URL': SECURE_PROD_DB} if app_env in {'production', 'staging'} else {}
    s = Settings(
        APP_ENV=app_env,
        COOKIE_SECURE=cookie_secure_setting,
        _env_file=None,
        **extra,
    )
    assert s.cookie_secure is expected


def test_production_configuration_safeguards():
    from app.core.config import Settings
    import pytest

    # 1. Production fails when default/weak DB password is used
    with pytest.raises(ValueError, match='Insecure default database password'):
        Settings(
            APP_ENV='production',
            DATABASE_URL='postgresql+psycopg://mindzen:change_me@localhost:5432/mindzen',
            _env_file=None,
        )

    # 2. Production fails when COOKIE_SECURE is explicitly set to false
    with pytest.raises(ValueError, match='COOKIE_SECURE cannot be disabled'):
        Settings(
            APP_ENV='production',
            DATABASE_URL=SECURE_PROD_DB,
            COOKIE_SECURE=False,
            _env_file=None,
        )

    # 3. Production fails when wildcard CORS is configured
    with pytest.raises(ValueError, match='Wildcard'):
        Settings(
            APP_ENV='production',
            DATABASE_URL=SECURE_PROD_DB,
            CORS_ORIGINS='*',
            _env_file=None,
        )

    # 4. Valid production settings succeed
    prod_settings = Settings(
        APP_ENV='production',
        DATABASE_URL=SECURE_PROD_DB,
        COOKIE_SECURE=True,
        _env_file=None,
    )
    assert prod_settings.cookie_secure is True

    # 5. Case-insensitivity and whitespace normalization in APP_ENV activate safeguards
    for prod_variant in ['production', 'PROD', ' production ', '  Prod  ', 'prod']:
        with pytest.raises(ValueError, match='Insecure default database password'):
            Settings(
                APP_ENV=prod_variant,
                DATABASE_URL='postgresql+psycopg://mindzen:change_me@localhost:5432/mindzen',
                _env_file=None,
            )

    # 6. Local development normalization allows development defaults
    for dev_variant in ['development', '  development  ', 'DEV', 'dev', 'test']:
        dev_settings = Settings(
            APP_ENV=dev_variant,
            _env_file=None,
        )
        assert dev_settings.cookie_secure is False


@pytest.mark.parametrize(
    ('env_vars', 'expected'),
    [
        ({'APP_ENV': 'production', 'DATABASE_URL': SECURE_PROD_DB}, True),
        ({'APP_ENV': 'production', 'DATABASE_URL': SECURE_PROD_DB, 'COOKIE_SECURE': 'true'}, True),
        ({'APP_ENV': 'development'}, False),
        ({'APP_ENV': 'test'}, False),
    ],
)
def test_cookie_secure_from_environment_variables(monkeypatch, env_vars, expected):
    from app.core.config import Settings

    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('COOKIE_SECURE', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)

    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)

    s = Settings(_env_file=None)
    assert s.cookie_secure is expected


def test_login_cookie_secure_flag_behavior(client, monkeypatch):
    from app.core.config import settings

    # Insecure mode (e.g. HTTP EC2 demo): cookies do NOT have Secure flag
    monkeypatch.setattr(settings, 'cookie_secure_setting', False)
    res_insecure = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    assert res_insecure.status_code == 200
    set_cookie_headers = res_insecure.headers.get_list('set-cookie')
    assert any('mindzen_session=' in h and '; secure' not in h.lower() for h in set_cookie_headers)

    # Secure mode (e.g. HTTPS production): cookies have Secure flag
    monkeypatch.setattr(settings, 'cookie_secure_setting', True)
    res_secure = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    assert res_secure.status_code == 200
    set_cookie_headers = res_secure.headers.get_list('set-cookie')
    assert any('mindzen_session=' in h and '; secure' in h.lower() for h in set_cookie_headers)



# ==============================================================================
# RBAC Scope Validation & Security Safeguards
# ==============================================================================


def test_role_permission_scope_validation_rejects_system_permissions_on_company_role(client):
    """Verify that assigning system-scoped permissions to a company role returns HTTP 422."""
    # Attempt assigning system.rbac.manage to company_administrator
    res = client.put(
        '/api/v1/security/roles/company_administrator/permissions',
        json={'permissions': ['asset.read', 'system.rbac.manage']},
    )
    assert res.status_code == 422
    assert "Cannot assign system-scoped permission(s) to company-scoped role 'company_administrator'" in res.json()['detail']

    # Attempt assigning company.create to read_only_user
    res_company_create = client.put(
        '/api/v1/security/roles/read_only_user/permissions',
        json={'permissions': ['asset.read', 'company.create']},
    )
    assert res_company_create.status_code == 422
    assert "Cannot assign system-scoped permission(s) to company-scoped role 'read_only_user'" in res_company_create.json()['detail']


def test_role_permission_scope_validation_allows_valid_company_permissions(client):
    """Verify that updating valid company-scoped permissions on a company role succeeds."""
    valid_perms = ['asset.read', 'organization.read', 'company.read']
    res = client.put(
        '/api/v1/security/roles/read_only_user/permissions',
        json={'permissions': valid_perms},
    )
    assert res.status_code == 200
    assert sorted(res.json()['permissions']) == sorted(valid_perms)


def test_system_administrator_role_is_immutable(client):
    """Verify that system_administrator role permissions cannot be altered."""
    res = client.put(
        '/api/v1/security/roles/system_administrator/permissions',
        json={'permissions': ['system.rbac.manage']},
    )
    assert res.status_code == 404
    assert 'immutable' in res.json()['detail'].lower()


def test_company_admin_cannot_access_role_permissions_endpoint(client, db_session):
    """Verify that a company administrator cannot update role permissions."""
    from app.models import CompanyMembership, Role, User
    from app.authentication import password_hasher

    company = _company(db_session, 'STC')
    role = db_session.scalar(select(Role).where(Role.code == 'company_administrator', Role.scope == 'company'))
    comp_admin_user = User(
        email='sec-comp-admin@example.invalid',
        password_hash=password_hasher.hash('CompAdmin-Secure-Pass-123!'),
        is_active=True,
    )
    db_session.add(comp_admin_user)
    db_session.flush()

    membership = CompanyMembership(
        company_id=company.id,
        user_id=comp_admin_user.id,
        role_id=role.id,
        status='active',
    )
    db_session.add(membership)
    db_session.commit()

    # Login as company admin using helper to set CSRF header
    _login_as(client, 'sec-comp-admin@example.invalid', 'CompAdmin-Secure-Pass-123!')

    # Attempt to modify roles
    res = client.put(
        '/api/v1/security/roles/read_only_user/permissions',
        json={'permissions': ['asset.read']},
    )
    assert res.status_code == 403


# ==============================================================================
# Invitation Workflow Edge Cases & Security
# ==============================================================================


def test_expired_invitation_cannot_be_accepted(client, db_session):
    """Verify that an expired invitation token is rejected."""
    from datetime import timedelta
    from app.models import UserInvitation
    from app.security import digest

    company = _company(db_session, 'EXPIRE')
    invitation_res = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'expired-test@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invitation_res.status_code == 201
    token = invitation_res.json()['token']

    # Backdate expiration to 2 hours in the past
    token_hash = digest(token)
    db_session.query(UserInvitation).filter(
        UserInvitation.token_hash == token_hash
    ).update({'expires_at': datetime.now(timezone.utc) - timedelta(hours=2)})
    db_session.commit()

    # Attempt acceptance
    accept_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Valid-Password-123!'},
    )
    assert accept_res.status_code == 400
    assert 'invalid or expired' in accept_res.json()['detail'].lower()


def test_deactivated_user_cannot_accept_invitation(client, db_session):
    """Verify that an inactive user account cannot accept invitations."""
    from app.models import CompanyMembership, Role, User, UserInvitation
    from app.authentication import password_hasher, digest, INVITATION_LIFETIME
    import secrets

    company = _company(db_session, 'INACT')
    role = db_session.scalar(select(Role).where(Role.code == 'read_only_user', Role.scope == 'company'))

    # Existing deactivated user with a password
    user = User(
        email='deactivated-user@example.invalid',
        password_hash=password_hasher.hash('Deactivated-Pass-123!'),
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    # Attempting to invite a deactivated user via API is rejected (409)
    invite_res = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'deactivated-user@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invite_res.status_code == 409
    assert 'inactive' in invite_res.json()['detail'].lower()

    # Even if an invitation record were directly in database, accept_invitation must reject it
    admin = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    membership = CompanyMembership(
        company_id=company.id,
        user_id=user.id,
        role_id=role.id,
        status='pending',
        assigned_by_id=admin.id,
    )
    db_session.add(membership)
    db_session.flush()

    raw_token = secrets.token_urlsafe(32)
    db_session.add(
        UserInvitation(
            token_hash=digest(raw_token),
            membership_id=membership.id,
            expires_at=datetime.now(timezone.utc) + INVITATION_LIFETIME,
        )
    )
    db_session.commit()

    accept_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': raw_token, 'password': 'Some-New-Password-123!'},
    )
    assert accept_res.status_code == 400
    assert 'invalid or expired' in accept_res.json()['detail'].lower()


def test_accepted_invitation_cannot_be_reused(client, db_session):
    """Verify that an accepted invitation cannot be accepted a second time."""
    company = _company(db_session, 'REUSE')
    invitation_res = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'single-use@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invitation_res.status_code == 201
    token = invitation_res.json()['token']

    # First acceptance succeeds
    first_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Valid-Password-123!'},
    )
    assert first_res.status_code == 200
    assert first_res.json()['status'] == 'invitation_accepted'

    # Second acceptance with same token fails
    second_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': 'Valid-Password-123!'},
    )
    assert second_res.status_code == 400
    assert 'invalid or expired' in second_res.json()['detail'].lower()


def test_existing_active_user_invitation_preserves_original_password(client, db_session):
    """Verify that inviting an existing active user does NOT alter their existing password."""
    from app.models import User
    from app.authentication import password_hasher

    # 1. Create an existing user with known password
    orig_password = 'Original-Password-42!'
    user = User(
        email='existing-user@example.invalid',
        password_hash=password_hasher.hash(orig_password),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    # 2. Invite existing user to new company
    company = _company(db_session, 'EXIST')
    invitation_res = client.post(
        f'/api/v1/security/companies/{company.id}/invitations',
        json={'email': 'existing-user@example.invalid', 'role_code': 'read_only_user'},
    )
    assert invitation_res.status_code == 201
    token = invitation_res.json()['token']

    # 3. Accept invitation with a DIFFERENT password in payload
    attacker_password = 'Attacker-Password-999!'
    accept_res = client.post(
        '/api/v1/auth/invitations/accept',
        json={'token': token, 'password': attacker_password},
    )
    assert accept_res.status_code == 200

    # 4. Attempt login with attacker password -> must fail (401)
    fail_login = client.post(
        '/api/v1/auth/login',
        json={'email': 'existing-user@example.invalid', 'password': attacker_password},
    )
    assert fail_login.status_code == 401

    # 5. Login with original password -> must succeed (200)
    _login_as(client, 'existing-user@example.invalid', orig_password)
    current_user = client.get('/api/v1/auth/me')
    assert current_user.status_code == 200
