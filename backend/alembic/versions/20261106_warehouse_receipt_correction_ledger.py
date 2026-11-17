"""Warehouse receipt correction immutable ledger table and triggers

Revision ID: 20261106_wr_correction_ledger
Revises: 20261106_goods_return_to_vendor
Create Date: 2026-11-06 22:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '20261106_wr_correction_ledger'
down_revision = '20261106_goods_return_to_vendor'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.create_table(
        'goods_return_warehouse_receipt_corrections',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('company_id', sa.Uuid(), sa.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('goods_return_id', sa.Uuid(), nullable=False),
        sa.Column('warehouse_receipt_id', sa.Uuid(), nullable=False),
        sa.Column('warehouse_receipt_line_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('correction_reason', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('corrected_by_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('corrected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('previous_asset_status', sa.String(length=32), nullable=False),
        sa.Column('resulting_asset_status', sa.String(length=32), nullable=False),
        sa.Column('previous_reservation_state', sa.String(length=64), nullable=False),
        sa.Column('reservation_outcome', sa.String(length=64), nullable=False),
        sa.Column('new_reservation_id', sa.Uuid(), nullable=True),
        sa.UniqueConstraint('company_id', 'id', name='uq_gr_wr_corrections_company_id_id'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_return_id'],
            ['goods_returns.company_id', 'goods_returns.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_corr_return',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'warehouse_receipt_id'],
            ['goods_return_warehouse_receipts.company_id', 'goods_return_warehouse_receipts.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_corr_receipt',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'warehouse_receipt_line_id'],
            ['goods_return_warehouse_receipt_lines.company_id', 'goods_return_warehouse_receipt_lines.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_corr_line',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_corr_asset',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'new_reservation_id'],
            ['goods_return_asset_reservations.company_id', 'goods_return_asset_reservations.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_corr_new_reservation',
        ),
    )

    op.create_index('ix_gr_wr_corr_company_id', 'goods_return_warehouse_receipt_corrections', ['company_id'])
    op.create_index('ix_gr_wr_corr_receipt', 'goods_return_warehouse_receipt_corrections', ['warehouse_receipt_id'])
    op.create_index('ix_gr_wr_corr_line', 'goods_return_warehouse_receipt_corrections', ['warehouse_receipt_line_id'])
    op.create_index('ix_gr_wr_corr_asset', 'goods_return_warehouse_receipt_corrections', ['company_id', 'asset_id'])

    if dialect == 'postgresql':
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trg_fn_prevent_wr_correction_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Warehouse receipt correction records are append-only and strictly immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_no_update_delete_gr_wr_correction
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipt_corrections
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_wr_correction_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr_correction ON goods_return_warehouse_receipt_corrections;")
        op.execute("DROP FUNCTION IF EXISTS trg_fn_prevent_wr_correction_mutation();")

    op.drop_table('goods_return_warehouse_receipt_corrections')

