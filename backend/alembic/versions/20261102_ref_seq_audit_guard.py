"""append-only guard triggers for reference_sequence_audits

Revision ID: 20261102_ref_seq_audit_guard
Revises: 20261102_reference_sequences
Create Date: 2026-11-02 16:00:00
"""

from alembic import op


revision = '20261102_ref_seq_audit_guard'
down_revision = '20261102_reference_sequences'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_reference_sequence_audit_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'reference_sequence_audits records are append-only and cannot be modified or deleted';
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER reference_sequence_audits_no_update
            BEFORE UPDATE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER reference_sequence_audits_no_delete
            BEFORE DELETE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER reference_sequence_audits_no_truncate
            BEFORE TRUNCATE ON reference_sequence_audits
            FOR EACH STATEMENT EXECUTE FUNCTION reject_reference_sequence_audit_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS reference_sequence_audits_no_truncate ON reference_sequence_audits')
        op.execute('DROP TRIGGER IF EXISTS reference_sequence_audits_no_delete ON reference_sequence_audits')
        op.execute('DROP TRIGGER IF EXISTS reference_sequence_audits_no_update ON reference_sequence_audits')
        op.execute('DROP FUNCTION IF EXISTS reject_reference_sequence_audit_mutation()')

