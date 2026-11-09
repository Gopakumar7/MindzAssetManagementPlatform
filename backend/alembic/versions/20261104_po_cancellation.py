"""Purchase order cancellation lifecycle and audit fields

Revision ID: 20261104_po_cancellation
Revises: 20261103_po_line_id_safe
Create Date: 2026-11-04 17:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '20261104_po_cancellation'
down_revision = '20261103_po_line_id_safe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        with op.batch_alter_table('purchase_orders') as batch_op:
            batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
            batch_op.add_column(sa.Column('cancelled_by_id', sa.Uuid(as_uuid=True), nullable=True))
            batch_op.add_column(sa.Column('cancellation_reason', sa.Text(), nullable=True))
            batch_op.create_foreign_key(
                'fk_purchase_orders_cancelled_by',
                'users',
                ['cancelled_by_id'],
                ['id'],
                ondelete='SET NULL',
            )
            batch_op.drop_constraint('ck_purchase_orders_status', type_='check')
            batch_op.create_check_constraint(
                'ck_purchase_orders_status',
                "status IN ('open', 'partially_received', 'received', 'cancelled')",
            )
    else:
        op.add_column('purchase_orders', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column('purchase_orders', sa.Column('cancelled_by_id', sa.Uuid(as_uuid=True), nullable=True))
        op.add_column('purchase_orders', sa.Column('cancellation_reason', sa.Text(), nullable=True))
        op.create_foreign_key(
            'fk_purchase_orders_cancelled_by',
            'purchase_orders',
            'users',
            ['cancelled_by_id'],
            ['id'],
            ondelete='SET NULL',
        )
        op.drop_constraint('ck_purchase_orders_status', 'purchase_orders', type_='check')
        op.create_check_constraint(
            'ck_purchase_orders_status',
            'purchase_orders',
            "status IN ('open', 'partially_received', 'received', 'cancelled')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'sqlite':
        with op.batch_alter_table('purchase_orders') as batch_op:
            batch_op.drop_constraint('ck_purchase_orders_status', type_='check')
            batch_op.create_check_constraint(
                'ck_purchase_orders_status',
                "status IN ('open', 'partially_received', 'received')",
            )
            batch_op.drop_constraint('fk_purchase_orders_cancelled_by', type_='foreignkey')
            batch_op.drop_column('cancellation_reason')
            batch_op.drop_column('cancelled_by_id')
            batch_op.drop_column('cancelled_at')
    else:
        op.drop_constraint('ck_purchase_orders_status', 'purchase_orders', type_='check')
        op.create_check_constraint(
            'ck_purchase_orders_status',
            'purchase_orders',
            "status IN ('open', 'partially_received', 'received')",
        )
        op.drop_constraint('fk_purchase_orders_cancelled_by', 'purchase_orders', type_='foreignkey')
        op.drop_column('purchase_orders', 'cancellation_reason')
        op.drop_column('purchase_orders', 'cancelled_by_id')
        op.drop_column('purchase_orders', 'cancelled_at')

