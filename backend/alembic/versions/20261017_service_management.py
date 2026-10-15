"""add warranty contracts and maintenance requests

Revision ID: 20261017_service_management
Revises: 20261016_procurement
Create Date: 2026-10-17 00:00:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261017_service_management'
down_revision = '20261016_procurement'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'asset_service_contracts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('supplier_id', sa.Uuid(), nullable=True),
        sa.Column('contract_type', sa.String(16), nullable=False),
        sa.Column('provider_name', sa.String(160), nullable=True),
        sa.Column('reference_number', sa.String(160), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('coverage_description', sa.Text(), nullable=True),
        sa.Column('support_contact', sa.String(320), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("contract_type IN ('warranty', 'amc')", name='ck_asset_service_contracts_type'),
        sa.CheckConstraint("status IN ('active', 'cancelled')", name='ck_asset_service_contracts_status'),
        sa.CheckConstraint('end_date >= start_date', name='ck_asset_service_contracts_date_range'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'supplier_id'], ['suppliers.company_id', 'suppliers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_asset_service_contracts_company_id'),
        sa.UniqueConstraint(
            'company_id', 'asset_id', 'reference_number',
            name='uq_asset_service_contracts_asset_reference',
        ),
    )
    op.create_index(
        'ix_asset_service_contracts_company_asset',
        'asset_service_contracts',
        ['company_id', 'asset_id'],
    )
    op.create_table(
        'maintenance_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('assignee_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('issue_description', sa.Text(), nullable=False),
        sa.Column('priority', sa.String(16), nullable=False, server_default='normal'),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('reported_date', sa.Date(), nullable=False),
        sa.Column('diagnosis', sa.Text(), nullable=True),
        sa.Column('work_performed', sa.Text(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('completed_date', sa.Date(), nullable=True),
        sa.Column('cost', sa.Numeric(14, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name='ck_maintenance_requests_priority'),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name='ck_maintenance_requests_status'),
        sa.CheckConstraint('cost IS NULL OR cost >= 0', name='ck_maintenance_requests_cost'),
        sa.CheckConstraint(
            "(status NOT IN ('resolved', 'closed')) OR (completed_date IS NOT NULL)",
            name='ck_maintenance_requests_completed_date',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['requester_id'],
            ['users.id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'assignee_id'],
            ['company_memberships.company_id', 'company_memberships.user_id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_maintenance_requests_company_id'),
    )
    op.create_index(
        'ix_maintenance_requests_company_status',
        'maintenance_requests',
        ['company_id', 'status'],
    )
    op.create_index(
        'ix_maintenance_requests_company_asset',
        'maintenance_requests',
        ['company_id', 'asset_id'],
    )

    bind = op.get_bind()
    permissions = {}
    for code, description in (
        ('maintenance.read', 'Read company service contracts and maintenance requests'),
        ('maintenance.manage', 'Manage company service contracts and maintenance requests'),
    ):
        permission_id = bind.execute(
            sa.text('SELECT id FROM permissions WHERE code = :code'),
            {'code': code},
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = uuid4()
            bind.execute(
                sa.text('INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description)'),
                {'id': permission_id, 'code': code, 'description': description},
            )
        permissions[code] = permission_id

    grants = {
        'system_administrator': ('maintenance.read', 'maintenance.manage'),
        'company_administrator': ('maintenance.read', 'maintenance.manage'),
        'asset_manager': ('maintenance.read', 'maintenance.manage'),
        'it_support': ('maintenance.read', 'maintenance.manage'),
        'auditor': ('maintenance.read',),
        'read_only_user': ('maintenance.read',),
    }
    for role_code, codes in grants.items():
        scope = 'system' if role_code == 'system_administrator' else 'company'
        role_id = bind.execute(
            sa.text('SELECT id FROM roles WHERE scope = :scope AND code = :code'),
            {'scope': scope, 'code': role_code},
        ).scalar_one_or_none()
        if role_id is None:
            continue
        for code in codes:
            bind.execute(
                sa.text(
                    'INSERT INTO role_permissions (role_id, permission_id) '
                    'VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING'
                ),
                {'role_id': role_id, 'permission_id': permissions[code]},
            )


def downgrade() -> None:
    bind = op.get_bind()
    permission_ids = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code IN ('maintenance.read', 'maintenance.manage')")
    ).scalars().all()
    for permission_id in permission_ids:
        bind.execute(
            sa.text('DELETE FROM role_permissions WHERE permission_id = :permission_id'),
            {'permission_id': permission_id},
        )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN ('maintenance.read', 'maintenance.manage')")
    )
    op.drop_table('maintenance_requests')
    op.drop_table('asset_service_contracts')
