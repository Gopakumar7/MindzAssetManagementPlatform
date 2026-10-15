"""security foundation

Revision ID: 20261014_security
Revises: b7b05462a977
Create Date: 2026-10-14 17:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.security_seed import seed_security_defaults

revision = '20261014_security'
down_revision = 'b7b05462a977'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'permissions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=240), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_table(
        'roles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('scope', sa.String(length=16), nullable=False),
        sa.CheckConstraint("scope IN ('system', 'company')", name='ck_roles_scope'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scope', 'code', name='uq_roles_scope_code'),
    )
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('permission_id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_users_email_lower', 'users', [sa.text('lower(email)')], unique=True)
    op.create_table(
        'company_memberships',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('assigned_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'active', 'revoked')", name='ck_company_memberships_status'),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'user_id', name='uq_company_memberships_company_user'),
    )
    op.create_index(op.f('ix_company_memberships_company_id'), 'company_memberships', ['company_id'])
    op.create_index(op.f('ix_company_memberships_user_id'), 'company_memberships', ['user_id'])
    op.create_table(
        'system_role_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('assigned_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_system_role_assignments_user_role'),
    )
    op.create_index(op.f('ix_system_role_assignments_user_id'), 'system_role_assignments', ['user_id'])
    op.create_table(
        'auth_sessions',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('csrf_token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index(op.f('ix_auth_sessions_expires_at'), 'auth_sessions', ['expires_at'])
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'])
    op.create_table(
        'user_invitations',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('membership_id', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['membership_id'], ['company_memberships.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index(op.f('ix_user_invitations_expires_at'), 'user_invitations', ['expires_at'])
    op.create_index(op.f('ix_user_invitations_membership_id'), 'user_invitations', ['membership_id'])
    op.create_table(
        'login_throttles',
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('blocked_until', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('key_hash'),
    )
    op.create_table(
        'login_failures',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('identity_hash', sa.String(length=64), nullable=False),
        sa.Column('source_hash', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_login_failures_identity_hash'), 'login_failures', ['identity_hash'])
    op.create_index(op.f('ix_login_failures_occurred_at'), 'login_failures', ['occurred_at'])
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=True),
        sa.Column('outcome', sa.String(length=16), nullable=False),
        sa.Column('request_id', sa.String(length=100), nullable=True),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_events_actor_id'), 'audit_events', ['actor_id'])
    op.create_index(op.f('ix_audit_events_company_id'), 'audit_events', ['company_id'])
    op.create_index(op.f('ix_audit_events_occurred_at'), 'audit_events', ['occurred_at'])
    op.create_index(op.f('ix_audit_events_request_id'), 'audit_events', ['request_id'])

    with Session(bind=op.get_bind()) as db:
        seed_security_defaults(db, commit=False)

    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit events are append-only';
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events')
        op.execute('DROP FUNCTION IF EXISTS reject_audit_event_mutation()')

    op.drop_index(op.f('ix_audit_events_request_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_occurred_at'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_company_id'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_actor_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index(op.f('ix_login_failures_occurred_at'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_identity_hash'), table_name='login_failures')
    op.drop_table('login_failures')
    op.drop_table('login_throttles')
    op.drop_index(op.f('ix_user_invitations_expires_at'), table_name='user_invitations')
    op.drop_index(op.f('ix_user_invitations_membership_id'), table_name='user_invitations')
    op.drop_table('user_invitations')
    op.drop_index(op.f('ix_auth_sessions_user_id'), table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_expires_at'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index(op.f('ix_system_role_assignments_user_id'), table_name='system_role_assignments')
    op.drop_table('system_role_assignments')
    op.drop_index(op.f('ix_company_memberships_user_id'), table_name='company_memberships')
    op.drop_index(op.f('ix_company_memberships_company_id'), table_name='company_memberships')
    op.drop_table('company_memberships')
    op.drop_table('role_permissions')
    op.drop_index('uq_users_email_lower', table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('permissions')
