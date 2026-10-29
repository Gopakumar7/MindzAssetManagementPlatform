"""alter asset_financials currency default to INR

Revision ID: 20261027_currency_default_inr
Revises: 20261027_sys_admin_perms
Create Date: 2026-10-27 21:35:00
"""

from alembic import op
import sqlalchemy as sa

revision = '20261027_currency_default_inr'
down_revision = '20261027_sys_admin_perms'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('asset_financials', 'currency', server_default='INR')
    op.execute("UPDATE asset_financials SET currency = 'INR' WHERE UPPER(TRIM(currency)) = 'USD'")


def downgrade() -> None:
    op.alter_column('asset_financials', 'currency', server_default='USD')
    op.execute("UPDATE asset_financials SET currency = 'USD' WHERE UPPER(TRIM(currency)) = 'INR'")
