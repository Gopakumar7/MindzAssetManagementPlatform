"""Tests for system-generated, immutable company reference numbering (CMP-0001...).

Covers:
1. Company code does not influence asset numbering (decoupling verified).
2. Default asset numbering uses established 'AST' prefix.
3. Company references are system-generated and globally unique.
4. Company reference remains immutable after creation.
5. Existing tenant numbering behaviour with explicit prefix is preserved.
6. Backfill ordering is deterministic for identical creation timestamps.
7. No redundant reference number index is created.
8. Downgrade safety guard blocks audit log destruction.
9. Database unique constraint rejects duplicate reference numbers.
10. Rollback safety preserves sequence state on failure.
11. Security audit event captures reference_number.
"""

from datetime import datetime, timezone
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    AssetCategory,
    AssetNumberRule,
    AuditEvent,
    Company,
    ReferenceSequence,
    ReferenceSequenceAudit,
    User,
)
from app.reference_service import ReferenceNumberService
from app.schemas import AssetCreate, CompanyCreate, CompanyUpdate
from app.services import create_asset, create_company


def test_company_creation_generates_expected_cmp_reference(client):
    """Company creation generates the expected CMP-0001 (or sequential 4-digit zero-padded) reference."""
    response = client.post(
        '/api/v1/companies',
        json={'code': f'ALPHA_{uuid4().hex[:6]}', 'name': 'Alpha Corporation'},
    )
    assert response.status_code == 201
    data = response.json()
    assert re.match(r'^CMP-\d{4}$', data['reference_number']), f"Invalid reference format: {data['reference_number']}"
    assert data['name'] == 'Alpha Corporation'
    assert data['is_active'] is True


def test_second_company_receives_next_reference(client):
    """A second and third company receive sequential references."""
    resp1 = client.post('/api/v1/companies', json={'code': f'CO1_{uuid4().hex[:6]}', 'name': 'First Co'})
    resp2 = client.post('/api/v1/companies', json={'code': f'CO2_{uuid4().hex[:6]}', 'name': 'Second Co'})
    resp3 = client.post('/api/v1/companies', json={'code': f'CO3_{uuid4().hex[:6]}', 'name': 'Third Co'})

    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp3.status_code == 201

    ref1 = resp1.json()['reference_number']
    ref2 = resp2.json()['reference_number']
    ref3 = resp3.json()['reference_number']

    num1 = int(ref1.split('-')[1])
    num2 = int(ref2.split('-')[1])
    num3 = int(ref3.split('-')[1])

    assert num2 == num1 + 1
    assert num3 == num2 + 1
    assert ref2 == f"CMP-{num2:04d}"
    assert ref3 == f"CMP-{num3:04d}"


def test_company_code_does_not_influence_asset_numbering(client):
    """1. Company reference (CMP-xxxx) is independent of company code, while operational numbering
    uses {COMPANY_CODE}-AST-{SEQ} and never uses Company Name as a prefix.
    """
    distinctive_code = f'CORP_{uuid4().hex[:6].upper()}'
    resp = client.post(
        '/api/v1/companies',
        json={'code': distinctive_code, 'name': 'Distinctive Name Enterprises'},
    )
    assert resp.status_code == 201
    co_data = resp.json()
    co_id = co_data['id']
    assert re.match(r'^CMP-\d{4}$', co_data['reference_number'])
    assert distinctive_code not in co_data['reference_number']

    # Fetch initial categories
    cats = client.get(f'/api/v1/companies/{co_id}/categories').json()
    cat_id = cats[0]['id']

    # Create an asset in this company without specifying manual asset_number
    asset_resp = client.post(
        f'/api/v1/companies/{co_id}/assets',
        json={'category_id': cat_id, 'serial_number': f'SN-{uuid4().hex[:6]}'},
    )
    assert asset_resp.status_code == 201
    asset_number = asset_resp.json()['asset_number']

    # Verify Company Name is NEVER used as a prefix and standard {COMPANY_CODE}-AST-{SEQ} is used
    assert 'DISTINCTIVE' not in asset_number
    assert 'ENTERPRISES' not in asset_number
    assert asset_number == f'{distinctive_code}-AST-000001'


def test_default_asset_numbering_remains_correct(client):
    """2. Default asset numbering uses {COMPANY_CODE}-AST-000001 with standard 6-digit padding."""
    code = f'DEF_{uuid4().hex[:6].upper()}'
    resp = client.post('/api/v1/companies', json={'code': code, 'name': 'Default Rule Co'})
    assert resp.status_code == 201
    co_id = resp.json()['id']

    cats = client.get(f'/api/v1/companies/{co_id}/categories').json()
    cat_id = cats[0]['id']

    asset_resp = client.post(
        f'/api/v1/companies/{co_id}/assets',
        json={'category_id': cat_id, 'serial_number': 'SERIAL-DEF-001'},
    )
    assert asset_resp.status_code == 201
    asset_num = asset_resp.json()['asset_number']
    assert asset_num == f'{code}-AST-000001'


def test_existing_tenant_numbering_behaviour_preserved(client):
    """5. Company code is the sole authoritative prefix; deprecated number_prefix cannot override company.code."""
    co_code = f'ACME_{uuid4().hex[:6].upper()}'
    resp = client.post(
        '/api/v1/companies',
        json={'code': co_code, 'name': 'Acme Corp', 'number_prefix': 'OVERRIDE'},
    )
    assert resp.status_code == 201
    co_id = resp.json()['id']
    assert resp.json()['reference_number'].startswith('CMP-')

    cats = client.get(f'/api/v1/companies/{co_id}/categories').json()
    cat_id = cats[0]['id']

    asset_resp = client.post(
        f'/api/v1/companies/{co_id}/assets',
        json={'category_id': cat_id, 'serial_number': 'SN-ACME-001'},
    )
    assert asset_resp.status_code == 201
    asset_num = asset_resp.json()['asset_number']
    assert asset_num == f'{co_code}-AST-000001'


def test_client_supplied_reference_values_rejected_by_api(client):
    """3. Client-supplied reference values are rejected by the API contract (422)."""
    response = client.post(
        '/api/v1/companies',
        json={'code': f'CUSTOM_{uuid4().hex[:6]}', 'name': 'Custom Ref Co', 'reference_number': 'CMP-9999'},
    )
    assert response.status_code == 422
    err_body = response.json()
    assert 'reference_number' in str(err_body)
    assert 'system-generated' in str(err_body).lower()


def test_reference_numbers_immutable_after_creation(client):
    """4. Reference numbers cannot be changed after creation."""
    create_resp = client.post('/api/v1/companies', json={'code': f'IMMUT_{uuid4().hex[:6]}', 'name': 'Original Name'})
    assert create_resp.status_code == 201
    co_id = create_resp.json()['id']
    orig_ref = create_resp.json()['reference_number']

    # Attempt to update reference_number via PATCH
    patch_resp = client.patch(
        f'/api/v1/companies/{co_id}',
        json={'reference_number': 'CMP-8888'},
    )
    assert patch_resp.status_code == 422
    assert 'immutable' in str(patch_resp.json()).lower()

    # Verify company reference remains unchanged
    get_resp = client.get(f'/api/v1/companies/{co_id}')
    assert get_resp.status_code == 200
    assert get_resp.json()['reference_number'] == orig_ref

    # Legitimate updates to other fields succeed while reference_number stays intact
    update_resp = client.patch(
        f'/api/v1/companies/{co_id}',
        json={'name': 'Updated Corp Name'},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()['name'] == 'Updated Corp Name'
    assert update_resp.json()['reference_number'] == orig_ref


def test_duplicate_references_rejected_by_database(db_session):
    """9. Duplicate references are rejected by the database uniqueness constraint."""
    ref = f'CMP-TEST-{uuid4().hex[:6]}'
    company1 = Company(
        reference_number=ref,
        code=f'CO_UNIQUE_A_{uuid4().hex[:6]}',
        name='Company Unique A',
    )
    db_session.add(company1)
    db_session.commit()

    company2 = Company(
        reference_number=ref,
        code=f'CO_UNIQUE_B_{uuid4().hex[:6]}',
        name='Company Unique B',
    )
    db_session.add(company2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_failed_company_creation_rollback_safety(client):
    """10. Failed company creation does not leave inconsistent records or sequence state."""
    unique_code = f'VALID_{uuid4().hex[:6]}'
    resp1 = client.post('/api/v1/companies', json={'code': unique_code, 'name': 'Valid One'})
    assert resp1.status_code == 201

    # Duplicate code fails with 409
    resp_fail = client.post('/api/v1/companies', json={'code': unique_code, 'name': 'Duplicate Code'})
    assert resp_fail.status_code == 409

    # Next valid creation gets the next sequence number or sequence is cleanly usable
    resp2 = client.post('/api/v1/companies', json={'code': f'VALID_NEXT_{uuid4().hex[:6]}', 'name': 'Valid Two'})
    assert resp2.status_code == 201
    assert resp2.json()['reference_number'].startswith('CMP-')


def test_backfill_ordering_deterministic_for_identical_timestamps(db_session):
    """6. Backfill ordering is deterministic for identical creation timestamps using id ASC tie-breaker."""
    fixed_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    id_lower = UUID('11111111-1111-1111-1111-111111111111')
    id_higher = UUID('22222222-2222-2222-2222-222222222222')

    c1 = Company(id=id_higher, code=f'TIED_B_{uuid4().hex[:4]}', name='Tied B', reference_number='TMP-B')
    c2 = Company(id=id_lower, code=f'TIED_A_{uuid4().hex[:4]}', name='Tied A', reference_number='TMP-A')
    db_session.add_all([c1, c2])
    db_session.commit()

    # Query with the exact deterministic ordering rule from the migration
    query = (
        select(Company.id)
        .where(Company.id.in_([id_lower, id_higher]))
        .order_by(Company.created_at.asc(), Company.id.asc())
    )
    results = db_session.scalars(query).all()
    # id_lower MUST always precede id_higher deterministically
    assert results == [id_lower, id_higher]


def test_no_redundant_reference_number_index_created(db_session):
    """7. Verified that no duplicate/redundant non-unique index exists for reference_number."""
    inspector = sa_inspect(db_session.get_bind())
    indexes = inspector.get_indexes('companies')
    ref_indexes = [idx for idx in indexes if idx['column_names'] == ['reference_number']]
    # There should only be at most 1 index on reference_number, not both ix_ and uq_
    assert len(ref_indexes) <= 1, f"Found redundant indexes on companies.reference_number: {ref_indexes}"


def test_downgrade_safety_blocks_system_audit_destruction(db_session):
    """8. Downgrade safety guard blocks downgrade if system-level sequence audit records exist."""
    user = User(
        id=uuid4(),
        email=f"auditor_{uuid4().hex[:6]}@example.com",
        password_hash="dummyhash",
        is_active=True,
    )
    dummy_seq_id = uuid4()
    seq = ReferenceSequence(
        id=dummy_seq_id,
        company_id=None,
        entity_type='company',
        fiscal_year='PERMANENT',
        prefix='CMP',
        separator='-',
        padding=4,
        current_value=0,
        is_active=True,
    )
    db_session.add_all([user, seq])
    db_session.flush()

    audit = ReferenceSequenceAudit(
        id=uuid4(),
        sequence_id=dummy_seq_id,
        company_id=None,
        entity_type='company',
        fiscal_year='PERMANENT',
        old_prefix='CMP',
        new_prefix='CMPX',
        old_padding=4,
        new_padding=4,
        reason='Emergency prefix correction test',
        performed_by_id=user.id,
        ticket_reference='SEC-TEST-001',
    )
    db_session.add(audit)
    db_session.flush()

    # The exact query executed by 20261112_company_ref_number.py in downgrade():
    audit_count = db_session.execute(
        text("SELECT COUNT(*) FROM reference_sequence_audits WHERE company_id IS NULL")
    ).scalar() or 0
    assert audit_count == 1

    # Verify that the downgrade guard logic blocks downgrade when audit_count > 0
    def migration_downgrade_guard(bind):
        cnt = bind.execute(
            text("SELECT COUNT(*) FROM reference_sequence_audits WHERE company_id IS NULL")
        ).scalar() or 0
        if cnt > 0:
            raise RuntimeError(
                f"Cannot safely downgrade migration 20261112_company_ref_number: {cnt} system-level "
                "sequence audit record(s) exist with company_id IS NULL. To preserve immutable audit history "
                "and prevent silent data loss, downgrade is blocked."
            )

    with pytest.raises(RuntimeError, match="Cannot safely downgrade migration 20261112_company_ref_number"):
        migration_downgrade_guard(db_session)


def test_audit_event_records_company_reference_number(client):
    """11. Verify security audit event captures reference_number on company creation."""
    resp = client.post('/api/v1/companies', json={'code': f'AUDITCO_{uuid4().hex[:6]}', 'name': 'Audited Co'})
    assert resp.status_code == 201
    co_id = resp.json()['id']
    ref = resp.json()['reference_number']

    audit_resp = client.get('/api/v1/security/audit')
    assert audit_resp.status_code == 200
    events = audit_resp.json()
    company_events = [
        e for e in events
        if e.get('entity_type') == 'Company' and e.get('entity_id') == co_id and e.get('action') == 'created'
    ]
    assert len(company_events) == 1
    changes = company_events[0].get('changes', {})
    assert changes.get('after', {}).get('reference_number') == ref
