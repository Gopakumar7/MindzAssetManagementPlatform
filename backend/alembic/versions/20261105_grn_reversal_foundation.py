"""Goods receipt reversal foundation transaction model and lifecycle status

Revision ID: 20261105_grn_reversal_foundation
Revises: 20261104_po_cancellation
Create Date: 2026-11-05 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '20261105_grn_reversal_foundation'
down_revision = '20261104_po_cancellation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. goods_receipts: add status column, index and check constraint
    if dialect == 'sqlite':
        with op.batch_alter_table('goods_receipts') as batch_op:
            batch_op.add_column(
                sa.Column('status', sa.String(length=24), nullable=False, server_default='completed')
            )
            batch_op.create_check_constraint(
                'ck_goods_receipts_status',
                "status IN ('completed', 'partially_reversed', 'reversed')",
            )
            batch_op.create_index('ix_goods_receipts_company_status', ['company_id', 'status'])
    else:
        op.add_column(
            'goods_receipts',
            sa.Column('status', sa.String(length=24), nullable=False, server_default='completed'),
        )
        op.create_check_constraint(
            'ck_goods_receipts_status',
            'goods_receipts',
            "status IN ('completed', 'partially_reversed', 'reversed')",
        )
        op.create_index('ix_goods_receipts_company_status', 'goods_receipts', ['company_id', 'status'])

    # 2. goods_receipt_lines: add quantity_reversed, check constraint and unique constraint
    if dialect == 'sqlite':
        with op.batch_alter_table('goods_receipt_lines') as batch_op:
            batch_op.add_column(
                sa.Column('quantity_reversed', sa.Integer(), nullable=False, server_default='0')
            )
            batch_op.create_check_constraint(
                'ck_goods_receipt_lines_reversed',
                'quantity_reversed >= 0 AND quantity_reversed <= (quantity_received - quantity_rejected)',
            )
            batch_op.create_unique_constraint(
                'uq_goods_receipt_lines_company_id_receipt',
                ['company_id', 'id', 'goods_receipt_id'],
            )
    else:
        op.add_column(
            'goods_receipt_lines',
            sa.Column('quantity_reversed', sa.Integer(), nullable=False, server_default='0'),
        )
        op.create_check_constraint(
            'ck_goods_receipt_lines_reversed',
            'goods_receipt_lines',
            'quantity_reversed >= 0 AND quantity_reversed <= (quantity_received - quantity_rejected)',
        )
        op.create_unique_constraint(
            'uq_goods_receipt_lines_company_id_receipt',
            'goods_receipt_lines',
            ['company_id', 'id', 'goods_receipt_id'],
        )

    # 3. goods_receipt_reversals table
    op.create_table(
        'goods_receipt_reversals',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('purchase_order_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reversal_reference', sa.String(length=80), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('reversed_by_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_id', 'purchase_order_id'],
            ['goods_receipts.company_id', 'goods_receipts.id', 'goods_receipts.purchase_order_id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversals_receipt',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'purchase_order_id'],
            ['purchase_orders.company_id', 'purchase_orders.id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversals_order',
        ),
        sa.ForeignKeyConstraint(['reversed_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_receipt_reversals_user'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_receipt_reversals_company_id'),
    )
    op.create_index('ix_goods_receipt_reversals_company_id', 'goods_receipt_reversals', ['company_id'])
    op.create_index('ix_goods_receipt_reversals_goods_receipt_id', 'goods_receipt_reversals', ['goods_receipt_id'])
    op.create_index('ix_goods_receipt_reversals_purchase_order_id', 'goods_receipt_reversals', ['purchase_order_id'])
    op.create_index('ix_goods_receipt_reversals_company_receipt', 'goods_receipt_reversals', ['company_id', 'goods_receipt_id'])
    op.create_index('ix_goods_receipt_reversals_company_order', 'goods_receipt_reversals', ['company_id', 'purchase_order_id'])

    # 4. goods_receipt_reversal_lines table
    op.create_table(
        'goods_receipt_reversal_lines',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reversal_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('purchase_order_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('quantity_reversed', sa.Integer(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['reversal_id'], ['goods_receipt_reversals.id'], ondelete='CASCADE', name='fk_goods_receipt_reversal_lines_rev'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_line_id'],
            ['goods_receipt_lines.company_id', 'goods_receipt_lines.id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversal_lines_receipt_line',
        ),
        sa.ForeignKeyConstraint(
            ['purchase_order_line_id'],
            ['purchase_order_lines.id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversal_lines_order_line',
        ),
        sa.CheckConstraint('quantity_reversed > 0', name='ck_goods_receipt_reversal_lines_qty_gt_zero'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_receipt_reversal_lines_company_id'),
        sa.UniqueConstraint('company_id', 'id', 'goods_receipt_line_id', name='uq_goods_receipt_reversal_lines_company_id_line'),
    )
    op.create_index('ix_goods_receipt_reversal_lines_company_id', 'goods_receipt_reversal_lines', ['company_id'])
    op.create_index('ix_goods_receipt_reversal_lines_goods_receipt_line_id', 'goods_receipt_reversal_lines', ['goods_receipt_line_id'])
    op.create_index('ix_goods_receipt_reversal_lines_purchase_order_line_id', 'goods_receipt_reversal_lines', ['purchase_order_line_id'])
    op.create_index('ix_goods_receipt_reversal_lines_reversal_id', 'goods_receipt_reversal_lines', ['reversal_id'])
    op.create_index('ix_goods_receipt_reversal_lines_rev', 'goods_receipt_reversal_lines', ['reversal_id'])
    op.create_index('ix_goods_receipt_reversal_lines_grl', 'goods_receipt_reversal_lines', ['goods_receipt_line_id'])

    # 5. goods_receipt_reversal_assets table
    op.create_table(
        'goods_receipt_reversal_assets',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reversal_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reversal_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('asset_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('asset_number', sa.String(length=80), nullable=False),
        sa.Column('serial_number', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['reversal_id'], ['goods_receipt_reversals.id'], ondelete='CASCADE', name='fk_goods_receipt_reversal_assets_rev'),
        sa.ForeignKeyConstraint(
            ['company_id', 'reversal_line_id', 'goods_receipt_line_id'],
            ['goods_receipt_reversal_lines.company_id', 'goods_receipt_reversal_lines.id', 'goods_receipt_reversal_lines.goods_receipt_line_id'],
            ondelete='CASCADE',
            name='fk_goods_receipt_reversal_assets_rev_line',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_line_id'],
            ['goods_receipt_lines.company_id', 'goods_receipt_lines.id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversal_assets_receipt_line',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
            name='fk_goods_receipt_reversal_assets_asset',
        ),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_receipt_reversal_assets_company_id'),
        sa.UniqueConstraint('company_id', 'asset_id', name='uq_goods_receipt_reversal_assets_company_asset'),
    )
    op.create_index('ix_goods_receipt_reversal_assets_company_id', 'goods_receipt_reversal_assets', ['company_id'])
    op.create_index('ix_goods_receipt_reversal_assets_reversal_id', 'goods_receipt_reversal_assets', ['reversal_id'])
    op.create_index('ix_goods_receipt_reversal_assets_reversal_line_id', 'goods_receipt_reversal_assets', ['reversal_line_id'])
    op.create_index('ix_goods_receipt_reversal_assets_goods_receipt_line_id', 'goods_receipt_reversal_assets', ['goods_receipt_line_id'])
    op.create_index('ix_goods_receipt_reversal_assets_asset_id', 'goods_receipt_reversal_assets', ['asset_id'])
    op.create_index('ix_goods_receipt_reversal_assets_rev_line', 'goods_receipt_reversal_assets', ['reversal_line_id'])
    op.create_index('ix_goods_receipt_reversal_assets_asset', 'goods_receipt_reversal_assets', ['company_id', 'asset_id'])


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.drop_table('goods_receipt_reversal_assets')
    op.drop_table('goods_receipt_reversal_lines')
    op.drop_table('goods_receipt_reversals')

    if dialect == 'sqlite':
        with op.batch_alter_table('goods_receipt_lines') as batch_op:
            batch_op.drop_constraint('uq_goods_receipt_lines_company_id_receipt', type_='unique')
            batch_op.drop_constraint('ck_goods_receipt_lines_reversed', type_='check')
            batch_op.drop_column('quantity_reversed')
        with op.batch_alter_table('goods_receipts') as batch_op:
            batch_op.drop_index('ix_goods_receipts_company_status')
            batch_op.drop_constraint('ck_goods_receipts_status', type_='check')
            batch_op.drop_column('status')
    else:
        op.drop_constraint('uq_goods_receipt_lines_company_id_receipt', 'goods_receipt_lines', type_='unique')
        op.drop_constraint('ck_goods_receipt_lines_reversed', 'goods_receipt_lines', type_='check')
        op.drop_column('goods_receipt_lines', 'quantity_reversed')
        op.drop_index('ix_goods_receipts_company_status', table_name='goods_receipts')
        op.drop_constraint('ck_goods_receipts_status', 'goods_receipts', type_='check')
        op.drop_column('goods_receipts', 'status')
