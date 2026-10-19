"""add asset alerts and action centre tables and permissions

Revision ID: 20261019_asset_alerts
Revises: 20261019_financial_lifecycle
Create Date: 2026-10-19 18:45:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261019_asset_alerts'
down_revision = '20261019_financial_lifecycle'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. asset_alerts table
    op.create_table(
        'asset_alerts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('alert_type', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False, server_default='warning'),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('entity_reference', sa.String(160), nullable=True),
        sa.Column('asset_id', sa.Uuid(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('days_overdue', sa.Integer(), nullable=True),
        sa.Column('responsible_user_id', sa.Uuid(), nullable=True),
        sa.Column('target_route', sa.String(200), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by_id', sa.Uuid(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_id', sa.Uuid(), nullable=True),
        sa.Column('resolution_reason', sa.String(32), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_asset_alerts')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_asset_alerts_company_id_companies'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id'], name=op.f('fk_asset_alerts_responsible_user_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['acknowledged_by_id'], ['users.id'], name=op.f('fk_asset_alerts_acknowledged_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], name=op.f('fk_asset_alerts_resolved_by_id_users'), ondelete='SET NULL'),
        sa.UniqueConstraint('company_id', 'id', name='uq_asset_alerts_company_id_id'),
        sa.CheckConstraint("severity IN ('critical', 'warning', 'info')", name='ck_asset_alerts_severity'),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'dismissed')", name='ck_asset_alerts_status'),
        sa.CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN ('source_resolved', 'manual_resolution', 'dismissed')",
            name='ck_asset_alerts_resolution_reason',
        ),
    )

    op.create_index(
        'uq_asset_alerts_active_entity',
        'asset_alerts',
        ['company_id', 'alert_type', 'entity_type', 'entity_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
        sqlite_where=sa.text("status IN ('open', 'acknowledged')"),
    )
    op.create_index('ix_asset_alerts_company_status', 'asset_alerts', ['company_id', 'status'])
    op.create_index('ix_asset_alerts_company_severity', 'asset_alerts', ['company_id', 'severity'])
    op.create_index('ix_asset_alerts_company_type', 'asset_alerts', ['company_id', 'alert_type'])
    op.create_index('ix_asset_alerts_company_asset', 'asset_alerts', ['company_id', 'asset_id'])

    # 2. Seed alerts permissions into database
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
        ('alerts.read', 'Read company lifecycle alerts and action centre'),
        ('alerts.manage', 'Acknowledge, assign, dismiss, and resolve company lifecycle alerts'),
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
        'company_administrator': ['alerts.read', 'alerts.manage'],
        'asset_manager': ['alerts.read', 'alerts.manage'],
        'it_support': ['alerts.read', 'alerts.manage'],
        'auditor': ['alerts.read'],
        'read_only_user': ['alerts.read'],
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
    op.drop_index('ix_asset_alerts_company_asset', table_name='asset_alerts')
    op.drop_index('ix_asset_alerts_company_type', table_name='asset_alerts')
    op.drop_index('ix_asset_alerts_company_severity', table_name='asset_alerts')
    op.drop_index('ix_asset_alerts_company_status', table_name='asset_alerts')
    op.drop_index('uq_asset_alerts_active_entity', table_name='asset_alerts')
    op.drop_table('asset_alerts')

