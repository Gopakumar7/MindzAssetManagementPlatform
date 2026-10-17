"""add dashboard.read permission and grant to company_administrator, asset_manager, auditor

Revision ID: 20261017_dashboard_permission
Revises: 20261017_service_management
Create Date: 2026-10-17 14:35:00
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = '20261017_dashboard_permission'
down_revision = '20261017_service_management'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    code = 'dashboard.read'
    description = 'Read executive dashboard and key metrics'

    permission_id = bind.execute(
        sa.text('SELECT id FROM permissions WHERE code = :code'),
        {'code': code},
    ).scalar_one_or_none()
    if permission_id is None:
        permission_id = uuid4()
        bind.execute(
            sa.text('INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description)'),
            {'id': permission_id, 'code': code, 'description': description},
        )

    roles = ('system_administrator', 'company_administrator', 'asset_manager', 'auditor')
    for role_code in roles:
        scope = 'system' if role_code == 'system_administrator' else 'company'
        role_id = bind.execute(
            sa.text('SELECT id FROM roles WHERE scope = :scope AND code = :code'),
            {'scope': scope, 'code': role_code},
        ).scalar_one_or_none()
        if role_id is None:
            continue
        bind.execute(
            sa.text(
                'INSERT INTO role_permissions (role_id, permission_id) '
                'VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING'
            ),
            {'role_id': role_id, 'permission_id': permission_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    permission_ids = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'dashboard.read'")
    ).scalars().all()
    for permission_id in permission_ids:
        bind.execute(
            sa.text('DELETE FROM role_permissions WHERE permission_id = :permission_id'),
            {'permission_id': permission_id},
        )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code = 'dashboard.read'")
    )

