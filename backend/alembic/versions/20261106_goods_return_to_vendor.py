"""Goods return to vendor (GRR) models, lineage constraints, reservations, and warehouse receipts

Revision ID: 20261106_goods_return_to_vendor
Revises: 20261105_grn_reversal_foundation
Create Date: 2026-11-06 17:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


revision = '20261106_goods_return_to_vendor'
down_revision = '20261105_grn_reversal_foundation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 0. Add settings column to companies
    op.add_column('companies', sa.Column('settings', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    # 1. Prerequisite composite unique constraints on existing parent tables
    if dialect == 'sqlite':
        with op.batch_alter_table('goods_receipt_reversals') as batch_op:
            batch_op.create_unique_constraint(
                'uq_goods_receipt_reversals_lineage',
                ['company_id', 'id', 'goods_receipt_id', 'purchase_order_id'],
            )
        with op.batch_alter_table('purchase_orders') as batch_op:
            batch_op.create_unique_constraint(
                'uq_purchase_orders_company_id_supplier',
                ['company_id', 'id', 'supplier_id'],
            )
        with op.batch_alter_table('goods_receipt_reversal_assets') as batch_op:
            batch_op.create_unique_constraint(
                'uq_goods_receipt_reversal_assets_lineage',
                ['company_id', 'id', 'reversal_id', 'reversal_line_id', 'goods_receipt_line_id', 'asset_id'],
            )
    else:
        op.create_unique_constraint(
            'uq_goods_receipt_reversals_lineage',
            'goods_receipt_reversals',
            ['company_id', 'id', 'goods_receipt_id', 'purchase_order_id'],
        )
        op.create_unique_constraint(
            'uq_purchase_orders_company_id_supplier',
            'purchase_orders',
            ['company_id', 'id', 'supplier_id'],
        )
        op.create_unique_constraint(
            'uq_goods_receipt_reversal_assets_lineage',
            'goods_receipt_reversal_assets',
            ['company_id', 'id', 'reversal_id', 'reversal_line_id', 'goods_receipt_line_id', 'asset_id'],
        )

    # 2. goods_returns table
    op.create_table(
        'goods_returns',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('return_number', sa.String(length=64), nullable=False),
        sa.Column('supplier_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('purchase_order_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('original_goods_receipt_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_reversal_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('return_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('return_reason', sa.Text(), nullable=False),
        sa.Column('vendor_reference', sa.String(length=128), nullable=True),
        sa.Column('dispatch_reference', sa.String(length=128), nullable=True),
        sa.Column('transport_details', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('policy_strict_approval_applied', sa.Boolean(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('approved_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dispatched_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT', name='fk_goods_returns_company'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_reversal_id', 'original_goods_receipt_id', 'purchase_order_id'],
            ['goods_receipt_reversals.company_id', 'goods_receipt_reversals.id', 'goods_receipt_reversals.goods_receipt_id', 'goods_receipt_reversals.purchase_order_id'],
            ondelete='RESTRICT',
            name='fk_goods_returns_reversal_lineage',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'purchase_order_id', 'supplier_id'],
            ['purchase_orders.company_id', 'purchase_orders.id', 'purchase_orders.supplier_id'],
            ondelete='RESTRICT',
            name='fk_goods_returns_po_supplier_lineage',
        ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_returns_created_by'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_returns_approved_by'),
        sa.ForeignKeyConstraint(['dispatched_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_returns_dispatched_by'),
        sa.ForeignKeyConstraint(['completed_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_returns_completed_by'),
        sa.ForeignKeyConstraint(['cancelled_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_goods_returns_cancelled_by'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_returns_company_id_id'),
        sa.UniqueConstraint('company_id', 'return_number', name='uq_goods_returns_company_number'),
        sa.UniqueConstraint('company_id', 'id', 'goods_receipt_reversal_id', name='uq_goods_returns_lineage'),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'dispatched', 'partially_returned_to_warehouse', 'returned_to_warehouse', 'completed', 'cancelled')",
            name='ck_goods_returns_status',
        ),
    )
    op.create_index('ix_goods_returns_company_id', 'goods_returns', ['company_id'])
    op.create_index('ix_goods_returns_company_status', 'goods_returns', ['company_id', 'status'])
    op.create_index('ix_goods_returns_company_reversal', 'goods_returns', ['company_id', 'goods_receipt_reversal_id'])

    # 3. goods_return_lines table
    op.create_table(
        'goods_return_lines',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_return_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_reversal_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_reversal_asset_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_reversal_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_receipt_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('asset_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('return_condition', sa.String(length=64), nullable=False, server_default='as_received'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT', name='fk_goods_return_lines_company'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_return_id', 'goods_receipt_reversal_id'],
            ['goods_returns.company_id', 'goods_returns.id', 'goods_returns.goods_receipt_reversal_id'],
            ondelete='RESTRICT',
            name='fk_goods_return_lines_grr_lineage',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_receipt_reversal_asset_id', 'goods_receipt_reversal_id', 'goods_receipt_reversal_line_id', 'goods_receipt_line_id', 'asset_id'],
            ['goods_receipt_reversal_assets.company_id', 'goods_receipt_reversal_assets.id', 'goods_receipt_reversal_assets.reversal_id', 'goods_receipt_reversal_assets.reversal_line_id', 'goods_receipt_reversal_assets.goods_receipt_line_id', 'goods_receipt_reversal_assets.asset_id'],
            ondelete='RESTRICT',
            name='fk_goods_return_lines_reversal_asset_lineage',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
            name='fk_goods_return_lines_asset',
        ),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_return_lines_company_id_id'),
        sa.UniqueConstraint('company_id', 'id', 'goods_return_id', 'asset_id', name='uq_goods_return_lines_receipt_lineage'),
    )
    op.create_index('ix_goods_return_lines_company_id', 'goods_return_lines', ['company_id'])
    op.create_index('ix_goods_return_lines_return', 'goods_return_lines', ['goods_return_id'])
    op.create_index('ix_goods_return_lines_asset', 'goods_return_lines', ['company_id', 'asset_id'])

    # 4. goods_return_asset_reservations table
    op.create_table(
        'goods_return_asset_reservations',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('asset_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_return_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('reserved_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('release_reason', sa.String(length=32), nullable=True),
        sa.Column('released_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT', name='fk_gr_reservations_company'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_return_id'],
            ['goods_returns.company_id', 'goods_returns.id'],
            ondelete='RESTRICT',
            name='fk_gr_reservations_return',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
            name='fk_gr_reservations_asset',
        ),
        sa.ForeignKeyConstraint(['released_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_gr_reservations_released_by'),
        sa.UniqueConstraint('company_id', 'id', name='uq_goods_return_asset_reservations_company_id'),
        sa.CheckConstraint(
            "((released_at IS NULL) AND (release_reason IS NULL) AND (released_by_id IS NULL)) OR "
            "((released_at IS NOT NULL) AND (release_reason IS NOT NULL) AND (released_by_id IS NOT NULL))",
            name='ck_gr_reservations_release_state',
        ),
        sa.CheckConstraint(
            "(release_reason IS NULL) OR (release_reason IN ('cancelled', 'deselected', 'returned_to_warehouse', 'fulfilled'))",
            name='ck_gr_reservations_release_reason',
        ),
        sa.CheckConstraint(
            "(released_at IS NULL) OR (released_at >= reserved_at)",
            name='ck_gr_reservations_chronology',
        ),
    )
    op.create_index(
        'uq_gr_asset_active_reservation',
        'goods_return_asset_reservations',
        ['company_id', 'asset_id'],
        unique=True,
        postgresql_where=text('released_at IS NULL'),
        sqlite_where=text('released_at IS NULL'),
    )
    op.create_index('ix_gr_reservations_company_id', 'goods_return_asset_reservations', ['company_id'])
    op.create_index('ix_gr_reservations_return', 'goods_return_asset_reservations', ['goods_return_id'])
    op.create_index('ix_gr_reservations_active', 'goods_return_asset_reservations', ['company_id', 'asset_id', 'released_at'])

    # 5. goods_return_warehouse_receipts table
    op.create_table(
        'goods_return_warehouse_receipts',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_return_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('receipt_number', sa.String(length=64), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('received_by_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('warehouse_location_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('dispatch_reference', sa.String(length=160), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT', name='fk_gr_wr_company'),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_return_id'],
            ['goods_returns.company_id', 'goods_returns.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_return',
        ),
        sa.ForeignKeyConstraint(['received_by_id'], ['users.id'], ondelete='RESTRICT', name='fk_gr_wr_received_by'),
        sa.UniqueConstraint('company_id', 'id', name='uq_gr_wr_company_id_id'),
        sa.UniqueConstraint('company_id', 'receipt_number', name='uq_gr_wr_company_number'),
        sa.UniqueConstraint('company_id', 'id', 'goods_return_id', name='uq_gr_wr_lineage'),
    )
    op.create_index('ix_gr_wr_company_id', 'goods_return_warehouse_receipts', ['company_id'])
    op.create_index('ix_gr_wr_company_return', 'goods_return_warehouse_receipts', ['company_id', 'goods_return_id'])
    op.create_index('ix_gr_wr_company_date', 'goods_return_warehouse_receipts', ['company_id', 'receipt_date'])

    # 6. goods_return_warehouse_receipt_lines table
    op.create_table(
        'goods_return_warehouse_receipt_lines',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('company_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('warehouse_receipt_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_return_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('goods_return_line_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('asset_id', sa.Uuid(as_uuid=True), nullable=False),
        sa.Column('condition_on_return', sa.String(length=64), nullable=False, server_default='intact'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_corrected', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('correction_reason', sa.Text(), nullable=True),
        sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('corrected_by_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT', name='fk_gr_wr_lines_company'),
        sa.ForeignKeyConstraint(
            ['company_id', 'warehouse_receipt_id', 'goods_return_id'],
            ['goods_return_warehouse_receipts.company_id', 'goods_return_warehouse_receipts.id', 'goods_return_warehouse_receipts.goods_return_id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_lines_receipt_lineage',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'goods_return_line_id', 'goods_return_id', 'asset_id'],
            ['goods_return_lines.company_id', 'goods_return_lines.id', 'goods_return_lines.goods_return_id', 'goods_return_lines.asset_id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_lines_return_line_lineage',
        ),
        sa.ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
            name='fk_gr_wr_lines_asset',
        ),
        sa.UniqueConstraint('company_id', 'id', name='uq_gr_wr_lines_company_id_id'),
    )
    op.create_index(
        'uq_gr_wr_lines_return_line',
        'goods_return_warehouse_receipt_lines',
        ['company_id', 'goods_return_line_id'],
        unique=True,
        postgresql_where=text('is_corrected IS FALSE'),
        sqlite_where=text('is_corrected = 0'),
    )
    op.create_index('ix_gr_wr_lines_company_id', 'goods_return_warehouse_receipt_lines', ['company_id'])
    op.create_index('ix_gr_wr_lines_receipt', 'goods_return_warehouse_receipt_lines', ['warehouse_receipt_id'])
    op.create_index('ix_gr_wr_lines_asset', 'goods_return_warehouse_receipt_lines', ['company_id', 'asset_id'])

    # 7. PostgreSQL Immutability Triggers
    if dialect == 'postgresql':
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trg_fn_prevent_warehouse_receipt_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                IF (TG_OP = 'DELETE') THEN
                    RAISE EXCEPTION 'Warehouse receipt event records are immutable ledger entries and cannot be deleted.';
                ELSIF (TG_OP = 'UPDATE') THEN
                    IF (TG_TABLE_NAME = 'goods_return_warehouse_receipts') THEN
                        RAISE EXCEPTION 'Warehouse receipt event headers are immutable ledger entries and cannot be modified.';
                    ELSIF (TG_TABLE_NAME = 'goods_return_warehouse_receipt_lines') THEN
                        IF (OLD.warehouse_receipt_id != NEW.warehouse_receipt_id OR
                            OLD.goods_return_id != NEW.goods_return_id OR
                            OLD.goods_return_line_id != NEW.goods_return_line_id OR
                            OLD.asset_id != NEW.asset_id OR
                            OLD.condition_on_return != NEW.condition_on_return) THEN
                            RAISE EXCEPTION 'Core warehouse receipt line attributes are immutable and cannot be modified.';
                        END IF;
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_no_update_delete_gr_wr
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipts
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_warehouse_receipt_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_no_update_delete_gr_wr_lines
            BEFORE UPDATE OR DELETE ON goods_return_warehouse_receipt_lines
            FOR EACH ROW EXECUTE FUNCTION trg_fn_prevent_warehouse_receipt_mutation();
            """
        )

    # 8. Provision reference sequences for goods_return across existing active companies
    existing_seqs = bind.execute(sa.text("""
        SELECT DISTINCT company_id, 
               CASE 
                   WHEN position('-' in prefix) > 0 THEN substring(prefix from 1 for position('-' in prefix) - 1)
                   ELSE 'MZ'
               END as prefix_base
        FROM reference_sequences
        WHERE entity_type IN ('goods_receipt', 'purchase_order')
    """ if dialect == 'postgresql' else """
        SELECT DISTINCT company_id,
               CASE 
                   WHEN instr(prefix, '-') > 0 THEN substr(prefix, 1, instr(prefix, '-') - 1)
                   ELSE 'MZ'
               END as prefix_base
        FROM reference_sequences
        WHERE entity_type IN ('goods_receipt', 'purchase_order')
    """)).fetchall()

    for row in existing_seqs:
        cid = row[0]
        pfx_base = row[1] or 'MZ'
        pfx = f"{pfx_base}-GRR"
        if dialect == 'postgresql':
            bind.execute(sa.text("""
                INSERT INTO reference_sequences (
                    id, company_id, entity_type, fiscal_year, prefix, separator, padding, current_value, is_active, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(),
                    :company_id,
                    'goods_return',
                    CASE 
                        WHEN EXTRACT(MONTH FROM CURRENT_DATE) >= 4 
                        THEN TO_CHAR(EXTRACT(YEAR FROM CURRENT_DATE) % 100, 'FM00') || TO_CHAR((EXTRACT(YEAR FROM CURRENT_DATE) + 1) % 100, 'FM00')
                        ELSE TO_CHAR((EXTRACT(YEAR FROM CURRENT_DATE) - 1) % 100, 'FM00') || TO_CHAR(EXTRACT(YEAR FROM CURRENT_DATE) % 100, 'FM00')
                    END,
                    :prefix,
                    '-',
                    5,
                    0,
                    true,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (company_id, entity_type, fiscal_year) DO NOTHING
            """), {'company_id': cid, 'prefix': pfx})
        else:
            bind.execute(sa.text("""
                INSERT INTO reference_sequences (
                    id, company_id, entity_type, fiscal_year, prefix, separator, padding, current_value, is_active, created_at, updated_at
                )
                VALUES (
                    lower(hex(randomblob(16))),
                    :company_id,
                    'goods_return',
                    '2627',
                    :prefix,
                    '-',
                    5,
                    0,
                    1,
                    datetime('now'),
                    datetime('now')
                )
                ON CONFLICT (company_id, entity_type, fiscal_year) DO NOTHING
            """), {'company_id': cid, 'prefix': pfx})


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr_lines ON goods_return_warehouse_receipt_lines;")
        op.execute("DROP TRIGGER IF EXISTS trg_no_update_delete_gr_wr ON goods_return_warehouse_receipts;")
        op.execute("DROP FUNCTION IF EXISTS trg_fn_prevent_warehouse_receipt_mutation();")

    op.execute("DELETE FROM reference_sequences WHERE entity_type = 'goods_return';")

    op.drop_table('goods_return_warehouse_receipt_lines')
    op.drop_table('goods_return_warehouse_receipts')
    op.drop_table('goods_return_asset_reservations')
    op.drop_table('goods_return_lines')
    op.drop_table('goods_returns')

    if dialect == 'sqlite':
        with op.batch_alter_table('goods_receipt_reversal_assets') as batch_op:
            batch_op.drop_constraint('uq_goods_receipt_reversal_assets_lineage', type_='unique')
        with op.batch_alter_table('purchase_orders') as batch_op:
            batch_op.drop_constraint('uq_purchase_orders_company_id_supplier', type_='unique')
        with op.batch_alter_table('goods_receipt_reversals') as batch_op:
            batch_op.drop_constraint('uq_goods_receipt_reversals_lineage', type_='unique')
    else:
        op.drop_constraint('uq_goods_receipt_reversal_assets_lineage', 'goods_receipt_reversal_assets', type_='unique')
        op.drop_constraint('uq_purchase_orders_company_id_supplier', 'purchase_orders', type_='unique')
        op.drop_constraint('uq_goods_receipt_reversals_lineage', 'goods_receipt_reversals', type_='unique')

    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS settings;")
