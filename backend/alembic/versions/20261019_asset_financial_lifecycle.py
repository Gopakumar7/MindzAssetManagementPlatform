"""add asset financial lifecycle, depreciation, disposal tables and permissions

Revision ID: 20261019_financial_lifecycle
Revises: 20261019_verification
Create Date: 2026-10-19 16:00:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261019_financial_lifecycle'
down_revision = '20261019_verification'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. asset_financials
    op.create_table(
        'asset_financials',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('capitalised_cost', sa.Numeric(14, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('depreciation_method', sa.String(32), nullable=False, server_default='straight_line'),
        sa.Column('useful_life_months', sa.Integer(), nullable=False),
        sa.Column('residual_value', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('depreciation_start_date', sa.Date(), nullable=False),
        sa.Column('accumulated_depreciation', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('current_book_value', sa.Numeric(14, 2), nullable=False),
        sa.Column('financial_status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_asset_financials_company_id_id'),
        sa.UniqueConstraint('company_id', 'asset_id', name='uq_asset_financials_company_asset'),
        sa.CheckConstraint('capitalised_cost >= 0', name='ck_asset_financials_capitalised_cost'),
        sa.CheckConstraint('residual_value >= 0', name='ck_asset_financials_residual_value'),
        sa.CheckConstraint('residual_value <= capitalised_cost', name='ck_asset_financials_residual_le_cost'),
        sa.CheckConstraint('useful_life_months > 0', name='ck_asset_financials_useful_life_months'),
        sa.CheckConstraint('accumulated_depreciation >= 0', name='ck_asset_financials_accum_deprec_gte_zero'),
        sa.CheckConstraint('accumulated_depreciation <= capitalised_cost - residual_value', name='ck_asset_financials_accum_deprec_le_basis'),
        sa.CheckConstraint('current_book_value >= residual_value', name='ck_asset_financials_book_value_gte_residual'),
        sa.CheckConstraint("financial_status IN ('draft', 'active', 'fully_depreciated', 'disposed')", name='ck_asset_financials_status'),
        sa.CheckConstraint("depreciation_method IN ('straight_line')", name='ck_asset_financials_method'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_asset_financials_company_status', 'asset_financials', ['company_id', 'financial_status'])
    op.create_index('ix_asset_financials_company_asset', 'asset_financials', ['company_id', 'asset_id'])

    # 2. asset_depreciation_entries
    op.create_table(
        'asset_depreciation_entries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('period', sa.String(7), nullable=False),
        sa.Column('period_start_date', sa.Date(), nullable=False),
        sa.Column('period_end_date', sa.Date(), nullable=False),
        sa.Column('depreciation_amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('accumulated_depreciation_after', sa.Numeric(14, 2), nullable=False),
        sa.Column('book_value_after', sa.Numeric(14, 2), nullable=False),
        sa.Column('method', sa.String(32), nullable=False, server_default='straight_line'),
        sa.Column('posted_by_id', sa.Uuid(), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_asset_deprec_entries_company_id_id'),
        sa.UniqueConstraint('company_id', 'asset_id', 'period', name='uq_asset_deprec_entries_company_asset_period'),
        sa.CheckConstraint('depreciation_amount >= 0', name='ck_asset_deprec_entries_amount'),
        sa.CheckConstraint('accumulated_depreciation_after >= 0', name='ck_asset_deprec_entries_accum'),
        sa.CheckConstraint('book_value_after >= 0', name='ck_asset_deprec_entries_book_value'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['posted_by_id'], ['users.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_asset_deprec_entries_company_period', 'asset_depreciation_entries', ['company_id', 'period'])
    op.create_index('ix_asset_deprec_entries_asset_period', 'asset_depreciation_entries', ['company_id', 'asset_id', 'period'])

    # 3. asset_disposals
    op.create_table(
        'asset_disposals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('disposal_date', sa.Date(), nullable=False),
        sa.Column('disposal_reason', sa.String(32), nullable=False),
        sa.Column('disposal_method', sa.String(32), nullable=False),
        sa.Column('sale_proceeds', sa.Numeric(14, 2), nullable=False, server_default='0.00'),
        sa.Column('net_book_value_at_disposal', sa.Numeric(14, 2), nullable=False),
        sa.Column('gain_loss', sa.Numeric(14, 2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('disposed_by_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_asset_disposals_company_id_id'),
        sa.UniqueConstraint('company_id', 'asset_id', name='uq_asset_disposals_company_asset'),
        sa.CheckConstraint("disposal_reason IN ('sale', 'scrap', 'lost', 'damaged', 'obsolete', 'donated', 'trade_in', 'other')", name='ck_asset_disposals_reason'),
        sa.CheckConstraint("disposal_method IN ('auction', 'direct_sale', 'certified_destruction', 'recycled', 'trade_in', 'written_off', 'other')", name='ck_asset_disposals_method'),
        sa.CheckConstraint('sale_proceeds >= 0', name='ck_asset_disposals_proceeds'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['disposed_by_id'], ['users.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_asset_disposals_company_date', 'asset_disposals', ['company_id', 'disposal_date'])

    # 4. Seed Permissions
    conn = op.get_bind()
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
    role_permissions = sa.table(
        'role_permissions',
        sa.column('role_id', sa.Uuid()),
        sa.column('permission_id', sa.Uuid()),
    )

    new_permissions = [
        ('finance.read', 'Read company asset financial records, depreciation, and disposal reports'),
        ('finance.manage', 'Manage company asset financial profiles, depreciation entries, and disposals'),
    ]

    for code, description in new_permissions:
        exists = conn.execute(
            sa.select(permissions_table.c.id).where(permissions_table.c.code == code)
        ).scalar()
        if not exists:
            perm_id = uuid4()
            conn.execute(
                permissions_table.insert().values(
                    id=perm_id,
                    code=code,
                    description=description,
                )
            )

    perm_cache = {
        row[0]: row[1]
        for row in conn.execute(sa.select(permissions_table.c.code, permissions_table.c.id)).all()
    }
    role_cache = {
        (row[0], row[1]): row[2]
        for row in conn.execute(sa.select(roles_table.c.scope, roles_table.c.code, roles_table.c.id)).all()
    }

    target_assignments = [
        (('system', 'system_administrator'), 'finance.read'),
        (('system', 'system_administrator'), 'finance.manage'),
        (('company', 'company_administrator'), 'finance.read'),
        (('company', 'company_administrator'), 'finance.manage'),
        (('company', 'asset_manager'), 'finance.read'),
        (('company', 'asset_manager'), 'finance.manage'),
        (('company', 'auditor'), 'finance.read'),
        (('company', 'read_only_user'), 'finance.read'),
    ]

    for role_key, perm_code in target_assignments:
        role_id = role_cache.get(role_key)
        perm_id = perm_cache.get(perm_code)
        if role_id and perm_id:
            already = conn.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == perm_id,
                )
            ).scalar()
            if not already:
                conn.execute(
                    role_permissions.insert().values(
                        role_id=role_id,
                        permission_id=perm_id,
                    )
                )


def downgrade() -> None:
    conn = op.get_bind()
    permissions_table = sa.table('permissions', sa.column('id', sa.Uuid()), sa.column('code', sa.String()))
    role_permissions = sa.table('role_permissions', sa.column('permission_id', sa.Uuid()))

    perm_ids = [
        row[0] for row in conn.execute(
            sa.select(permissions_table.c.id).where(
                permissions_table.c.code.in_(['finance.read', 'finance.manage'])
            )
        ).all()
    ]
    if perm_ids:
        conn.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(perm_ids)))
        conn.execute(permissions_table.delete().where(permissions_table.c.id.in_(perm_ids)))

    op.drop_index('ix_asset_disposals_company_date', table_name='asset_disposals')
    op.drop_table('asset_disposals')

    op.drop_index('ix_asset_deprec_entries_asset_period', table_name='asset_depreciation_entries')
    op.drop_index('ix_asset_deprec_entries_company_period', table_name='asset_depreciation_entries')
    op.drop_table('asset_depreciation_entries')

    op.drop_index('ix_asset_financials_company_asset', table_name='asset_financials')
    op.drop_index('ix_asset_financials_company_status', table_name='asset_financials')
    op.drop_table('asset_financials')

