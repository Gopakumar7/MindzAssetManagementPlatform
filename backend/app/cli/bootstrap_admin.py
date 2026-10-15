from getpass import getpass

from sqlalchemy import select

from app.audit import record_security_event
from app.authentication import has_system_administrator, normalize_email, password_hasher, password_is_valid
from app.database import SessionLocal
from app.models import Role, SystemRoleAssignment, User


def main() -> None:
    with SessionLocal() as db:
        if has_system_administrator(db):
            raise SystemExit('A system administrator already exists; bootstrap is disabled.')

        email = normalize_email(input('Administrator email: '))
        password = getpass('Administrator password (minimum 12 characters): ')
        confirmation = getpass('Confirm password: ')
        if password != confirmation or not password_is_valid(password):
            raise SystemExit('Passwords must match and contain 12 to 128 characters.')

        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise SystemExit('That email is already registered; no account was changed.')
        role = db.scalar(select(Role).where(Role.code == 'system_administrator', Role.scope == 'system'))
        if role is None:
            raise SystemExit('Security roles have not been installed. Run Alembic migrations first.')

        user = User(email=email, password_hash=password_hasher.hash(password), is_active=True)
        db.add(user)
        db.flush()
        db.add(SystemRoleAssignment(user_id=user.id, role_id=role.id, assigned_by_id=user.id))
        record_security_event(
            db,
            action='security.bootstrap_admin',
            entity_type='User',
            entity_id=str(user.id),
            actor_id=user.id,
            outcome='success',
        )
        db.commit()
        print(f'System administrator provisioned: {user.email}')


if __name__ == '__main__':
    main()
