"""Purchase Order origin and external reference data model

Revision ID: 20261103_po_origin_ext
Revises: 20261102_ref_seq_audit_guard
Create Date: 2026-11-03 15:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = '20261103_po_origin_ext'
down_revision = '20261102_ref_seq_audit_guard'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add new columns to purchase_orders
    op.add_column('purchase_orders', sa.Column('origin', sa.String(length=16), nullable=True))
    op.add_column('purchase_orders', sa.Column('source_system', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('source_instance_id', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_reference', sa.String(length=64), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_system_id', sa.String(length=128), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_last_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('purchase_orders', sa.Column('external_payload_hash', sa.String(length=64), nullable=True))

    # 2. Add new columns to purchase_order_lines
    op.add_column('purchase_order_lines', sa.Column('external_line_id', sa.String(length=64), nullable=True))
    op.add_column('purchase_order_lines', sa.Column('line_number', sa.Integer(), nullable=True))

    # 3. Safe historical backfill: classify all existing POs as INTERNAL
    op.execute("UPDATE purchase_orders SET origin = 'INTERNAL' WHERE origin IS NULL")

    # 4. Enforce NOT NULL and server_default on origin
    op.alter_column(
        'purchase_orders',
        'origin',
        existing_type=sa.String(length=16),
        nullable=False,
        server_default='INTERNAL',
    )

    # 5. Check constraints on purchase_orders
    op.create_check_constraint(
        'ck_purchase_orders_origin',
        'purchase_orders',
        "origin IN ('INTERNAL', 'EXTERNAL')",
    )

    op.create_check_constraint(
        'ck_purchase_orders_origin_fields',
        'purchase_orders',
        "(origin = 'INTERNAL' AND source_system IS NULL AND source_instance_id IS NULL AND external_reference IS NULL AND external_system_id IS NULL AND external_last_synced_at IS NULL AND external_updated_at IS NULL AND external_payload_hash IS NULL) OR "
        "(origin = 'EXTERNAL' AND source_system IS NOT NULL AND source_instance_id IS NOT NULL AND external_reference IS NOT NULL)",
    )

    # 6. Check constraint on purchase_order_lines
    op.create_check_constraint(
        'ck_purchase_order_lines_line_number',
        'purchase_order_lines',
        'line_number IS NULL OR line_number > 0',
    )

    # 7. Partial unique indexes on purchase_orders
    op.create_index(
        'uq_purchase_orders_company_source_ext_id',
        'purchase_orders',
        ['company_id', 'source_system', 'source_instance_id', 'external_system_id'],
        unique=True,
        postgresql_where=sa.text("external_system_id IS NOT NULL"),
    )

    op.create_index(
        'uq_purchase_orders_company_source_ext_ref',
        'purchase_orders',
        ['company_id', 'source_system', 'source_instance_id', 'external_reference'],
        unique=True,
        postgresql_where=sa.text("external_system_id IS NULL AND external_reference IS NOT NULL"),
    )

    # 8. Index on purchase_order_lines for external line lookup
    op.create_index(
        'ix_purchase_order_lines_order_ext_line',
        'purchase_order_lines',
        ['purchase_order_id', 'external_line_id'],
        unique=False,
        postgresql_where=sa.text("external_line_id IS NOT NULL"),
    )


def downgrade() -> None:
    # 1. Drop indexes
    op.drop_index(
        'ix_purchase_order_lines_order_ext_line',
        table_name='purchase_order_lines',
        postgresql_where=sa.text("external_line_id IS NOT NULL"),
    )
    op.drop_index(
        'uq_purchase_orders_company_source_ext_ref',
        table_name='purchase_orders',
        postgresql_where=sa.text("external_system_id IS NULL AND external_reference IS NOT NULL"),
    )
    op.drop_index(
        'uq_purchase_orders_company_source_ext_id',
        table_name='purchase_orders',
        postgresql_where=sa.text("external_system_id IS NOT NULL"),
    )

    # 2. Drop check constraints
    op.drop_constraint('ck_purchase_order_lines_line_number', 'purchase_order_lines', type_='check')
    op.drop_constraint('ck_purchase_orders_origin_fields', 'purchase_orders', type_='check')
    op.drop_constraint('ck_purchase_orders_origin', 'purchase_orders', type_='check')

    # 3. Drop columns from purchase_order_lines
    op.drop_column('purchase_order_lines', 'line_number')
    op.drop_column('purchase_order_lines', 'external_line_id')

    # 4. Drop columns from purchase_orders
    op.drop_column('purchase_orders', 'external_payload_hash')
    op.drop_column('purchase_orders', 'external_updated_at')
    op.drop_column('purchase_orders', 'external_last_synced_at')
    op.drop_column('purchase_orders', 'external_system_id')
    op.drop_column('purchase_orders', 'external_reference')
    op.drop_column('purchase_orders', 'source_instance_id')
    op.drop_column('purchase_orders', 'source_system')
    op.drop_column('purchase_orders', 'origin')

