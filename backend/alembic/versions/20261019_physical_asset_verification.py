"""add physical asset verification tables and permissions

Revision ID: 20261019_verification
Revises: 20261017_dashboard_permission
Create Date: 2026-10-19 14:00:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261019_verification'
down_revision = '20261017_dashboard_permission'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. verification_campaigns
    op.create_table(
        'verification_campaigns',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_reference', sa.String(64), nullable=False),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='draft'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('scope_category_ids', sa.JSON(), nullable=True),
        sa.Column('scope_location_ids', sa.JSON(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_by_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('end_date >= start_date', name='ck_verification_campaigns_date_range'),
        sa.CheckConstraint(
            "status IN ('draft', 'in_progress', 'under_review', 'completed', 'cancelled')",
            name='ck_verification_campaigns_status',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['closed_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_verification_campaigns_company_id_id'),
        sa.UniqueConstraint('company_id', 'campaign_reference', name='uq_verification_campaigns_reference'),
    )
    op.create_index(
        'ix_verification_campaigns_company_status',
        'verification_campaigns',
        ['company_id', 'status'],
    )

    # 2. verification_expected_assets
    op.create_table(
        'verification_expected_assets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('expected_site_id', sa.Uuid(), nullable=True),
        sa.Column('expected_location_id', sa.Uuid(), nullable=True),
        sa.Column('expected_department_id', sa.Uuid(), nullable=True),
        sa.Column('expected_custodian_id', sa.Uuid(), nullable=True),
        sa.Column('expected_custodian_name', sa.String(160), nullable=True),
        sa.Column('expected_condition', sa.String(32), nullable=True),
        sa.Column('expected_status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_verification_expected_assets_company_id_id'),
        sa.UniqueConstraint('campaign_id', 'asset_id', name='uq_verification_expected_assets_campaign_asset'),
    )
    op.create_index(
        'ix_verification_expected_assets_company_campaign',
        'verification_expected_assets',
        ['company_id', 'campaign_id'],
    )
    op.create_index(
        'ix_verification_expected_assets_company_asset',
        'verification_expected_assets',
        ['company_id', 'asset_id'],
    )

    # 3. verification_observations
    op.create_table(
        'verification_observations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('expected_asset_id', sa.Uuid(), nullable=True),
        sa.Column('asset_id', sa.Uuid(), nullable=True),
        sa.Column('is_found', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('actual_site_id', sa.Uuid(), nullable=True),
        sa.Column('actual_location_id', sa.Uuid(), nullable=True),
        sa.Column('actual_department_id', sa.Uuid(), nullable=True),
        sa.Column('actual_custodian_id', sa.Uuid(), nullable=True),
        sa.Column('observed_condition', sa.String(32), nullable=False, server_default='good'),
        sa.Column('verification_date', sa.Date(), nullable=False),
        sa.Column('verified_by_id', sa.Uuid(), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('reference_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_verification_observations_company_id_id'),
        sa.UniqueConstraint('campaign_id', 'expected_asset_id', name='uq_verification_observations_campaign_expected'),
    )
    op.create_index(
        'ix_verification_observations_company_campaign',
        'verification_observations',
        ['company_id', 'campaign_id'],
    )

    # 4. verification_discrepancies
    op.create_table(
        'verification_discrepancies',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('observation_id', sa.Uuid(), nullable=True),
        sa.Column('expected_asset_id', sa.Uuid(), nullable=True),
        sa.Column('asset_id', sa.Uuid(), nullable=True),
        sa.Column('discrepancy_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='open'),
        sa.Column('expected_data', sa.JSON(), nullable=True),
        sa.Column('observed_data', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('resolution_action', sa.String(32), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('resolved_by_id', sa.Uuid(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "discrepancy_type IN ('missing', 'location_mismatch', 'custodian_mismatch', 'condition_mismatch', 'unregistered_asset')",
            name='ck_verification_discrepancies_type',
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name='ck_verification_discrepancies_status',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_verification_discrepancies_company_id_id'),
    )
    op.create_index(
        'ix_verification_discrepancies_company_campaign',
        'verification_discrepancies',
        ['company_id', 'campaign_id'],
    )
    op.create_index(
        'ix_verification_discrepancies_type_status',
        'verification_discrepancies',
        ['company_id', 'discrepancy_type', 'status'],
    )

    # 5. verification_unregistered_assets
    op.create_table(
        'verification_unregistered_assets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('observation_id', sa.Uuid(), nullable=True),
        sa.Column('discrepancy_id', sa.Uuid(), nullable=True),
        sa.Column('serial_number', sa.String(120), nullable=True),
        sa.Column('description', sa.String(200), nullable=False),
        sa.Column('category_id', sa.Uuid(), nullable=False),
        sa.Column('site_id', sa.Uuid(), nullable=True),
        sa.Column('location_id', sa.Uuid(), nullable=True),
        sa.Column('custodian_id', sa.Uuid(), nullable=True),
        sa.Column('observed_condition', sa.String(32), nullable=True, server_default='good'),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('registered_asset_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'registered', 'rejected')",
            name='ck_verification_unregistered_assets_status',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'category_id'],
            ['asset_categories.company_id', 'asset_categories.id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_verification_unregistered_assets_company_id_id'),
    )
    op.create_index(
        'ix_verification_unregistered_assets_campaign',
        'verification_unregistered_assets',
        ['company_id', 'campaign_id'],
    )

    # Seed verification permissions and assign to roles
    bind = op.get_bind()
    permissions = {}
    for code, description in (
        ('verification.read', 'Read company physical asset verification campaigns and discrepancies'),
        ('verification.manage', 'Manage company physical asset verification campaigns, observations, and resolutions'),
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
        'system_administrator': ('verification.read', 'verification.manage'),
        'company_administrator': ('verification.read', 'verification.manage'),
        'asset_manager': ('verification.read', 'verification.manage'),
        'it_support': ('verification.read',),
        'auditor': ('verification.read',),
        'read_only_user': ('verification.read',),
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
        sa.text("SELECT id FROM permissions WHERE code IN ('verification.read', 'verification.manage')")
    ).scalars().all()
    for permission_id in permission_ids:
        bind.execute(
            sa.text('DELETE FROM role_permissions WHERE permission_id = :permission_id'),
            {'permission_id': permission_id},
        )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN ('verification.read', 'verification.manage')")
    )
    op.drop_table('verification_unregistered_assets')
    op.drop_table('verification_discrepancies')
    op.drop_table('verification_observations')
    op.drop_table('verification_expected_assets')
    op.drop_table('verification_campaigns')
