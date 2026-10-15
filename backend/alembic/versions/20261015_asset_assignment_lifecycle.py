"""add assignment lifecycle records and permission

Revision ID: 20261015_assignment
Revises: 20261014_audit_truncate
Create Date: 2026-10-15 00:00:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = '20261015_assignment'
down_revision = '20261014_audit_truncate'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'audit_events',
        'entity_id',
        existing_type=sa.String(length=100),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.create_table(
        'asset_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_id', sa.Uuid(), nullable=False),
        sa.Column('responsible_department_id', sa.Uuid(), nullable=True),
        sa.Column('location_id', sa.Uuid(), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('reference', sa.String(length=160), nullable=True),
        sa.Column('handover_date', sa.Date(), nullable=True),
        sa.Column('handover_condition', sa.String(length=80), nullable=True),
        sa.Column('included_items', sa.Text(), nullable=True),
        sa.Column('acknowledgement', sa.Text(), nullable=True),
        sa.Column('handover_notes', sa.Text(), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('return_condition', sa.String(length=80), nullable=True),
        sa.Column('return_notes', sa.Text(), nullable=True),
        sa.Column('issue_details', sa.Text(), nullable=True),
        sa.Column('next_asset_status', sa.String(length=16), nullable=True),
        sa.Column('transfer_reason', sa.Text(), nullable=True),
        sa.Column('previous_assignment_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'returned', 'transferred')",
            name='ck_asset_assignments_status',
        ),
        sa.CheckConstraint(
            "(status = 'active' AND ended_at IS NULL) OR (status != 'active' AND ended_at IS NOT NULL)",
            name='ck_asset_assignments_end_state',
        ),
        sa.CheckConstraint(
            "next_asset_status IS NULL OR next_asset_status IN ('in_stock', 'maintenance')",
            name='ck_asset_assignments_next_asset_status',
        ),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'responsible_department_id'],
            ['departments.company_id', 'departments.id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(['company_id', 'location_id'], ['locations.company_id', 'locations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['company_id', 'recipient_id'],
            ['company_memberships.company_id', 'company_memberships.user_id'],
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_asset_assignments_asset_id'), 'asset_assignments', ['asset_id'])
    op.create_index(
        'uq_asset_assignments_active',
        'asset_assignments',
        ['asset_id'],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'asset.assignment.manage'")
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = uuid4()
        bind.execute(
            sa.text(
                'INSERT INTO permissions (id, code, description) '
                'VALUES (:id, :code, :description)'
            ),
            {
                'id': permission_id,
                'code': 'asset.assignment.manage',
                'description': 'Manage asset assignments, handovers, returns, and transfers',
            },
        )

    for scope, role_code in (
        ('system', 'system_administrator'),
        ('company', 'company_administrator'),
        ('company', 'asset_manager'),
    ):
        role_id = bind.execute(
            sa.text('SELECT id FROM roles WHERE scope = :scope AND code = :code'),
            {'scope': scope, 'code': role_code},
        ).scalar_one_or_none()
        if role_id is not None:
            exists = bind.execute(
                sa.text(
                    'SELECT 1 FROM role_permissions '
                    'WHERE role_id = :role_id AND permission_id = :permission_id'
                ),
                {'role_id': role_id, 'permission_id': permission_id},
            ).scalar_one_or_none()
            if exists is None:
                bind.execute(
                    sa.text(
                        'INSERT INTO role_permissions (role_id, permission_id) '
                        'VALUES (:role_id, :permission_id)'
                    ),
                    {'role_id': role_id, 'permission_id': permission_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'asset.assignment.manage'")
    ).scalar_one_or_none()
    if permission_id is not None:
        bind.execute(
            sa.text('DELETE FROM role_permissions WHERE permission_id = :permission_id'),
            {'permission_id': permission_id},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :permission_id"),
            {'permission_id': permission_id},
        )
    op.drop_index('uq_asset_assignments_active', table_name='asset_assignments')
    op.drop_index(op.f('ix_asset_assignments_asset_id'), table_name='asset_assignments')
    op.drop_table('asset_assignments')
    op.alter_column(
        'audit_events',
        'entity_id',
        existing_type=sa.String(length=512),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
