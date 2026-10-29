"""grant alerts and notifications permissions to system_administrator role

Revision ID: 20261027_sys_admin_perms
Revises: 20261019_notifications_sched
Create Date: 2026-10-27 20:20:00
"""

from alembic import op
import sqlalchemy as sa

revision = '20261027_sys_admin_perms'
down_revision = '20261019_notifications_sched'
branch_labels = None
depends_on = None

PERMISSIONS_TO_ADD = [
    'alerts.read',
    'alerts.manage',
    'notifications.read',
    'notifications.manage',
]


def upgrade() -> None:
    bind = op.get_bind()
    roles_table = sa.table(
        'roles',
        sa.column('id', sa.Uuid()),
        sa.column('scope', sa.String()),
        sa.column('code', sa.String()),
    )
    permissions_table = sa.table(
        'permissions',
        sa.column('id', sa.Uuid()),
        sa.column('code', sa.String()),
    )
    role_permissions_table = sa.table(
        'role_permissions',
        sa.column('role_id', sa.Uuid()),
        sa.column('permission_id', sa.Uuid()),
    )

    sys_admin_id = bind.execute(
        sa.select(roles_table.c.id).where(
            roles_table.c.scope == 'system',
            roles_table.c.code == 'system_administrator',
        )
    ).scalar_one_or_none()

    if not sys_admin_id:
        return

    for p_code in PERMISSIONS_TO_ADD:
        pid = bind.execute(
            sa.select(permissions_table.c.id).where(permissions_table.c.code == p_code)
        ).scalar_one_or_none()
        if not pid:
            continue
        exists = bind.execute(
            sa.select(role_permissions_table.c.role_id).where(
                role_permissions_table.c.role_id == sys_admin_id,
                role_permissions_table.c.permission_id == pid,
            )
        ).scalar_one_or_none()
        if not exists:
            bind.execute(
                role_permissions_table.insert().values(role_id=sys_admin_id, permission_id=pid)
            )


def downgrade() -> None:
    bind = op.get_bind()
    roles_table = sa.table(
        'roles',
        sa.column('id', sa.Uuid()),
        sa.column('scope', sa.String()),
        sa.column('code', sa.String()),
    )
    permissions_table = sa.table(
        'permissions',
        sa.column('id', sa.Uuid()),
        sa.column('code', sa.String()),
    )
    role_permissions_table = sa.table(
        'role_permissions',
        sa.column('role_id', sa.Uuid()),
        sa.column('permission_id', sa.Uuid()),
    )

    sys_admin_id = bind.execute(
        sa.select(roles_table.c.id).where(
            roles_table.c.scope == 'system',
            roles_table.c.code == 'system_administrator',
        )
    ).scalar_one_or_none()

    if not sys_admin_id:
        return

    for p_code in PERMISSIONS_TO_ADD:
        pid = bind.execute(
            sa.select(permissions_table.c.id).where(permissions_table.c.code == p_code)
        ).scalar_one_or_none()
        if pid:
            bind.execute(
                role_permissions_table.delete().where(
                    role_permissions_table.c.role_id == sys_admin_id,
                    role_permissions_table.c.permission_id == pid,
                )
            )
