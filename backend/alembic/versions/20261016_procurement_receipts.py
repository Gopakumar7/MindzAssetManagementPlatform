"""add company-scoped procurement and goods receipt traceability

Revision ID: 20261016_procurement
Revises: 20261015_assignment
Create Date: 2026-10-16 00:00:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261016_procurement'
down_revision = '20261015_assignment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'suppliers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('email', sa.String(320), nullable=True),
        sa.Column('phone', sa.String(64), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_suppliers_company_id_id'),
        sa.UniqueConstraint('company_id', 'code', name='uq_suppliers_company_code'),
    )
    op.create_index(op.f('ix_suppliers_company_id'), 'suppliers', ['company_id'])
    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('supplier_id', sa.Uuid(), nullable=False),
        sa.Column('order_number', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('ordered_date', sa.Date(), nullable=False),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'partially_received', 'received')", name='ck_purchase_orders_status'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'supplier_id'], ['suppliers.company_id', 'suppliers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_purchase_orders_company_id_id'),
        sa.UniqueConstraint('company_id', 'order_number', name='uq_purchase_orders_company_number'),
    )
    op.create_index(op.f('ix_purchase_orders_company_id'), 'purchase_orders', ['company_id'])
    op.create_index(op.f('ix_purchase_orders_supplier_id'), 'purchase_orders', ['supplier_id'])
    op.create_table(
        'purchase_order_lines',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('purchase_order_id', sa.Uuid(), nullable=False),
        sa.Column('category_id', sa.Uuid(), nullable=False),
        sa.Column('description', sa.String(300), nullable=False),
        sa.Column('quantity_ordered', sa.Integer(), nullable=False),
        sa.Column('unit_cost', sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint('quantity_ordered > 0', name='ck_purchase_order_lines_quantity'),
        sa.CheckConstraint('unit_cost >= 0', name='ck_purchase_order_lines_unit_cost'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'purchase_order_id'], ['purchase_orders.company_id', 'purchase_orders.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'category_id'], ['asset_categories.company_id', 'asset_categories.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'purchase_order_id', 'id', name='uq_purchase_order_lines_company_order_id'),
    )
    op.create_index(op.f('ix_purchase_order_lines_company_id'), 'purchase_order_lines', ['company_id'])
    op.create_index(op.f('ix_purchase_order_lines_purchase_order_id'), 'purchase_order_lines', ['purchase_order_id'])
    op.create_index(op.f('ix_purchase_order_lines_category_id'), 'purchase_order_lines', ['category_id'])
    op.create_table(
        'goods_receipts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('purchase_order_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_number', sa.String(64), nullable=False),
        sa.Column('received_date', sa.Date(), nullable=False),
        sa.Column('delivery_reference', sa.String(160), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'purchase_order_id'], ['purchase_orders.company_id', 'purchase_orders.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_receipts_company_id_id'),
        sa.UniqueConstraint('company_id', 'id', 'purchase_order_id', name='uq_goods_receipts_company_id_order'),
        sa.UniqueConstraint('company_id', 'receipt_number', name='uq_goods_receipts_company_number'),
    )
    op.create_index(op.f('ix_goods_receipts_company_id'), 'goods_receipts', ['company_id'])
    op.create_index(op.f('ix_goods_receipts_purchase_order_id'), 'goods_receipts', ['purchase_order_id'])
    op.create_table(
        'goods_receipt_lines',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('goods_receipt_id', sa.Uuid(), nullable=False),
        sa.Column('purchase_order_id', sa.Uuid(), nullable=False),
        sa.Column('purchase_order_line_id', sa.Uuid(), nullable=False),
        sa.Column('quantity_received', sa.Integer(), nullable=False),
        sa.Column('quantity_rejected', sa.Integer(), nullable=False),
        sa.Column('discrepancy_notes', sa.Text(), nullable=True),
        sa.CheckConstraint('quantity_received > 0', name='ck_goods_receipt_lines_received'),
        sa.CheckConstraint('quantity_rejected >= 0 AND quantity_rejected <= quantity_received', name='ck_goods_receipt_lines_rejected'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_id', 'purchase_order_id'],
            ['goods_receipts.company_id', 'goods_receipts.id', 'goods_receipts.purchase_order_id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'purchase_order_id', 'purchase_order_line_id'],
            ['purchase_order_lines.company_id', 'purchase_order_lines.purchase_order_id', 'purchase_order_lines.id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_receipt_lines_company_id_id'),
        sa.UniqueConstraint('company_id', 'goods_receipt_id', 'purchase_order_line_id', name='uq_goods_receipt_lines_receipt_order_line'),
    )
    op.create_index(op.f('ix_goods_receipt_lines_company_id'), 'goods_receipt_lines', ['company_id'])
    op.create_index(op.f('ix_goods_receipt_lines_goods_receipt_id'), 'goods_receipt_lines', ['goods_receipt_id'])
    op.create_index(op.f('ix_goods_receipt_lines_purchase_order_id'), 'goods_receipt_lines', ['purchase_order_id'])
    op.create_index(op.f('ix_goods_receipt_lines_purchase_order_line_id'), 'goods_receipt_lines', ['purchase_order_line_id'])
    op.add_column('assets', sa.Column('goods_receipt_line_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_assets_company_goods_receipt_line',
        'assets',
        'goods_receipt_lines',
        ['company_id', 'goods_receipt_line_id'],
        ['company_id', 'id'],
        ondelete='RESTRICT',
    )

    bind = op.get_bind()
    permission_ids = {}
    for code, description in (
        ('procurement.read', 'Read company suppliers, purchase orders, and goods receipts'),
        ('procurement.manage', 'Manage company suppliers, purchase orders, and goods receipts'),
    ):
        existing_id = bind.execute(
            sa.text('SELECT id FROM permissions WHERE code = :code'),
            {'code': code},
        ).scalar_one_or_none()
        permission_id = existing_id or uuid4()
        if existing_id is None:
            bind.execute(
                sa.text('INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description)'),
                {'id': permission_id, 'code': code, 'description': description},
            )
        permission_ids[code] = permission_id

    grants = {
        'system_administrator': ('procurement.read', 'procurement.manage'),
        'company_administrator': ('procurement.read', 'procurement.manage'),
        'asset_manager': ('procurement.read', 'procurement.manage'),
        'auditor': ('procurement.read',),
        'read_only_user': ('procurement.read',),
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
            permission_id = permission_ids[code]
            present = bind.execute(
                sa.text('SELECT 1 FROM role_permissions WHERE role_id = :role AND permission_id = :permission'),
                {'role': role_id, 'permission': permission_id},
            ).scalar_one_or_none()
            if present is None:
                bind.execute(
                    sa.text('INSERT INTO role_permissions (role_id, permission_id) VALUES (:role, :permission)'),
                    {'role': role_id, 'permission': permission_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    permission_ids = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code IN ('procurement.read', 'procurement.manage')")
    ).scalars().all()
    if permission_ids:
        for permission_id in permission_ids:
            bind.execute(
                sa.text('DELETE FROM role_permissions WHERE permission_id = :permission_id'),
                {'permission_id': permission_id},
            )
        bind.execute(sa.text("DELETE FROM permissions WHERE code IN ('procurement.read', 'procurement.manage')"))
    op.drop_constraint('fk_assets_company_goods_receipt_line', 'assets', type_='foreignkey')
    op.drop_column('assets', 'goods_receipt_line_id')
    for table in ('goods_receipt_lines', 'goods_receipts', 'purchase_order_lines', 'purchase_orders', 'suppliers'):
        op.drop_table(table)
