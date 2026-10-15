from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, Role, role_permissions

_PERMISSIONS = {
    'company.read': 'Read authorized company details',
    'company.create': 'Create companies',
    'company.update': 'Update authorized company details',
    'company.members.manage': 'Invite and manage memberships in an authorized company',
    'system.companies.manage': 'Provision companies platform-wide',
    'system.users.manage': 'Manage platform user accounts and system administrator assignments',
    'system.rbac.manage': 'Manage persistent role permission mappings',
    'organization.read': 'Read company organisation masters and configuration',
    'organization.manage': 'Manage company organisation masters and asset numbering',
    'asset.read': 'Read company asset records',
    'asset.create': 'Create company asset records',
    'asset.update': 'Update company asset records',
    'asset.usage.manage': 'Manage department asset usage',
    'asset.assignment.manage': 'Manage asset assignments, handovers, returns, and transfers',
    'procurement.read': 'Read company suppliers, purchase orders, and goods receipts',
    'procurement.manage': 'Manage company suppliers, purchase orders, and goods receipts',
    'maintenance.read': 'Read company service contracts and maintenance requests',
    'maintenance.manage': 'Manage company service contracts and maintenance requests',
    'asset.history.read': 'Read asset history',
    'audit.read': 'Read security and business audit events',
}

_ROLE_PERMISSIONS = {
    ('system', 'system_administrator'): set(_PERMISSIONS),
    ('company', 'company_administrator'): {
        'company.read', 'company.update', 'company.members.manage',
        'organization.read', 'organization.manage', 'asset.read', 'asset.create',
        'asset.update', 'asset.usage.manage', 'asset.history.read', 'audit.read',
        'asset.assignment.manage', 'procurement.read', 'procurement.manage',
        'maintenance.read', 'maintenance.manage',
    },
    ('company', 'asset_manager'): {
        'company.read', 'organization.read', 'organization.manage', 'asset.read',
        'asset.create', 'asset.update', 'asset.usage.manage', 'asset.assignment.manage',
        'asset.history.read', 'procurement.read', 'procurement.manage',
        'maintenance.read', 'maintenance.manage',
    },
    ('company', 'it_support'): {
        'company.read', 'organization.read', 'asset.read', 'asset.update',
        'asset.usage.manage', 'asset.history.read', 'maintenance.read',
        'maintenance.manage',
    },
    ('company', 'auditor'): {
        'company.read', 'organization.read', 'asset.read', 'asset.history.read', 'audit.read',
        'procurement.read', 'maintenance.read',
    },
    ('company', 'read_only_user'): {
        'company.read', 'organization.read', 'asset.read', 'asset.history.read', 'procurement.read',
        'maintenance.read',
    },
}

_ROLE_NAMES = {
    'system_administrator': 'System Administrator',
    'company_administrator': 'Company Administrator',
    'asset_manager': 'Asset Manager',
    'it_support': 'IT Support',
    'auditor': 'Auditor',
    'read_only_user': 'Read-only User',
}


def seed_security_defaults(db: Session, *, commit: bool = True) -> None:
    permissions = {row.code: row for row in db.scalars(select(Permission)).all()}
    for code, description in _PERMISSIONS.items():
        if code not in permissions:
            permission = Permission(code=code, description=description)
            db.add(permission)
            permissions[code] = permission

    roles = {(row.scope, row.code): row for row in db.scalars(select(Role)).all()}
    for (scope, code), permission_codes in _ROLE_PERMISSIONS.items():
        role = roles.get((scope, code))
        if role is None:
            role = Role(scope=scope, code=code, name=_ROLE_NAMES[code])
            db.add(role)
            db.flush()
            db.execute(
                role_permissions.insert(),
                [
                    {'role_id': role.id, 'permission_id': permissions[permission_code].id}
                    for permission_code in sorted(permission_codes)
                ],
            )
    if commit:
        db.commit()
    else:
        db.flush()
