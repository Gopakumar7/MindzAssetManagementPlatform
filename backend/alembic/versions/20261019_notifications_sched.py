"""add scheduled job executions and notifications tables and permissions

Revision ID: 20261019_notifications_sched
Revises: 20261019_asset_alerts
Create Date: 2026-10-19 21:30:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261019_notifications_sched'
down_revision = '20261019_asset_alerts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. scheduled_job_executions table
    op.create_table(
        'scheduled_job_executions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('job_name', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('total_companies_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('alerts_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('alerts_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('alerts_auto_resolved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('node_id', sa.String(120), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scheduled_job_executions')),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name='ck_scheduled_job_executions_status'),
    )
    op.create_index('ix_scheduled_job_executions_name_started', 'scheduled_job_executions', ['job_name', 'started_at'])
    op.create_index('ix_scheduled_job_executions_status', 'scheduled_job_executions', ['status'])

    # 2. notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('recipient_user_id', sa.Uuid(), nullable=False),
        sa.Column('notification_type', sa.String(64), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False, server_default='info'),
        sa.Column('entity_type', sa.String(64), nullable=True),
        sa.Column('entity_id', sa.Uuid(), nullable=True),
        sa.Column('target_route', sa.String(200), nullable=True),
        sa.Column('dedup_key', sa.String(255), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='unread'),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_notifications_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], name=op.f('fk_notifications_recipient_user_id_users'), ondelete='CASCADE'),
        sa.UniqueConstraint('dedup_key', name='uq_notifications_dedup_key'),
        sa.CheckConstraint("severity IN ('critical', 'warning', 'info')", name='ck_notifications_severity'),
        sa.CheckConstraint("status IN ('unread', 'read', 'archived')", name='ck_notifications_status'),
    )
    op.create_index('ix_notifications_company_id', 'notifications', ['company_id'])
    op.create_index('ix_notifications_recipient_user_id', 'notifications', ['recipient_user_id'])
    op.create_index('ix_notifications_recipient_status', 'notifications', ['recipient_user_id', 'status'])
    op.create_index('ix_notifications_company_created', 'notifications', ['company_id', 'created_at'])
    op.create_index('ix_notifications_entity', 'notifications', ['entity_type', 'entity_id'])

    # 3. notification_deliveries table
    op.create_table(
        'notification_deliveries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('notification_id', sa.Uuid(), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False, server_default='email'),
        sa.Column('recipient_address', sa.String(320), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_deliveries')),
        sa.ForeignKeyConstraint(['notification_id'], ['notifications.id'], name=op.f('fk_notification_deliveries_notification_id_notifications'), ondelete='CASCADE'),
        sa.CheckConstraint("channel IN ('email', 'webhook', 'sms')", name='ck_notification_deliveries_channel'),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name='ck_notification_deliveries_status'),
    )
    op.create_index('ix_notification_deliveries_notification_id', 'notification_deliveries', ['notification_id'])
    op.create_index('ix_notification_deliveries_status', 'notification_deliveries', ['status'])

    # 4. Seed permissions into database
    bind = op.get_bind()
    permissions_table = sa.table(
        'permissions',
        sa.column('id', sa.Uuid()),
        sa.column('code', sa.String()),
        sa.column('description', sa.String()),
    )
    roles_table = sa.table(
        'roles',
        sa.column('id', sa.Uuid()),
        sa.column('scope', sa.String()),
        sa.column('code', sa.String()),
    )
    role_permissions_table = sa.table(
        'role_permissions',
        sa.column('role_id', sa.Uuid()),
        sa.column('permission_id', sa.Uuid()),
    )

    new_permissions = [
        ('notifications.read', 'Read personal in-app notifications and delivery status'),
        ('notifications.manage', 'Mark notifications as read or archive them'),
    ]

    perm_ids = {}
    for code, desc in new_permissions:
        existing = bind.execute(
            sa.select(permissions_table.c.id).where(permissions_table.c.code == code)
        ).scalar_one_or_none()
        if existing:
            perm_ids[code] = existing
        else:
            new_id = uuid4()
            bind.execute(
                permissions_table.insert().values(id=new_id, code=code, description=desc)
            )
            perm_ids[code] = new_id

    role_mapping = {
        'company_administrator': ['notifications.read', 'notifications.manage'],
        'asset_manager': ['notifications.read', 'notifications.manage'],
        'it_support': ['notifications.read', 'notifications.manage'],
        'auditor': ['notifications.read', 'notifications.manage'],
        'read_only_user': ['notifications.read', 'notifications.manage'],
    }

    for role_code, p_codes in role_mapping.items():
        role_id = bind.execute(
            sa.select(roles_table.c.id).where(
                roles_table.c.scope == 'company',
                roles_table.c.code == role_code,
            )
        ).scalar_one_or_none()
        if not role_id:
            continue
        for p_code in p_codes:
            pid = perm_ids.get(p_code)
            if not pid:
                continue
            exists = bind.execute(
                sa.select(role_permissions_table.c.role_id).where(
                    role_permissions_table.c.role_id == role_id,
                    role_permissions_table.c.permission_id == pid,
                )
            ).scalar_one_or_none()
            if not exists:
                bind.execute(
                    role_permissions_table.insert().values(role_id=role_id, permission_id=pid)
                )


def downgrade() -> None:
    op.drop_index('ix_notification_deliveries_status', table_name='notification_deliveries')
    op.drop_index('ix_notification_deliveries_notification_id', table_name='notification_deliveries')
    op.drop_table('notification_deliveries')

    op.drop_index('ix_notifications_entity', table_name='notifications')
    op.drop_index('ix_notifications_company_created', table_name='notifications')
    op.drop_index('ix_notifications_recipient_status', table_name='notifications')
    op.drop_index('ix_notifications_recipient_user_id', table_name='notifications')
    op.drop_index('ix_notifications_company_id', table_name='notifications')
    op.drop_table('notifications')

    op.drop_index('ix_scheduled_job_executions_status', table_name='scheduled_job_executions')
    op.drop_index('ix_scheduled_job_executions_name_started', table_name='scheduled_job_executions')
    op.drop_table('scheduled_job_executions')
