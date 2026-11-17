"""Make company reference number system-generated and immutable

Revision ID: 20261112_company_ref_number
Revises: 20261106_wr_correction_ledger
Create Date: 2026-11-12 17:30:00
"""

from uuid import uuid4
from alembic import op
import sqlalchemy as sa


revision = '20261112_company_ref_number'
down_revision = '20261106_wr_correction_ledger'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add reference_number column to companies (initially nullable for backfill safety)
    op.add_column('companies', sa.Column('reference_number', sa.String(length=32), nullable=True))

    # 2. Backfill existing companies sequentially ordered deterministically by created_at, id
    companies_table = sa.table(
        'companies',
        sa.column('id', sa.Uuid()),
        sa.column('reference_number', sa.String()),
        sa.column('created_at', sa.DateTime()),
    )
    existing_companies = bind.execute(
        sa.select(companies_table.c.id).order_by(
            companies_table.c.created_at.asc(),
            companies_table.c.id.asc(),
        )
    ).all()

    for idx, row in enumerate(existing_companies, start=1):
        ref = f"CMP-{idx:04d}"
        bind.execute(
            sa.update(companies_table)
            .where(companies_table.c.id == row.id)
            .values(reference_number=ref)
        )

    # 3. Enforce not null and unique constraint on companies.reference_number
    # (The unique constraint automatically creates the underlying unique btree index in PostgreSQL)
    op.alter_column('companies', 'reference_number', nullable=False)
    op.create_unique_constraint('uq_companies_reference_number', 'companies', ['reference_number'])

    # 4. Make company_id nullable on reference_sequences and reference_sequence_audits
    op.alter_column('reference_sequences', 'company_id', nullable=True)
    op.alter_column('reference_sequence_audits', 'company_id', nullable=True)

    # 5. Create partial unique index on system reference sequences (where company_id IS NULL)
    op.create_index(
        'uq_reference_sequences_system_entity_fy',
        'reference_sequences',
        ['entity_type', 'fiscal_year'],
        unique=True,
        postgresql_where=sa.text('company_id IS NULL'),
        sqlite_where=sa.text('company_id IS NULL'),
    )

    # 6. Seed initial system reference sequence for company
    ref_seq_table = sa.table(
        'reference_sequences',
        sa.column('id', sa.Uuid()),
        sa.column('company_id', sa.Uuid()),
        sa.column('entity_type', sa.String()),
        sa.column('fiscal_year', sa.String()),
        sa.column('prefix', sa.String()),
        sa.column('separator', sa.String()),
        sa.column('padding', sa.Integer()),
        sa.column('current_value', sa.BigInteger()),
        sa.column('is_active', sa.Boolean()),
    )
    has_seq = bind.execute(
        sa.select(ref_seq_table.c.id).where(
            ref_seq_table.c.company_id.is_(None),
            ref_seq_table.c.entity_type == 'company',
            ref_seq_table.c.fiscal_year == 'PERMANENT',
        )
    ).first()

    if not has_seq:
        bind.execute(
            sa.insert(ref_seq_table).values(
                id=uuid4(),
                company_id=None,
                entity_type='company',
                fiscal_year='PERMANENT',
                prefix='CMP',
                separator='-',
                padding=4,
                current_value=len(existing_companies),
                is_active=True,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    # 1. Audit preservation safety guard:
    # If system sequence audit records exist (company_id IS NULL), restoring NOT NULL
    # would either fail with an integrity error or silently delete immutable audit records.
    audit_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM reference_sequence_audits WHERE company_id IS NULL")
    ).scalar() or 0
    if audit_count > 0:
        raise RuntimeError(
            f"Cannot safely downgrade migration {revision}: {audit_count} system-level sequence audit record(s) "
            "exist with company_id IS NULL. To preserve immutable audit history and prevent silent data loss, "
            "downgrade is blocked. System-level sequence audit records must be explicitly archived before downgrade."
        )

    # 2. Remove system reference sequence
    op.execute("DELETE FROM reference_sequences WHERE company_id IS NULL AND entity_type = 'company'")

    # 3. Drop partial unique index on system reference sequences
    op.drop_index('uq_reference_sequences_system_entity_fy', table_name='reference_sequences')

    # 4. Restore company_id not null on reference_sequence_audits and reference_sequences
    op.alter_column('reference_sequence_audits', 'company_id', nullable=False)
    op.alter_column('reference_sequences', 'company_id', nullable=False)

    # 5. Drop unique constraint and reference_number column on companies
    op.drop_constraint('uq_companies_reference_number', 'companies', type_='unique')
    op.drop_column('companies', 'reference_number')
