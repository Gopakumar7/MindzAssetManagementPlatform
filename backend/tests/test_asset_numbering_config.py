"""Comprehensive tests for Standardized Company-Code-Based Operational Numbering (Final Architecture Review).

Covers:
1. GET /asset-numbering is strictly read-only and never modifies database state.
2. Legacy sequence alignment occurs only through the explicit transactional align operation.
3. Custom prefixes are never overwritten by alignment.
4. Issued sequences (current_value > 0) are never automatically changed by alignment.
5. Company Code always determines new company provisioning across all 9 operational entities.
6. Legacy number_prefix cannot override Company Code.
7. Maximum supported Company Code length (24 characters) is enforced without silent truncation.
8. Two different company codes cannot produce colliding operational prefixes.
9. All nine operational entity formats (MO-AST, MO-PO, MO-GRN, MO-VC, MO-GRR, MO-SR, MO-MWO, MO-TRF, MO-DSP) are correct.
10. Fiscal-year rollover, controlled prefix change with audit history, Company Code immutability, and RBAC/tenant isolation.
"""

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app import models
from app.models import AuditEvent
from app.reference_service import (
    MAX_COMPANY_CODE_LENGTH,
    PrefixImmutabilityError,
    ReferenceNumberService,
    build_entity_prefix,
    normalize_company_prefix_base,
    validate_numbering_format,
)
from tests.test_security import _company_user, _login_as


def _new_company(client, code: str | None = None, name: str = 'Madhuradhipate Organics', **extra):
    body = {'code': code or f'CO_{uuid4().hex[:6].upper()}', 'name': name, **extra}
    resp = client.post('/api/v1/companies', json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_asset(client, company_id: str) -> str:
    cat = client.get(f'/api/v1/companies/{company_id}/categories').json()[0]['id']
    resp = client.post(f'/api/v1/companies/{company_id}/assets', json={'category_id': cat})
    assert resp.status_code == 201, resp.text
    return resp.json()['asset_number']


def test_all_nine_operational_entity_formats_for_company_mo(client, db_session):
    """All nine operational entities for company MO follow {COMPANY_CODE}-{ENTITY_IDENTIFIER}-{SEQUENCE}."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    assert co['reference_number'].startswith('CMP-')
    cid = UUID(co['id'])

    # Verify GET /asset-numbering returns MO-AST-000001
    cfg = client.get(f"/api/v1/companies/{co['id']}/asset-numbering").json()
    assert cfg['prefix'] == 'MO-AST'
    assert cfg['separator'] == '-'
    assert cfg['padding'] == 6
    assert cfg['next_number'] == 1
    assert cfg['next_reference_preview'] == 'MO-AST-000001'
    assert cfg['issued_count'] == 0
    assert cfg['is_locked'] is False

    target_dt = date(2026, 10, 15)
    assert ReferenceNumberService.allocate(db_session, cid, 'asset', business_date=target_dt) == 'MO-AST-000001'
    assert ReferenceNumberService.allocate(db_session, cid, 'purchase_order', business_date=target_dt) == 'MO-PO-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'goods_receipt', business_date=target_dt) == 'MO-GRN-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'verification_campaign', business_date=target_dt) == 'MO-VC-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'goods_return', business_date=target_dt) == 'MO-GRR-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'service_request', business_date=target_dt) == 'MO-SR-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'maintenance_work_order', business_date=target_dt) == 'MO-MWO-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'asset_transfer', business_date=target_dt) == 'MO-TRF-2026-27-00001'
    assert ReferenceNumberService.allocate(db_session, cid, 'asset_disposal', business_date=target_dt) == 'MO-DSP-2026-27-00001'


def test_company_mo_end_to_end_api_workflows(client):
    """End-to-end API creation of PO, GRN (with asset registration), and Verification Campaign for MO."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    co_id = co['id']
    cat_id = client.get(f'/api/v1/companies/{co_id}/categories').json()[0]['id']

    sup = client.post(
        f'/api/v1/companies/{co_id}/suppliers',
        json={'code': 'SUP-MO', 'name': 'MO Supplier'},
    ).json()
    po_res = client.post(
        f'/api/v1/companies/{co_id}/purchase-orders',
        json={
            'supplier_id': sup['id'],
            'ordered_date': '2026-10-15',
            'lines': [{'category_id': cat_id, 'description': 'MacBook Pro', 'quantity_ordered': 2, 'unit_cost': '1500.00'}],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()
    assert po['order_number'] == 'MO-PO-2026-27-00001'

    grn_res = client.post(
        f'/api/v1/companies/{co_id}/purchase-orders/{po["id"]}/goods-receipts',
        json={
            'received_date': '2026-10-16',
            'delivery_reference': 'DN-MO-001',
            'lines': [
                {
                    'purchase_order_line_id': po['lines'][0]['id'],
                    'quantity_received': 1,
                    'quantity_rejected': 0,
                    'assets': [{'serial_number': 'SN-MO-001'}],
                }
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text
    grn = grn_res.json()
    assert grn['receipt_number'] == 'MO-GRN-2026-27-00001'
    assert grn['lines'][0]['assets'][0]['asset_number'] == 'MO-AST-000001'

    vc_res = client.post(
        f'/api/v1/companies/{co_id}/verification-campaigns',
        json={
            'name': 'MO Annual Audit',
            'start_date': '2026-10-20',
            'end_date': '2026-11-20',
        },
    )
    assert vc_res.status_code == 201, vc_res.text
    assert vc_res.json()['campaign_reference'] == 'MO-VC-2026-27-00001'


def test_get_asset_numbering_is_strictly_read_only_and_never_mutates_db(client, db_session):
    """1. GET /asset-numbering must be read-only and return persisted state without modifying sequences."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])

    # Simulate legacy unaligned 'AST' prefix in database
    asset_seq = db_session.scalar(
        select(models.ReferenceSequence).where(
            models.ReferenceSequence.company_id == cid,
            models.ReferenceSequence.entity_type == 'asset',
        )
    )
    asset_seq.prefix = 'AST'
    db_session.commit()

    # Calling GET must return the actual persisted prefix ('AST') and must NOT modify the DB
    get_res = client.get(f'/api/v1/companies/{co["id"]}/asset-numbering')
    assert get_res.status_code == 200
    assert get_res.json()['prefix'] == 'AST'
    assert get_res.json()['next_reference_preview'] == 'AST-000001'

    db_session.expire_all()
    assert asset_seq.prefix == 'AST'


def test_explicit_alignment_updates_only_eligible_legacy_defaults_and_preserves_custom_and_issued(client, db_session):
    """2, 3, 4. Explicit align operation updates only unissued legacy defaults, preserving custom prefixes and issued sequences."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])

    seqs = {
        s.entity_type: s
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid))
    }
    # 1) Eligible unissued legacy default ('AST' on asset, current_value=0) -> should become 'MO-AST'
    seqs['asset'].prefix = 'AST'
    seqs['asset'].current_value = 0
    # 2) Custom unissued prefix ('BESPOKE-GRN' on goods_receipt, current_value=0) -> must NOT be overwritten
    seqs['goods_receipt'].prefix = 'BESPOKE-GRN'
    seqs['goods_receipt'].current_value = 0
    # 3) Issued legacy sequence ('AST-PO' on purchase_order, current_value=4) -> must NOT be modified
    seqs['purchase_order'].prefix = 'AST-PO'
    seqs['purchase_order'].current_value = 4
    db_session.commit()

    # Execute explicit alignment operation
    align_res = client.post(f'/api/v1/companies/{co["id"]}/asset-numbering/align')
    assert align_res.status_code == 200, align_res.text
    assert align_res.json()['prefix'] == 'MO-AST'
    assert align_res.json()['next_reference_preview'] == 'MO-AST-000001'

    db_session.expire_all()
    assert seqs['asset'].prefix == 'MO-AST'
    assert seqs['goods_receipt'].prefix == 'BESPOKE-GRN'
    assert seqs['purchase_order'].prefix == 'AST-PO'
    assert seqs['purchase_order'].current_value == 4


def test_company_code_is_sole_authoritative_prefix_and_legacy_number_prefix_cannot_override(client, db_session):
    """5, 6. Company Code always determines new company provisioning; legacy number_prefix cannot override it."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics', number_prefix='LEGACYOVR')
    cid = UUID(co['id'])

    seqs = {
        s.entity_type: s.prefix
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid))
    }
    assert seqs == {
        'asset': 'MO-AST',
        'purchase_order': 'MO-PO',
        'goods_receipt': 'MO-GRN',
        'verification_campaign': 'MO-VC',
        'goods_return': 'MO-GRR',
        'service_request': 'MO-SR',
        'maintenance_work_order': 'MO-MWO',
        'asset_transfer': 'MO-TRF',
        'asset_disposal': 'MO-DSP',
    }
    assert _create_asset(client, co['id']) == 'MO-AST-000001'


def test_company_code_max_length_enforced_without_silent_truncation_and_no_prefix_collision(client):
    """7, 8. Maximum Company Code length (24) is enforced without silent truncation; distinct codes never collide."""
    assert MAX_COMPANY_CODE_LENGTH == 24
    # Existing 23-char code MADHURADHIPATE_ORGANICS and a 24-char code both succeed without truncation
    code_23 = 'MADHURADHIPATE_ORGANICS'
    code_24 = 'MADHURADHIPATE_ORGANICSX'
    assert len(code_23) == 23
    assert len(code_24) == 24

    co_23 = _new_company(client, code=code_23, name='Madhuradhipate Organics LLP')
    co_24 = _new_company(client, code=code_24, name='Madhuradhipate Organics Extended')

    assert _create_asset(client, co_23['id']) == f'{code_23}-AST-000001'
    assert _create_asset(client, co_24['id']) == f'{code_24}-AST-000001'

    # 25-character code is rejected with HTTP 422 rather than silently truncated to 24 chars
    code_25 = 'MADHURADHIPATE_ORGANICSXY'
    assert len(code_25) == 25
    too_long = client.post('/api/v1/companies', json={'code': code_25, 'name': 'Too Long Co'})
    assert too_long.status_code == 422
    assert '24' in too_long.text


def test_two_companies_produce_distinct_references_and_independent_counters(client, db_session):
    """Two companies with different codes (MO and WW) produce distinct references and independent counters."""
    co_mo = _new_company(client, code='MO', name='Madhuradhipate Organics')
    co_ww = _new_company(client, code='WW', name='WeWin Global')

    assert _create_asset(client, co_mo['id']) == 'MO-AST-000001'
    assert _create_asset(client, co_mo['id']) == 'MO-AST-000002'
    assert _create_asset(client, co_ww['id']) == 'WW-AST-000001'
    assert _create_asset(client, co_mo['id']) == 'MO-AST-000003'
    assert _create_asset(client, co_ww['id']) == 'WW-AST-000002'

    po_mo = ReferenceNumberService.allocate(db_session, UUID(co_mo['id']), 'purchase_order', business_date=date(2026, 6, 1))
    po_ww = ReferenceNumberService.allocate(db_session, UUID(co_ww['id']), 'purchase_order', business_date=date(2026, 6, 1))
    assert po_mo == 'MO-PO-2026-27-00001'
    assert po_ww == 'WW-PO-2026-27-00001'


def test_fiscal_year_rollover_preserves_asset_permanence_and_resets_fy_entities(client, db_session):
    """FY entities reset on April 1 (2026-27 -> 2027-28) while asset numbering remains PERMANENT."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])

    po_fy1_a = ReferenceNumberService.allocate(db_session, cid, 'purchase_order', business_date=date(2027, 3, 31))
    po_fy1_b = ReferenceNumberService.allocate(db_session, cid, 'purchase_order', business_date=date(2027, 3, 31))
    po_fy2_a = ReferenceNumberService.allocate(db_session, cid, 'purchase_order', business_date=date(2027, 4, 1))
    assert po_fy1_a == 'MO-PO-2026-27-00001'
    assert po_fy1_b == 'MO-PO-2026-27-00002'
    assert po_fy2_a == 'MO-PO-2027-28-00001'

    a1 = ReferenceNumberService.allocate(db_session, cid, 'asset', business_date=date(2027, 3, 31))
    a2 = ReferenceNumberService.allocate(db_session, cid, 'asset', business_date=date(2027, 4, 1))
    assert a1 == 'MO-AST-000001'
    assert a2 == 'MO-AST-000002'


@pytest.mark.parametrize('input_prefix,expected_prefix', [
    ('MO-AST', 'MO-AST'),
    ('MO', 'MO-AST'),
    ('mz', 'MZ-AST'),
    ('MZ-AST', 'MZ-AST'),
])
def test_asset_numbering_configuration_accepts_company_prefix_without_duplicating(client, db_session, input_prefix, expected_prefix):
    co = _new_company(client, code=f'C_{uuid4().hex[:4].upper()}')
    resp = client.put(
        f"/api/v1/companies/{co['id']}/asset-numbering",
        json={'prefix': input_prefix, 'separator': '-', 'padding': 6},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()['prefix'] == expected_prefix
    assert resp.json()['next_reference_preview'] == f'{expected_prefix}-000001'
    assert _create_asset(client, co['id']) == f'{expected_prefix}-000001'
    event = db_session.scalar(
        select(AuditEvent).where(AuditEvent.entity_type == 'AssetNumbering', AuditEvent.company_id == UUID(co['id']))
    )
    assert event is not None


@pytest.mark.parametrize('separator,expected', [('-', 'XY-AST-000001'), ('/', 'XY-AST/000001')])
def test_supported_separators(client, separator, expected):
    co = _new_company(client, code='XY', number_separator=separator)
    assert _create_asset(client, co['id']) == expected


@pytest.mark.parametrize('bad_prefix', [
    'MO-MO-AST',
    'MO-MO',
    'AST-AST',
    'MO-AST-AST',
    'A B',
    'AST/',
    '',
    'A' * 29,
    'ÄBC',
    '-MO',
    'MO-',
])
def test_invalid_and_duplicated_prefixes_rejected(client, bad_prefix):
    co = _new_company(client)
    resp = client.put(
        f"/api/v1/companies/{co['id']}/asset-numbering",
        json={'prefix': bad_prefix, 'separator': '-', 'padding': 6},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize('separator', ['.', '_', '--', ' ', ''])
def test_invalid_separator_rejected(client, separator):
    co = _new_company(client)
    resp = client.put(
        f"/api/v1/companies/{co['id']}/asset-numbering",
        json={'prefix': 'MO-AST', 'separator': separator, 'padding': 6},
    )
    assert resp.status_code == 422
    assert 'Separator' in resp.text


def test_issued_sequence_is_locked_and_unchanged(client):
    co = _new_company(client, code='MO')
    assert _create_asset(client, co['id']) == 'MO-AST-000001'
    resp = client.put(
        f"/api/v1/companies/{co['id']}/asset-numbering",
        json={'prefix': 'MZ-AST', 'separator': '/', 'padding': 8},
    )
    assert resp.status_code == 409
    cfg = client.get(f"/api/v1/companies/{co['id']}/asset-numbering").json()
    assert cfg['is_locked'] is True and cfg['prefix'] == 'MO-AST' and cfg['issued_count'] == 1
    assert _create_asset(client, co['id']) == 'MO-AST-000002'


def test_controlled_prefix_change_preserves_audit_history(client, db_session):
    co = _new_company(client, code='MO')
    assert _create_asset(client, co['id']) == 'MO-AST-000001'
    seq = ReferenceNumberService.get_asset_sequence(db_session, UUID(co['id']))
    with pytest.raises(PrefixImmutabilityError):
        ReferenceNumberService.update_sequence_standard(db_session, seq.id, 'MZ-AST')
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))
    ReferenceNumberService.update_prefix_controlled(
        db_session, seq.id, 'MZ-AST', 'Rebrand', admin.id, 'TICKET-1'
    )
    db_session.commit()
    audits = db_session.scalars(
        select(models.ReferenceSequenceAudit).where(models.ReferenceSequenceAudit.sequence_id == seq.id)
    ).all()
    assert len(audits) == 1 and (audits[0].old_prefix, audits[0].new_prefix) == ('MO-AST', 'MZ-AST')
    assert seq.current_value == 1
    assert _create_asset(client, co['id']) == 'MZ-AST-000002'


def test_company_code_immutable_during_normal_company_editing(client):
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    patch_res = client.patch(
        f"/api/v1/companies/{co['id']}",
        json={'code': 'NEWCODE', 'name': 'Updated Name'},
    )
    assert patch_res.status_code == 422
    assert 'locked' in patch_res.text.lower()

    dup_res = client.post('/api/v1/companies', json={'code': 'MO', 'name': 'Another MO'})
    assert dup_res.status_code == 409


def test_validator_and_prefix_builder_unit():
    assert normalize_company_prefix_base('mo', company_code='MO') == 'MO'
    assert normalize_company_prefix_base('MO-AST', company_code='MO') == 'MO'
    assert build_entity_prefix('MO', 'AST') == 'MO-AST'
    assert build_entity_prefix('MO-AST', 'AST') == 'MO-AST'
    assert validate_numbering_format('mo', '-', 6, entity_suffix='AST') == ('MO-AST', '-')
    assert validate_numbering_format('MO-AST', '-', 6, entity_suffix='AST') == ('MO-AST', '-')
    with pytest.raises(ValueError):
        normalize_company_prefix_base('A' * 25)
    with pytest.raises(ValueError):
        validate_numbering_format('MO-MO-AST', '-', 6, entity_suffix='AST')
    with pytest.raises(ValueError):
        validate_numbering_format('AST', '-', 6, entity_suffix='AST')
    with pytest.raises(ValueError):
        validate_numbering_format('MO-AST', '.', 6, entity_suffix='AST')


def test_unauthorized_user_cannot_change_or_align_numbering_or_cross_tenant(client, db_session):
    company_a = db_session.get(models.Company, UUID(_new_company(client, code='NUMA')['id']))
    company_b = db_session.get(models.Company, UUID(_new_company(client, code='NUMB')['id']))
    _company_user(db_session, company_a)
    _login_as(client, 'auditor@example.invalid', 'Company-Auditor-42!')
    payload = {'prefix': 'ZZ-AST', 'separator': '-', 'padding': 6}
    assert client.put(f'/api/v1/companies/{company_a.id}/asset-numbering', json=payload).status_code == 403
    assert client.post(f'/api/v1/companies/{company_a.id}/asset-numbering/align').status_code == 403
    assert client.post(f'/api/v1/companies/{company_a.id}/asset-numbering/admin-align').status_code == 403
    assert client.put(f'/api/v1/companies/{company_b.id}/asset-numbering', json=payload).status_code in (403, 404)
    assert client.get(f'/api/v1/companies/{company_b.id}/asset-numbering').status_code in (403, 404)


def _set_legacy_ast_prefixes(db_session, company_id: UUID, asset_prefix: str = 'AST') -> dict[str, UUID]:
    from app.reference_service import DEFAULT_ENTITY_CONFIGS

    seqs = db_session.scalars(
        select(models.ReferenceSequence)
        .where(models.ReferenceSequence.company_id == company_id)
        .order_by(models.ReferenceSequence.entity_type)
    ).all()
    seq_ids: dict[str, UUID] = {}
    for s in seqs:
        sfx = DEFAULT_ENTITY_CONFIGS[s.entity_type]['suffix']
        s.prefix = asset_prefix if s.entity_type == 'asset' else f'AST-{sfx}'
        s.current_value = 0
        seq_ids[s.entity_type] = s.id
    db_session.commit()
    return seq_ids


def test_nine_sequence_changes_produce_nine_complete_immutable_audit_records_and_idempotency(client, db_session):
    """Nine sequence changes produce nine individual AuditEvent rows with complete metadata, are idempotent, and are immutable."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])
    seq_ids = _set_legacy_ast_prefixes(db_session, cid, asset_prefix='AST')
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))

    res = client.post(f'/api/v1/companies/{co["id"]}/asset-numbering/align')
    assert res.status_code == 200, res.text
    assert res.json()['prefix'] == 'MO-AST'

    db_session.expire_all()
    audits = db_session.scalars(
        select(AuditEvent)
        .where(AuditEvent.company_id == cid, AuditEvent.action == 'sequence.prefix_aligned')
        .order_by(AuditEvent.id)
    ).all()
    assert len(audits) == 9

    expected_old = {
        'asset': 'AST',
        'purchase_order': 'AST-PO',
        'goods_receipt': 'AST-GRN',
        'verification_campaign': 'AST-VC',
        'goods_return': 'AST-GRR',
        'service_request': 'AST-SR',
        'maintenance_work_order': 'AST-MWO',
        'asset_transfer': 'AST-TRF',
        'asset_disposal': 'AST-DSP',
    }
    expected_new = {
        'asset': 'MO-AST',
        'purchase_order': 'MO-PO',
        'goods_receipt': 'MO-GRN',
        'verification_campaign': 'MO-VC',
        'goods_return': 'MO-GRR',
        'service_request': 'MO-SR',
        'maintenance_work_order': 'MO-MWO',
        'asset_transfer': 'MO-TRF',
        'asset_disposal': 'MO-DSP',
    }
    seen_entities = set()
    for ev in audits:
        assert ev.actor_id == admin.id
        assert ev.company_id == cid
        assert ev.entity_type == 'ReferenceSequence'
        assert ev.outcome == 'success'
        assert ev.occurred_at is not None
        ch = ev.changes
        ent = ch['entity_type']
        seen_entities.add(ent)
        assert ev.entity_id == str(seq_ids[ent])
        assert ch['company_id'] == str(cid)
        assert ch['company_reference'] == co['reference_number']
        assert ch['company_code'] == 'MO'
        assert ch['sequence_id'] == str(seq_ids[ent])
        assert ch['fiscal_year'] == ('PERMANENT' if ent == 'asset' else ReferenceNumberService.get_fiscal_year())
        assert ch['old_prefix'] == expected_old[ent]
        assert ch['new_prefix'] == expected_new[ent]
        assert ch['current_value'] == 0
        assert ch['actor_id'] == str(admin.id)
        assert ch['operation'] == 'align_unissued_company_sequences'
        assert ch['reason']
        assert ch['outcome'] == 'success'
        assert ch['timestamp']
        assert ch['before']['prefix'] == expected_old[ent]
        assert ch['after']['prefix'] == expected_new[ent]

    assert seen_entities == set(expected_new.keys())

    # Repeated alignment is idempotent: 0 new changes and 0 new audit events
    res2 = client.post(f'/api/v1/companies/{co["id"]}/asset-numbering/align')
    assert res2.status_code == 200
    db_session.expire_all()
    audits_after = db_session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == cid, AuditEvent.action == 'sequence.prefix_aligned')
    ).all()
    assert len(audits_after) == 9

    # Audit records are immutable under ORM append-only protection
    audits_after[0].outcome = 'tampered'
    with pytest.raises(ValueError, match='append-only'):
        db_session.flush()
    db_session.rollback()


def test_audit_failure_rolls_back_all_nine_sequence_updates(client, db_session, monkeypatch):
    """If an audit write fails on the 9th sequence, all 9 sequence updates roll back atomically."""
    import app.reference_service as ref_mod

    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])
    _set_legacy_ast_prefixes(db_session, cid, asset_prefix='AST')
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))

    orig_record = ref_mod.record_security_event
    call_count = {'n': 0}

    def failing_record_on_ninth(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 9:
            raise RuntimeError('Simulated audit failure on 9th sequence')
        return orig_record(*args, **kwargs)

    monkeypatch.setattr(ref_mod, 'record_security_event', failing_record_on_ninth)

    with pytest.raises(RuntimeError, match='Simulated audit failure on 9th sequence'):
        ReferenceNumberService.align_unissued_company_sequences(
            db_session, cid, performed_by_id=admin.id
        )

    db_session.expire_all()
    seqs = {
        s.entity_type: s.prefix
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid))
    }
    assert seqs['asset'] == 'AST'
    assert seqs['purchase_order'] == 'AST-PO'
    assert seqs['verification_campaign'] == 'AST-VC'
    audits = db_session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == cid, AuditEvent.action == 'sequence.prefix_aligned')
    ).all()
    assert len(audits) == 0


def test_sequence_update_failure_rolls_back_complete_company_alignment_and_audits(client, db_session, monkeypatch):
    """If a sequence update fails mid-way (e.g. 5th sequence), all prior updates and audits roll back."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])
    _set_legacy_ast_prefixes(db_session, cid, asset_prefix='AST')
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))

    orig_update = ReferenceNumberService.update_sequence_standard
    call_count = {'n': 0}

    @classmethod
    def failing_update_on_fifth(cls, db, sequence_id, new_prefix, new_padding=None):
        call_count['n'] += 1
        if call_count['n'] == 5:
            raise RuntimeError('Simulated sequence update failure on 5th sequence')
        return orig_update(db, sequence_id, new_prefix, new_padding=new_padding)

    monkeypatch.setattr(ReferenceNumberService, 'update_sequence_standard', failing_update_on_fifth)

    with pytest.raises(RuntimeError, match='Simulated sequence update failure on 5th sequence'):
        ReferenceNumberService.align_unissued_company_sequences(
            db_session, cid, performed_by_id=admin.id
        )

    db_session.expire_all()
    seqs = {
        s.entity_type: s.prefix
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid))
    }
    assert seqs['asset'] == 'AST'
    assert seqs['purchase_order'] == 'AST-PO'
    audits = db_session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == cid, AuditEvent.action == 'sequence.prefix_aligned')
    ).all()
    assert len(audits) == 0


def test_dirty_session_rejected_without_committing_unrelated_pending_changes(client, db_session):
    """align_unissued_company_sequences refuses to run on a dirty session so unrelated pending changes are never committed."""
    co = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid = UUID(co['id'])
    _set_legacy_ast_prefixes(db_session, cid, asset_prefix='AST')
    admin = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))

    # Stage an uncommitted change in db_session
    company_obj = db_session.get(models.Company, cid)
    company_obj.name = 'Uncommitted Dirty Name'
    assert db_session.dirty

    with pytest.raises(RuntimeError, match='clean transaction boundary'):
        ReferenceNumberService.align_unissued_company_sequences(
            db_session, cid, performed_by_id=admin.id
        )

    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(models.Company, cid).name == 'Madhuradhipate Organics'
    assert ReferenceNumberService.get_asset_sequence(db_session, cid).prefix == 'AST'


def test_inactive_company_alignment_requires_system_admin_preserves_status_and_blocks_company_users(client, db_session):
    """Inactive company (like CMP-0001 MADHURADHIPATE_ORGANICS) can only be aligned by a System Administrator via admin-align,
    preserving its inactive status and leaving CMP system sequence and other companies untouched.
    """
    from app.authentication import password_hasher

    co_inactive = _new_company(client, code='MADHURADHIPATE_ORGANICS', name='Madhuradhipate Organics LLP')
    co_active = _new_company(client, code='MO', name='Madhuradhipate Organics')
    cid_inactive = UUID(co_inactive['id'])
    cid_active = UUID(co_active['id'])

    _set_legacy_ast_prefixes(db_session, cid_inactive, asset_prefix='AST-AST')
    _set_legacy_ast_prefixes(db_session, cid_active, asset_prefix='AST')

    # Deactivate CMP-0001 (MADHURADHIPATE_ORGANICS)
    comp_inactive_obj = db_session.get(models.Company, cid_inactive)
    comp_inactive_obj.is_active = False
    db_session.commit()

    # Create a company_administrator user on the inactive company
    comp_admin_role = db_session.scalar(select(models.Role).where(models.Role.code == 'company_administrator'))
    admin_user = db_session.scalar(select(models.User).where(models.User.email == 'test-admin@example.invalid'))
    comp_admin_user = models.User(
        email='comp-admin@example.invalid',
        password_hash=password_hasher.hash('Comp-Admin-Pass-42!'),
        is_active=True,
    )
    db_session.add(comp_admin_user)
    db_session.flush()
    db_session.add(
        models.CompanyMembership(
            company_id=cid_inactive,
            user_id=comp_admin_user.id,
            role_id=comp_admin_role.id,
            status='active',
            assigned_by_id=admin_user.id,
        )
    )
    db_session.commit()

    # 1. Ordinary company_administrator cannot align inactive company via normal route (404), admin route (403), or service bypass
    _login_as(client, 'comp-admin@example.invalid', 'Comp-Admin-Pass-42!')
    assert client.post(f'/api/v1/companies/{cid_inactive}/asset-numbering/align').status_code == 404
    assert client.post(f'/api/v1/companies/{cid_inactive}/asset-numbering/admin-align').status_code == 403
    with pytest.raises(PermissionError, match='System Administrator'):
        ReferenceNumberService.align_unissued_company_sequences(
            db_session, cid_inactive, performed_by_id=comp_admin_user.id, allow_inactive_company=True
        )

    # 2. System Administrator cannot use ordinary /align route on inactive company (404 — require_permission is not weakened)
    _login_as(client, 'test-admin@example.invalid', 'Correct-Horse-42!')
    assert client.post(f'/api/v1/companies/{cid_inactive}/asset-numbering/align').status_code == 404

    # Record CMP system sequence value before alignment
    cmp_seq_before = db_session.scalar(
        select(models.ReferenceSequence).where(
            models.ReferenceSequence.company_id.is_(None),
            models.ReferenceSequence.entity_type == 'company',
        )
    ).current_value

    # 3. System Administrator aligns inactive company via /admin-align
    admin_res = client.post(f'/api/v1/companies/{cid_inactive}/asset-numbering/admin-align')
    assert admin_res.status_code == 200, admin_res.text
    assert admin_res.json()['prefix'] == 'MADHURADHIPATE_ORGANICS-AST'
    assert admin_res.json()['next_reference_preview'] == 'MADHURADHIPATE_ORGANICS-AST-000001'

    db_session.expire_all()
    # Inactive status is preserved!
    assert db_session.get(models.Company, cid_inactive).is_active is False

    # All 9 sequences of inactive company are aligned and 9 individual audit records exist
    inactive_seqs = {
        s.entity_type: s.prefix
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid_inactive))
    }
    assert inactive_seqs == {
        'asset': 'MADHURADHIPATE_ORGANICS-AST',
        'purchase_order': 'MADHURADHIPATE_ORGANICS-PO',
        'goods_receipt': 'MADHURADHIPATE_ORGANICS-GRN',
        'verification_campaign': 'MADHURADHIPATE_ORGANICS-VC',
        'goods_return': 'MADHURADHIPATE_ORGANICS-GRR',
        'service_request': 'MADHURADHIPATE_ORGANICS-SR',
        'maintenance_work_order': 'MADHURADHIPATE_ORGANICS-MWO',
        'asset_transfer': 'MADHURADHIPATE_ORGANICS-TRF',
        'asset_disposal': 'MADHURADHIPATE_ORGANICS-DSP',
    }
    inactive_audits = db_session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == cid_inactive, AuditEvent.action == 'sequence.prefix_aligned')
    ).all()
    assert len(inactive_audits) == 9

    # Active company MO was NOT touched by inactive company alignment (separate transaction)
    active_seqs = {
        s.entity_type: s.prefix
        for s in db_session.scalars(select(models.ReferenceSequence).where(models.ReferenceSequence.company_id == cid_active))
    }
    assert active_seqs['asset'] == 'AST'
    assert active_seqs['purchase_order'] == 'AST-PO'

    # System CMP sequence was NOT touched
    cmp_seq_after = db_session.scalar(
        select(models.ReferenceSequence).where(
            models.ReferenceSequence.company_id.is_(None),
            models.ReferenceSequence.entity_type == 'company',
        )
    )
    assert cmp_seq_after.prefix == 'CMP'
    assert cmp_seq_after.current_value == cmp_seq_before

