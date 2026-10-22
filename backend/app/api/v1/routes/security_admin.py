from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.authentication import (
    assigned_permission_codes,
    create_invitation,
    has_system_administrator,
    normalize_email,
)
from app.database import get_db
from app.models import (
    AuthSession,
    AuditEvent,
    CompanyMembership,
    Permission,
    Role,
    SystemRoleAssignment,
    User,
    UserInvitation,
    role_permissions,
)
from app.schemas import (
    AuditEventRead,
    InvitationCreateRequest,
    InvitationCreateResponse,
    MemberRead,
    MembershipUpdateRequest,
    RolePermissionsUpdateRequest,
    RoleRead,
)
from app.security import (
    CurrentActor,
    actor_has_permission,
    current_actor,
    permission_codes,
    require_permission,
)

router = APIRouter(prefix='/security', tags=['security administration'])


@router.get('/companies/{company_id}/roles', response_model=list[RoleRead])
def list_company_roles(
    company_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('company.members.manage')),
):
    roles = db.scalars(select(Role).where(Role.scope == 'company').order_by(Role.name)).all()
    return [
        RoleRead(code=role.code, name=role.name, scope=role.scope, permissions=sorted(assigned_permission_codes(db, role.id)))
        for role in roles
    ]


@router.get('/companies/{company_id}/members', response_model=list[MemberRead])
def list_members(
    company_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('company.members.manage')),
):
    rows = db.execute(
        select(CompanyMembership, User, Role)
        .join(User, User.id == CompanyMembership.user_id)
        .join(Role, Role.id == CompanyMembership.role_id)
        .where(CompanyMembership.company_id == company_id)
        .order_by(User.email)
    ).all()
    return [
        MemberRead(
            id=user.id,
            email=user.email,
            membership_id=membership.id,
            status=membership.status,
            role_code=role.code,
            role_name=role.name,
            created_at=membership.created_at,
        )
        for membership, user, role in rows
    ]


@router.post(
    '/companies/{company_id}/invitations',
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    company_id: UUID,
    payload: InvitationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('company.members.manage')),
):
    role = db.scalar(select(Role).where(Role.code == payload.role_code, Role.scope == 'company'))
    if role is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Unknown company role')
    normalized_email = normalize_email(payload.email)
    existing_user = db.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None and existing_user.id == actor.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You cannot change your own membership')

    actor_permissions = permission_codes(db, actor.user.id, company_id)
    actor_permissions.update(permission_codes(db, actor.user.id))
    if not assigned_permission_codes(db, role.id).issubset(actor_permissions):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot grant permissions you do not hold')
    if existing_user is not None and not existing_user.is_active and existing_user.password_hash is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='This account is inactive')

    try:
        membership, raw_token = create_invitation(
            db,
            email=normalized_email,
            company_id=company_id,
            role=role,
            assigned_by_id=actor.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.info['audit_request_id'] = getattr(request.state, 'request_id', None)
    record_security_event(
        db,
        action='security.member.invited',
        entity_type='CompanyMembership',
        entity_id=str(membership.id),
        actor_id=actor.user.id,
        company_id=company_id,
        outcome='success',
        changes={'email': normalized_email, 'role_code': role.code},
    )
    db.commit()
    invitation = db.scalar(
        select(UserInvitation).where(UserInvitation.membership_id == membership.id, UserInvitation.accepted_at.is_(None))
        .order_by(UserInvitation.created_at.desc())
    )
    return InvitationCreateResponse(
        email=normalized_email,
        company_id=company_id,
        role_code=role.code,
        token=raw_token,
        expires_at=invitation.expires_at,
    )


@router.patch('/companies/{company_id}/members/{membership_id}', response_model=MemberRead)
def update_member(
    company_id: UUID,
    membership_id: UUID,
    payload: MembershipUpdateRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('company.members.manage')),
):
    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Membership not found')
    if membership.user_id == actor.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='You cannot change your own membership')

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='No membership changes supplied')
    if 'role_code' in changes:
        role = db.scalar(select(Role).where(Role.code == changes['role_code'], Role.scope == 'company'))
        if role is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Unknown company role')
        actor_permissions = permission_codes(db, actor.user.id, company_id)
        actor_permissions.update(permission_codes(db, actor.user.id))
        if not assigned_permission_codes(db, role.id).issubset(actor_permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Cannot grant permissions you do not hold')
        membership.role_id = role.id
    if changes.get('status') == 'revoked':
        membership.status = 'revoked'
        now = datetime.now(timezone.utc)
        for invitation in db.scalars(
            select(UserInvitation).where(
                UserInvitation.membership_id == membership.id,
                UserInvitation.accepted_at.is_(None),
                UserInvitation.revoked_at.is_(None),
            )
        ).all():
            invitation.revoked_at = now
    record_security_event(
        db,
        action='security.member.updated',
        entity_type='CompanyMembership',
        entity_id=str(membership.id),
        actor_id=actor.user.id,
        company_id=company_id,
        outcome='success',
        changes=changes,
    )
    db.commit()
    user = db.get(User, membership.user_id)
    role = db.get(Role, membership.role_id)
    return MemberRead(
        id=user.id,
        email=user.email,
        membership_id=membership.id,
        status=membership.status,
        role_code=role.code,
        role_name=role.name,
        created_at=membership.created_at,
    )


@router.post('/system-administrators/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
def assign_system_administrator(
    user_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('system.users.manage')),
):
    user = db.get(User, user_id)
    role = db.scalar(select(Role).where(Role.code == 'system_administrator', Role.scope == 'system'))
    if user is None or not user.is_active or role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Active user not found')
    existing = db.scalar(
        select(SystemRoleAssignment.id).where(
            SystemRoleAssignment.user_id == user.id,
            SystemRoleAssignment.role_id == role.id,
        )
    )
    if existing is None:
        db.add(SystemRoleAssignment(user_id=user.id, role_id=role.id, assigned_by_id=actor.user.id))
        record_security_event(
            db,
            action='security.system_admin.assigned',
            entity_type='User',
            entity_id=str(user.id),
            actor_id=actor.user.id,
            outcome='success',
        )
        db.commit()
    return None


@router.delete('/system-administrators/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
def revoke_system_administrator(
    user_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('system.users.manage')),
):
    if user_id == actor.user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Administrators cannot revoke their own system role')
    role = db.scalar(select(Role).where(Role.code == 'system_administrator', Role.scope == 'system'))
    assignment = db.scalar(
        select(SystemRoleAssignment).where(
            SystemRoleAssignment.user_id == user_id,
            SystemRoleAssignment.role_id == role.id,
        )
    ) if role is not None else None
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='System administrator not found')
    db.delete(assignment)
    if not has_system_administrator(db):
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='At least one system administrator must remain')
    record_security_event(
        db,
        action='security.system_admin.revoked',
        entity_type='User',
        entity_id=str(user_id),
        actor_id=actor.user.id,
        outcome='success',
    )
    db.commit()
    return None


@router.patch('/users/{user_id}/active', status_code=status.HTTP_204_NO_CONTENT)
def set_user_active(
    user_id: UUID,
    active: bool = Query(...),
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('system.users.manage')),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')
    if not active and user.id == actor.user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Administrators cannot deactivate themselves')
    user.is_active = active
    if not active:
        db.flush()
        if not has_system_administrator(db):
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='At least one active system administrator must remain')
        for session in db.scalars(
            select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        ).all():
            session.revoked_at = datetime.now(timezone.utc)
        pending_memberships = db.scalars(
            select(CompanyMembership).where(
                CompanyMembership.user_id == user_id,
                CompanyMembership.status == 'pending',
            )
        ).all()
        pending_ids = [membership.id for membership in pending_memberships]
        for membership in pending_memberships:
            membership.status = 'revoked'
        if pending_ids:
            for invitation in db.scalars(
                select(UserInvitation).where(
                    UserInvitation.membership_id.in_(pending_ids),
                    UserInvitation.accepted_at.is_(None),
                    UserInvitation.revoked_at.is_(None),
                )
            ).all():
                invitation.revoked_at = datetime.now(timezone.utc)
    record_security_event(
        db,
        action='security.user.status_updated',
        entity_type='User',
        entity_id=str(user.id),
        actor_id=actor.user.id,
        outcome='success',
        changes={'is_active': active},
    )
    db.commit()
    return None


@router.get('/roles', response_model=list[RoleRead])
def list_roles(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('system.rbac.manage')),
):
    roles = db.scalars(select(Role).order_by(Role.scope, Role.name)).all()
    return [
        RoleRead(code=role.code, name=role.name, scope=role.scope, permissions=sorted(assigned_permission_codes(db, role.id)))
        for role in roles
    ]


@router.put('/roles/{role_code}/permissions', response_model=RoleRead)
def update_role_permissions(
    role_code: str,
    payload: RolePermissionsUpdateRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('system.rbac.manage')),
):
    role = db.scalar(select(Role).where(Role.code == role_code))
    if role is None or role.code == 'system_administrator':
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Role not found or immutable')
    new_codes = set(payload.permissions)
    permissions = db.scalars(select(Permission).where(Permission.code.in_(new_codes))).all()
    if {permission.code for permission in permissions} != new_codes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Unknown permission identifier')
    old_codes = assigned_permission_codes(db, role.id)
    db.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
    db.execute(
        role_permissions.insert(),
        [{'role_id': role.id, 'permission_id': permission.id} for permission in permissions],
    )
    record_security_event(
        db,
        action='security.role.permissions.updated',
        entity_type='Role',
        entity_id=role.code,
        actor_id=actor.user.id,
        changes={'before': sorted(old_codes), 'after': sorted(new_codes)},
    )
    db.commit()
    return RoleRead(code=role.code, name=role.name, scope=role.scope, permissions=sorted(new_codes))


@router.get('/audit', response_model=list[AuditEventRead])
def list_audit_events(
    company_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    before: datetime | None = None,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    if company_id is None:
        if not actor_has_permission(db, actor.user.id, None, 'audit.read'):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Specify an authorized company scope')
    else:
        company = db.get(Company, company_id)
        if (
            company is None
            or (not company.is_active and not actor_has_permission(db, actor.user.id, None, 'system.companies.manage'))
            or not actor_has_permission(db, actor.user.id, company_id, 'audit.read')
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found')

    query = select(AuditEvent)
    if company_id is not None:
        query = query.where(AuditEvent.company_id == company_id)
    elif not actor_has_permission(db, actor.user.id, None, 'system.users.manage'):
        authorized_company_ids = db.scalars(
            select(CompanyMembership.company_id).where(
                CompanyMembership.user_id == actor.user.id,
                CompanyMembership.status == 'active',
            )
        ).all()
        query = query.where(AuditEvent.company_id.in_(authorized_company_ids))
    if actor_id is not None:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if before:
        query = query.where(AuditEvent.occurred_at < before)
    return db.scalars(query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id).limit(limit)).all()
