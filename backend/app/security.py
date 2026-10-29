from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.database import get_db
from app.models import (
    AuthSession,
    Company,
    CompanyMembership,
    Permission,
    Role,
    SystemRoleAssignment,
    User,
    role_permissions,
)

SESSION_COOKIE = 'mindzen_session'
CSRF_COOKIE = 'mindzen_csrf'
CSRF_HEADER = 'X-CSRF-Token'

SYSTEM_PERMISSION_CODES = {
    'system.companies.manage',
    'system.users.manage',
    'system.rbac.manage',
    'company.create',
}


def is_system_permission(code: str) -> bool:
    """Determine if a permission code is platform/system-scoped."""
    return code.startswith('system.') or code == 'company.create'


def is_company_permission(code: str) -> bool:
    """Determine if a permission code is company-scoped."""
    return not is_system_permission(code)



@dataclass(frozen=True)
class CurrentActor:
    user: User
    session: AuthSession


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _has_system_permission(db: Session, user_id: UUID, permission_code: str) -> bool:
    return db.scalar(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .join(Role, Role.id == role_permissions.c.role_id)
        .join(SystemRoleAssignment, SystemRoleAssignment.role_id == Role.id)
        .where(
            SystemRoleAssignment.user_id == user_id,
            Role.scope == 'system',
            Permission.code == permission_code,
        )
    ) is not None


def actor_has_permission(
    db: Session,
    user_id: UUID,
    company_id: UUID | None,
    permission_code: str,
) -> bool:
    if _has_system_permission(db, user_id, permission_code):
        return True
    if company_id is None:
        return False
    return db.scalar(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .join(Role, Role.id == role_permissions.c.role_id)
        .join(CompanyMembership, CompanyMembership.role_id == Role.id)
        .where(
            CompanyMembership.user_id == user_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == 'active',
            Role.scope == 'company',
            Permission.code == permission_code,
        )
    ) is not None


def current_actor(request: Request, db: Session = Depends(get_db)) -> CurrentActor:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')

    session = db.get(AuthSession, digest(raw_token))
    now = utc_now()
    expires_at = session.expires_at if session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if session is None or session.revoked_at is not None or expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')

    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')

    db.info['audit_actor_id'] = user.id
    db.info['audit_request_id'] = getattr(request.state, 'request_id', None)
    if request.method.upper() in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        csrf_cookie = request.cookies.get(CSRF_COOKIE, '')
        csrf_header = request.headers.get(CSRF_HEADER, '')
        if (
            not csrf_cookie
            or not csrf_header
            or not hmac.compare_digest(csrf_cookie, csrf_header)
            or not hmac.compare_digest(digest(csrf_cookie), session.csrf_token_hash)
        ):
            record_security_event(
                db,
                action='auth.csrf',
                entity_type='API',
                entity_id=request.url.path,
                actor_id=user.id,
                outcome='denied',
                changes={'reason': 'csrf_validation_failed'},
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='CSRF validation failed')

    request.state.current_actor = user
    return CurrentActor(user=user, session=session)


def require_permission(permission_code: str):
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        actor: CurrentActor = Depends(current_actor),
    ) -> CurrentActor:
        raw_company_id = request.path_params.get('company_id')
        company_id: UUID | None = None
        if raw_company_id is not None:
            try:
                company_id = UUID(str(raw_company_id))
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found') from exc
            company = db.get(Company, company_id)
            if company is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found')
            system_company_manager = _has_system_permission(db, actor.user.id, 'system.companies.manage')
            if not company.is_active and not (
                permission_code == 'company.update' and system_company_manager
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found')
            if not system_company_manager and not actor_has_permission(db, actor.user.id, company_id, 'company.read'):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found')

        if not actor_has_permission(db, actor.user.id, company_id, permission_code):
            record_security_event(
                db,
                action='authz.denied',
                entity_type='API',
                entity_id=request.url.path,
                actor_id=actor.user.id,
                company_id=company_id,
                outcome='denied',
                changes={'permission': permission_code},
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Insufficient permission')
        return actor

    return dependency


def permission_codes(db: Session, user_id: UUID, company_id: UUID | None = None) -> set[str]:
    query = (
        select(Permission.code)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .join(Role, Role.id == role_permissions.c.role_id)
    )
    if company_id is None:
        query = query.join(SystemRoleAssignment, SystemRoleAssignment.role_id == Role.id).where(
            SystemRoleAssignment.user_id == user_id,
            Role.scope == 'system',
        )
    else:
        query = query.join(CompanyMembership, CompanyMembership.role_id == Role.id).where(
            CompanyMembership.user_id == user_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == 'active',
            Role.scope == 'company',
        )
    return set(db.scalars(query).all())
