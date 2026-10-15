from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.models import (
    AuthSession,
    Company,
    CompanyMembership,
    LoginFailure,
    LoginThrottle,
    Permission,
    Role,
    SystemRoleAssignment,
    User,
    UserInvitation,
    role_permissions,
)
from app.security import digest

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))
SESSION_LIFETIME = timedelta(hours=8)
INVITATION_LIFETIME = timedelta(days=3)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 8


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def password_is_valid(password: str) -> bool:
    return 12 <= len(password) <= 128


def verify_password(password_hash: str | None, password: str) -> bool:
    target = password_hash or DUMMY_PASSWORD_HASH
    try:
        valid = password_hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False
    return bool(valid and password_hash is not None)


def _login_throttle_key(email: str, source: str) -> str:
    return digest(f'{email}\0{source}')


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def login_is_throttled(db: Session, email: str, source: str, now: datetime) -> bool:
    throttle = db.get(LoginThrottle, _login_throttle_key(email, source))
    return (
        throttle is not None
        and throttle.blocked_until is not None
        and _as_utc(throttle.blocked_until) > now
    )


def record_login_failure(db: Session, email: str, source: str, request_id: str | None) -> None:
    now = datetime.now(timezone.utc)
    key = _login_throttle_key(email, source)
    throttle = db.get(LoginThrottle, key)
    if throttle is None:
        throttle = LoginThrottle(key_hash=key, attempts=0, window_started_at=now)
        db.add(throttle)
        db.flush()
    if now - _as_utc(throttle.window_started_at) >= LOGIN_WINDOW:
        throttle.attempts = 0
        throttle.window_started_at = now
        throttle.blocked_until = None
    throttle.attempts += 1
    if throttle.attempts >= MAX_LOGIN_FAILURES:
        throttle.blocked_until = now + LOGIN_BLOCK
    db.add(LoginFailure(identity_hash=digest(email), source_hash=digest(source), occurred_at=now))
    db.info['audit_request_id'] = request_id
    record_security_event(
        db,
        action='auth.login',
        entity_type='User',
        outcome='denied',
        changes={'reason': 'invalid_credentials'},
    )
    db.commit()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not verify_password(user.password_hash if user else None, password):
        return None
    if user is None or not user.is_active:
        return None
    return user


def create_session(db: Session, user: User) -> tuple[AuthSession, str, str]:
    raw_token = secrets.token_urlsafe(32)
    raw_csrf = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        token_hash=digest(raw_token),
        csrf_token_hash=digest(raw_csrf),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + SESSION_LIFETIME,
        last_used_at=datetime.now(timezone.utc),
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.add(auth_session)
    db.add(user)
    return auth_session, raw_token, raw_csrf


def create_invitation(
    db: Session,
    *,
    email: str,
    company_id: UUID,
    role: Role,
    assigned_by_id: UUID,
) -> tuple[CompanyMembership, str]:
    normalized = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        user = User(email=normalized, is_active=False)
        db.add(user)
        db.flush()

    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = CompanyMembership(
            company_id=company_id,
            user_id=user.id,
            role_id=role.id,
            status='pending',
            assigned_by_id=assigned_by_id,
        )
        db.add(membership)
        db.flush()
    elif membership.status == 'active':
        raise ValueError('This user already has an active membership in the company')
    else:
        membership.role_id = role.id
        membership.status = 'pending'
        membership.assigned_by_id = assigned_by_id

    previous_invitations = db.scalars(
        select(UserInvitation).where(
            UserInvitation.membership_id == membership.id,
            UserInvitation.accepted_at.is_(None),
            UserInvitation.revoked_at.is_(None),
        )
    ).all()
    now = datetime.now(timezone.utc)
    for previous in previous_invitations:
        previous.revoked_at = now

    raw_token = secrets.token_urlsafe(32)
    db.add(
        UserInvitation(
            token_hash=digest(raw_token),
            membership_id=membership.id,
            expires_at=now + INVITATION_LIFETIME,
        )
    )
    return membership, raw_token


def accept_invitation(db: Session, token: str, password: str) -> User | None:
    if not password_is_valid(password):
        return None
    now = datetime.now(timezone.utc)
    invitation = db.get(UserInvitation, digest(token))
    expires_at = invitation.expires_at if invitation is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or expires_at <= now
    ):
        return None
    membership = db.get(CompanyMembership, invitation.membership_id)
    if membership is None or membership.status != 'pending':
        return None
    user = db.get(User, membership.user_id)
    company = db.get(Company, membership.company_id)
    if user is None or company is None or not company.is_active or (not user.is_active and user.password_hash is not None):
        return None

    if user.password_hash is None:
        user.password_hash = password_hasher.hash(password)
        user.is_active = True
    membership.status = 'active'
    invitation.accepted_at = now
    return user


def assigned_permission_codes(db: Session, role_id: UUID) -> set[str]:
    return set(
        db.scalars(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_id)
        ).all()
    )


def has_system_administrator(db: Session) -> bool:
    return db.scalar(
        select(SystemRoleAssignment.id)
        .join(Role, Role.id == SystemRoleAssignment.role_id)
        .join(User, User.id == SystemRoleAssignment.user_id)
        .where(Role.code == 'system_administrator', Role.scope == 'system', User.is_active.is_(True))
    ) is not None
