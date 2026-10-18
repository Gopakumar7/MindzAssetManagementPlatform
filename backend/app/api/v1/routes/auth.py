from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.authentication import (
    accept_invitation,
    authenticate,
    create_session,
    login_is_throttled,
    record_login_failure,
)
from app.core.config import settings
from app.database import get_db
from app.models import Company, CompanyMembership, Role, User
from app.schemas import CurrentMembershipRead, CurrentUserRead, InvitationAcceptRequest, LoginRequest
from app.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    CurrentActor,
    current_actor,
    digest,
    permission_codes,
)

router = APIRouter(prefix='/auth', tags=['authentication'])


def _validate_origin(request: Request) -> None:
    origin = request.headers.get('origin')
    if origin is None:
        return

    allowed_origins = settings.cors_origins_list
    if origin in allowed_origins:
        return

    # Nginx must explicitly forward the original host and scheme.
    forwarded_host = request.headers.get('x-forwarded-host')
    forwarded_proto = request.headers.get('x-forwarded-proto')

    if forwarded_host and forwarded_proto:
        expected_origin = f'{forwarded_proto}://{forwarded_host}'
        if origin == expected_origin:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail='Request origin is not allowed',
    )


@router.post('/login')
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    _validate_origin(request)
    email = payload.email.strip().casefold()
    source = request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    now = datetime.now(timezone.utc)
    if login_is_throttled(db, email, source, now):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail='Too many login attempts; try again later')

    user = authenticate(db, email, payload.password)
    if user is None:
        record_login_failure(db, email, source, getattr(request.state, 'request_id', None))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')

    db.info['audit_request_id'] = getattr(request.state, 'request_id', None)
    auth_session, raw_token, raw_csrf = create_session(db, user)
    record_security_event(
        db,
        action='auth.login',
        entity_type='User',
        entity_id=str(user.id),
        actor_id=user.id,
        outcome='success',
    )
    db.commit()

    cookie_secure = settings.cookie_secure
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    max_age = int((expires_at - now).total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max_age,
        httponly=True,
        secure=cookie_secure,
        samesite='lax',
        path='/api/v1',
    )
    response.set_cookie(
        CSRF_COOKIE,
        raw_csrf,
        max_age=max_age,
        httponly=False,
        secure=cookie_secure,
        samesite='lax',
        path='/',
    )
    return {'status': 'authenticated'}


@router.get('/me', response_model=CurrentUserRead)
def read_current_user(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    system_permissions = sorted(permission_codes(db, actor.user.id))
    rows = db.execute(
        select(CompanyMembership, Company, Role)
        .join(Company, Company.id == CompanyMembership.company_id)
        .join(Role, Role.id == CompanyMembership.role_id)
        .where(
            CompanyMembership.user_id == actor.user.id,
            CompanyMembership.status == 'active',
            Company.is_active.is_(True),
        )
        .order_by(Company.name)
    ).all()
    memberships = [
        CurrentMembershipRead(
            company_id=membership.company_id,
            company_code=company.code,
            company_name=company.name,
            role_code=role.code,
            role_name=role.name,
            permissions=sorted(permission_codes(db, actor.user.id, membership.company_id)),
        )
        for membership, company, role in rows
    ]
    return CurrentUserRead(
        id=actor.user.id,
        email=actor.user.email,
        system_permissions=system_permissions,
        memberships=memberships,
    )


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    actor.session.revoked_at = datetime.now(timezone.utc)
    record_security_event(
        db,
        action='auth.logout',
        entity_type='User',
        entity_id=str(actor.user.id),
        actor_id=actor.user.id,
        outcome='success',
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path='/api/v1', secure=settings.cookie_secure, httponly=True, samesite='lax')
    response.delete_cookie(CSRF_COOKIE, path='/', secure=settings.cookie_secure, httponly=False, samesite='lax')
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post('/invitations/accept')
def accept_user_invitation(
    payload: InvitationAcceptRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _validate_origin(request)
    user = accept_invitation(db, payload.token, payload.password)
    if user is None:
        record_security_event(
            db,
            action='auth.invitation.accept',
            entity_type='UserInvitation',
            outcome='denied',
            changes={'reason': 'invalid_or_expired'},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invitation is invalid or expired')
    db.info['audit_actor_id'] = user.id
    db.info['audit_request_id'] = getattr(request.state, 'request_id', None)
    record_security_event(
        db,
        action='auth.invitation.accept',
        entity_type='User',
        entity_id=str(user.id),
        actor_id=user.id,
        outcome='success',
    )
    db.commit()
    return {'status': 'invitation_accepted'}
