"""Initial schema for MindZen foundation

Revision ID: 20261013_initial
Revises:
Create Date: 2026-10-13 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '20261013_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'health_checks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='ok'),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index(op.f('ix_health_checks_id'), 'health_checks', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_health_checks_id'), table_name='health_checks')
    op.drop_table('health_checks')
