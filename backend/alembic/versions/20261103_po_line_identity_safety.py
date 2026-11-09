"""External PO line identity partial unique indexes and update safety

Revision ID: 20261103_po_line_id_safe
Revises: 20261103_po_origin_ext
Create Date: 2026-11-03 16:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = '20261103_po_line_id_safe'
down_revision = '20261103_po_origin_ext'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Inspect existing data for duplicates before introducing uniqueness constraint
    dup_ext = bind.execute(sa.text("""
        SELECT purchase_order_id, external_line_id, COUNT(*)
        FROM purchase_order_lines
        WHERE external_line_id IS NOT NULL
        GROUP BY purchase_order_id, external_line_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    if dup_ext:
        raise RuntimeError(f"Duplicate external_line_id found in purchase_order_lines: {dup_ext}")

    dup_line_num = bind.execute(sa.text("""
        SELECT purchase_order_id, line_number, COUNT(*)
        FROM purchase_order_lines
        WHERE line_number IS NOT NULL
        GROUP BY purchase_order_id, line_number
        HAVING COUNT(*) > 1
    """)).fetchall()
    if dup_line_num:
        raise RuntimeError(f"Duplicate line_number found in purchase_order_lines: {dup_line_num}")

    # 2. Drop legacy non-unique index
    op.drop_index(
        'ix_purchase_order_lines_order_ext_line',
        table_name='purchase_order_lines',
        postgresql_where=sa.text("external_line_id IS NOT NULL")
    )

    # 3. Create partial unique index on (purchase_order_id, external_line_id)
    op.create_index(
        'uq_purchase_order_lines_order_ext_line',
        'purchase_order_lines',
        ['purchase_order_id', 'external_line_id'],
        unique=True,
        postgresql_where=sa.text("external_line_id IS NOT NULL")
    )

    # 4. Create partial unique index on (purchase_order_id, line_number)
    op.create_index(
        'uq_purchase_order_lines_order_line_num',
        'purchase_order_lines',
        ['purchase_order_id', 'line_number'],
        unique=True,
        postgresql_where=sa.text("line_number IS NOT NULL")
    )


def downgrade() -> None:
    # 1. Drop partial unique indexes
    op.drop_index(
        'uq_purchase_order_lines_order_line_num',
        table_name='purchase_order_lines',
        postgresql_where=sa.text("line_number IS NOT NULL")
    )
    op.drop_index(
        'uq_purchase_order_lines_order_ext_line',
        table_name='purchase_order_lines',
        postgresql_where=sa.text("external_line_id IS NOT NULL")
    )

    # 2. Re-create non-unique index
    op.create_index(
        'ix_purchase_order_lines_order_ext_line',
        'purchase_order_lines',
        ['purchase_order_id', 'external_line_id'],
        unique=False,
        postgresql_where=sa.text("external_line_id IS NOT NULL")
    )

