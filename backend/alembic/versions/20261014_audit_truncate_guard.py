"""prevent truncating the append-only audit log

Revision ID: 20261014_audit_truncate
Revises: 20261014_security
Create Date: 2026-10-14 18:00:00
"""

from alembic import op

revision = '20261014_audit_truncate'
down_revision = '20261014_security'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            CREATE TRIGGER audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events')
