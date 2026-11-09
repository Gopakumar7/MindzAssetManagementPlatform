"""create reference_sequences and reference_sequence_audits tables

Revision ID: 20261102_reference_sequences
Revises: 20261027_currency_default_inr
Create Date: 2026-11-02 12:40:00
"""

from uuid import uuid4
from alembic import op
import sqlalchemy as sa


revision = '20261102_reference_sequences'
down_revision = '20261027_currency_default_inr'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create reference_sequences table
    op.create_table(
        'reference_sequences',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('fiscal_year', sa.String(length=10), nullable=False),
        sa.Column('prefix', sa.String(length=32), nullable=False),
        sa.Column('separator', sa.String(length=4), server_default='-', nullable=False),
        sa.Column('padding', sa.Integer(), server_default='5', nullable=False),
        sa.Column('current_value', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reference_sequences')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_reference_sequences_company_id_companies'), ondelete='CASCADE'),
        sa.UniqueConstraint('company_id', 'entity_type', 'fiscal_year', name='uq_reference_sequences_company_entity_fy'),
    )
    op.create_index('ix_reference_sequences_lookup', 'reference_sequences', ['company_id', 'entity_type', 'is_active'])

    # 2. Create reference_sequence_audits table
    op.create_table(
        'reference_sequence_audits',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('sequence_id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('fiscal_year', sa.String(length=10), nullable=False),
        sa.Column('old_prefix', sa.String(length=32), nullable=False),
        sa.Column('new_prefix', sa.String(length=32), nullable=False),
        sa.Column('old_padding', sa.Integer(), nullable=False),
        sa.Column('new_padding', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('performed_by_id', sa.Uuid(), nullable=False),
        sa.Column('ticket_reference', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reference_sequence_audits')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_reference_sequence_audits_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sequence_id'], ['reference_sequences.id'], name=op.f('fk_reference_sequence_audits_sequence_id_reference_sequences'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['performed_by_id'], ['users.id'], name=op.f('fk_reference_sequence_audits_performed_by_id_users'), ondelete='RESTRICT'),
    )
    op.create_index('ix_reference_sequence_audits_sequence_id', 'reference_sequence_audits', ['sequence_id'])
    op.create_index('ix_reference_sequence_audits_company_id', 'reference_sequence_audits', ['company_id'])

    # 3. Seed reference sequences for existing companies
    bind = op.get_bind()
    companies = bind.execute(sa.text("SELECT id, code FROM companies")).fetchall()

    for comp in companies:
        company_id = comp[0]
        code = comp[1] or ''
        upper_code = code.upper()

        if 'MINDZEN' in upper_code:
            prefix_base = 'MZ'
            # MindZen Demo has 21 existing assets (MZ-000001 to MZ-000021)
            # Per approved design: start from 21 so next generated is MZ-AST-000022
            initial_asset_val = 21
        elif 'WEWIN' in upper_code:
            prefix_base = 'WW'
            initial_asset_val = 0
        else:
            prefix_base = upper_code.split('-')[0][:4] if upper_code else 'ORG'
            initial_asset_val = 0

        # Permanent asset sequence
        bind.execute(
            sa.text("""
                INSERT INTO reference_sequences (id, company_id, entity_type, fiscal_year, prefix, separator, padding, current_value, is_active)
                VALUES (:id, :company_id, :entity_type, :fiscal_year, :prefix, :separator, :padding, :current_value, :is_active)
                ON CONFLICT (company_id, entity_type, fiscal_year) DO NOTHING
            """),
            {
                'id': uuid4(),
                'company_id': company_id,
                'entity_type': 'asset',
                'fiscal_year': 'PERMANENT',
                'prefix': f'{prefix_base}-AST',
                'separator': '-',
                'padding': 6,
                'current_value': initial_asset_val,
                'is_active': True,
            }
        )

        # Transactional entities for current fiscal year 2026-27
        txn_entities = [
            ('purchase_order', 'PO', 5),
            ('goods_receipt', 'GRN', 5),
            ('verification_campaign', 'VC', 5),
            ('service_request', 'SR', 5),
            ('maintenance_work_order', 'MWO', 5),
            ('asset_transfer', 'TRF', 5),
            ('asset_disposal', 'DSP', 5),
        ]
        for ent_type, suffix, pad in txn_entities:
            bind.execute(
                sa.text("""
                    INSERT INTO reference_sequences (id, company_id, entity_type, fiscal_year, prefix, separator, padding, current_value, is_active)
                    VALUES (:id, :company_id, :entity_type, :fiscal_year, :prefix, :separator, :padding, :current_value, :is_active)
                    ON CONFLICT (company_id, entity_type, fiscal_year) DO NOTHING
                """),
                {
                    'id': uuid4(),
                    'company_id': company_id,
                    'entity_type': ent_type,
                    'fiscal_year': '2026-27',
                    'prefix': f'{prefix_base}-{suffix}',
                    'separator': '-',
                    'padding': pad,
                    'current_value': 0,
                    'is_active': True,
                }
            )


def downgrade() -> None:
    op.drop_index('ix_reference_sequence_audits_company_id', table_name='reference_sequence_audits')
    op.drop_index('ix_reference_sequence_audits_sequence_id', table_name='reference_sequence_audits')
    op.drop_table('reference_sequence_audits')

    op.drop_index('ix_reference_sequences_lookup', table_name='reference_sequences')
    op.drop_table('reference_sequences')

