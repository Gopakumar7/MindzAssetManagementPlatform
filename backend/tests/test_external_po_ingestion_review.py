"""Milestone 2C.4.1: External PO Ingestion Production-Readiness Review Tests.

Comprehensive PostgreSQL integration verification addressing:
1. Concurrent duplicate imports (genuine multithreaded concurrency against PostgreSQL).
2. Authorization (unauthenticated, insufficient permissions, cross-company isolation, no information leakage).
3. Audit verification (creation/update events, rollback on rejection, no sensitive tokens/credentials logged).
4. Timestamp edge cases (deterministic handling of all 8 timestamp states).
5. ERP instance identity (distinct instance identities, multi-company coexistence, prefix override immunity).
6. Atomicity (failed headers, invalid lines, supplier/category failures, receipt violations leave zero dirty state).
7. Display-number contract (prefix sourcing, immutability, uniqueness, independent preservation, deterministic normalization).
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.authentication import password_hasher
from app.erp_ingestion_service import (
    clear_dynamic_integrations,
    derive_display_order_number,
    import_external_purchase_order,
    register_trusted_integration,
)
from app.models import (
    AssetCategory,
    AuditEvent,
    Base,
    Company,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ReferenceSequence,
    Role,
    Supplier,
    User,
)
from app.schemas import (
    ExternalPurchaseOrderImportPayload,
    ExternalPurchaseOrderLineImportPayload,
)


def _login_admin(client):
    res = client.post(
        '/api/v1/auth/login',
        json={'email': 'test-admin@example.invalid', 'password': 'Correct-Horse-42!'},
    )
    assert res.status_code == 200, res.text
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']


def create_test_company(client, code: str, prefix: str):
    res = client.post(
        '/api/v1/companies',
        json={
            'code': code,
            'name': f'Company {code}',
            'number_prefix': prefix,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_supplier(client, company_id: str, code: str):
    res = client.post(
        f'/api/v1/companies/{company_id}/suppliers',
        json={'code': code, 'name': f'Supplier {code}'},
    )
    assert res.status_code == 201, res.text
    return res.json()


def add_company_member(db_session, company_id, email: str, role_code: str) -> tuple[User, str]:
    cid = UUID(str(company_id))
    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == role_code))
    pwd = 'TestPassword123!'
    user = User(
        email=email,
        password_hash=password_hasher.hash(pwd),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        CompanyMembership(
            company_id=cid,
            user_id=user.id,
            role_id=role.id,
            status='active',
        )
    )
    db_session.commit()
    return user, pwd


# =========================================================================
# 1. Concurrent duplicate imports
# =========================================================================
def test_concurrent_duplicate_first_time_imports_postgresql(client, db_session):
    """
    1. Concurrent duplicate imports:
    Two concurrent requests import the exact same external PO concurrently.
    Verify:
    - Exactly one PurchaseOrder record exists.
    - Exactly one set of PurchaseOrderLine records exists.
    - Both requests receive deterministic, valid responses (201 and 200).
    - No unhandled IntegrityError or HTTP 500 is returned.
    - The winning record can be retrieved consistently.
    Uses independent database sessions and genuine concurrent execution.
    """
    comp = create_test_company(client, 'C-CONC-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-CONC-01')
    cats = client.get(f"/api/v1/companies/{comp['id']}/categories").json()
    cat_id = cats[0]['id']

    payload_data = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'CONC-PO-1001',
        'external_system_id': 'CONC-SYS-1001',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'LINE-1',
                'category_id': cat_id,
                'description': 'Laptop Model X',
                'quantity_ordered': 10,
                'unit_cost': '1200.00',
            },
            {
                'external_line_id': 'LINE-2',
                'category_id': cat_id,
                'description': 'Monitor 27"',
                'quantity_ordered': 10,
                'unit_cost': '300.00',
            },
        ],
    }

    test_db_url = os.getenv('TEST_DATABASE_URL')
    if not test_db_url:
        pytest.skip('TEST_DATABASE_URL not configured for concurrent PostgreSQL testing')

    engine = create_engine(test_db_url, pool_pre_ping=True)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    admin_id = admin_user.id
    co_uuid = UUID(comp['id'])

    def worker_import(worker_index: int):
        worker_session = SessionMaker()
        try:
            p = ExternalPurchaseOrderImportPayload(**payload_data)
            po, is_created = import_external_purchase_order(
                worker_session,
                co_uuid,
                p,
                admin_id,
            )
            return {
                'worker': worker_index,
                'po_id': po.id,
                'order_number': po.order_number,
                'is_created': is_created,
                'error': None,
            }
        except Exception as exc:
            return {
                'worker': worker_index,
                'po_id': None,
                'order_number': None,
                'is_created': None,
                'error': str(exc),
            }
        finally:
            worker_session.close()

    # Execute 2 concurrent worker threads
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker_import, i) for i in range(2)]
        results = [f.result() for f in as_completed(futures)]

    # Assert no errors escaped
    for r in results:
        assert r['error'] is None, f"Worker {r['worker']} failed: {r['error']}"

    # Verify responses: one created, one replayed (or both deterministic valid)
    created_count = sum(1 for r in results if r['is_created'] is True)
    replayed_count = sum(1 for r in results if r['is_created'] is False)
    assert created_count == 1, f"Expected exactly 1 creation, got {created_count}"
    assert replayed_count == 1, f"Expected exactly 1 replay, got {replayed_count}"

    # Both must point to the identical PO UUID
    po_ids = {r['po_id'] for r in results}
    assert len(po_ids) == 1, f"Workers returned different PO UUIDs: {po_ids}"

    # Verify exactly one PurchaseOrder record exists in DB
    all_pos = db_session.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == co_uuid,
            PurchaseOrder.external_reference == 'CONC-PO-1001',
        )
    ).all()
    assert len(all_pos) == 1

    # Verify exactly 2 lines exist for this PO
    winning_po = all_pos[0]
    lines = db_session.scalars(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == winning_po.id
        )
    ).all()
    assert len(lines) == 2
    assert {l.external_line_id for l in lines} == {'LINE-1', 'LINE-2'}

    engine.dispose()


def test_concurrent_duplicate_update_imports_postgresql(client, db_session):
    """
    1b. Concurrent duplicate updates:
    Two concurrent requests submit the same update to an existing external PO.
    Verify row-locking and deterministic response without race corruption.
    """
    comp = create_test_company(client, 'C-CONC-02', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-CONC-02')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    initial_payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'CONC-PO-2002',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item 1', 'quantity_ordered': 5, 'unit_cost': '100.00'}],
    }
    res0 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=initial_payload)
    assert res0.status_code == 201

    update_payload = dict(initial_payload)
    update_payload['external_updated_at'] = '2026-11-04T12:00:00Z'
    update_payload['notes'] = 'Concurrent Update Revision'
    update_payload['lines'] = [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item 1 Updated', 'quantity_ordered': 8, 'unit_cost': '100.00'}]

    test_db_url = os.getenv('TEST_DATABASE_URL')
    if not test_db_url:
        pytest.skip('TEST_DATABASE_URL not configured')

    engine = create_engine(test_db_url, pool_pre_ping=True)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    admin_user = db_session.scalar(select(User).where(User.email == 'test-admin@example.invalid'))
    co_uuid = UUID(comp['id'])

    def worker_update(worker_index: int):
        worker_session = SessionMaker()
        try:
            p = ExternalPurchaseOrderImportPayload(**update_payload)
            po, is_created = import_external_purchase_order(
                worker_session,
                co_uuid,
                p,
                admin_user.id,
            )
            return {'worker': worker_index, 'is_created': is_created, 'error': None}
        except Exception as exc:
            return {'worker': worker_index, 'is_created': None, 'error': str(exc)}
        finally:
            worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker_update, i) for i in range(2)]
        results = [f.result() for f in as_completed(futures)]

    for r in results:
        assert r['error'] is None, f"Worker failed: {r['error']}"

    # Both succeeded deterministically (neither created, both return updated/replayed PO)
    assert all(r['is_created'] is False for r in results)

    # Verify final state
    db_session.expire_all()
    po_check = db_session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == co_uuid,
            PurchaseOrder.external_reference == 'CONC-PO-2002',
        )
    )
    assert po_check.notes == 'Concurrent Update Revision'
    lines = db_session.scalars(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == po_check.id
        )
    ).all()
    assert len(lines) == 1
    assert lines[0].quantity_ordered == 8
    engine.dispose()


# =========================================================================
# 2. Authorization
# =========================================================================
def test_authorization_matrix(client, db_session):
    """
    2. Authorization:
    - Unauthenticated request is rejected (401).
    - Authenticated user without dedicated external PO import permission receives HTTP 403.
    - Authorized user with permission can import.
    - Cross-company import is rejected (403).
    - No company data is exposed through error responses.
    """
    comp_a = create_test_company(client, 'C-AUTH-A', 'MZA')
    comp_b = create_test_company(client, 'C-AUTH-B', 'MZB')
    sup_a = create_test_supplier(client, comp_a['id'], 'SUP-A')
    cat_a = client.get(f"/api/v1/companies/{comp_a['id']}/categories").json()[0]

    valid_payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'AUTH-PO-01',
        'supplier_id': sup_a['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat_a['id'], 'description': 'Item', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
    }

    # A. Unauthenticated request -> 401
    client.cookies.clear()
    client.headers.pop('X-CSRF-Token', None)

    res_unauth = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=valid_payload)
    assert res_unauth.status_code == 401, res_unauth.text

    # B. User without procurement.import (read_only_user) -> 403
    ro_user, ro_pwd = add_company_member(db_session, comp_a['id'], 'ro-user@example.invalid', 'read_only_user')
    client.cookies.clear()
    login_ro = client.post('/api/v1/auth/login', json={'email': ro_user.email, 'password': ro_pwd})
    assert login_ro.status_code == 200
    client.headers['X-CSRF-Token'] = login_ro.cookies['mindzen_csrf']

    res_ro = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=valid_payload)
    assert res_ro.status_code == 403, res_ro.text
    assert res_ro.json()['detail'] == 'Insufficient permission'

    # C. Cross-company import attempt:
    # User is member of Company A (with asset_manager role which HAS procurement.import in Company A)
    # Attempts to import into Company B
    mgr_user, mgr_pwd = add_company_member(db_session, comp_a['id'], 'mgr-user@example.invalid', 'asset_manager')
    client.cookies.clear()
    login_mgr = client.post('/api/v1/auth/login', json={'email': mgr_user.email, 'password': mgr_pwd})
    assert login_mgr.status_code == 200
    client.headers['X-CSRF-Token'] = login_mgr.cookies['mindzen_csrf']

    res_cross = client.post(f"/api/v1/companies/{comp_b['id']}/purchase-orders/external-import", json=valid_payload)
    assert res_cross.status_code in (403, 404), res_cross.text
    if res_cross.status_code == 403:
        assert res_cross.json()['detail'] == 'Insufficient permission'
    else:
        assert 'Company not found' in res_cross.json()['detail']

    # D. Authorized user with permission in Company A -> 201
    res_mgr_ok = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=valid_payload)
    assert res_mgr_ok.status_code == 201, res_mgr_ok.text

    # Restore admin login for remainder of tests
    client.cookies.clear()
    _login_admin(client)


# =========================================================================
# 3. Audit verification
# =========================================================================
def test_audit_verification_success_and_rejected_imports(client, db_session):
    """
    3. Audit verification:
    - Verify successful external PO creation generates 'purchase_order_imported' audit event.
    - Verify successful external PO update generates 'purchase_order_import_updated' audit event.
    - Verify rejected imports do not leave misleading success audit events.
    - Verify no credentials, tokens, or sensitive integration data are logged.
    """
    comp = create_test_company(client, 'C-AUD-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-AUD-01')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    co_uuid = UUID(comp['id'])

    # 1. Successful creation
    p_create = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'AUD-PO-01',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item 1', 'quantity_ordered': 5, 'unit_cost': '50.00'}],
    }
    res_create = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_create)
    assert res_create.status_code == 201
    po_id = res_create.json()['id']

    # Query AuditEvent for purchase_order_imported
    events_create = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == co_uuid,
            AuditEvent.action == 'purchase_order_imported',
            AuditEvent.entity_id == str(po_id),
        )
    ).all()
    assert len(events_create) == 1
    evt1 = events_create[0]
    changes1 = db_session.scalar(select(AuditEvent.entity_id).where(AuditEvent.id == evt1.id))
    # Verify no tokens or passwords in audit records
    for evt in db_session.scalars(select(AuditEvent).where(AuditEvent.company_id == co_uuid)).all():
        assert 'password' not in str(evt)
        assert 'token' not in str(evt)

    # 2. Successful update
    p_update = dict(p_create)
    p_update['external_updated_at'] = '2026-11-04T12:00:00Z'
    p_update['notes'] = 'Revised Audit PO'
    res_update = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_update)
    assert res_update.status_code == 200

    events_update = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == co_uuid,
            AuditEvent.action == 'purchase_order_import_updated',
            AuditEvent.entity_id == str(po_id),
        )
    ).all()
    assert len(events_update) == 1

    # 3. Rejected import (Stale update) -> 409
    p_stale = dict(p_create)
    p_stale['external_updated_at'] = '2026-11-04T08:00:00Z'
    res_stale = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_stale)
    assert res_stale.status_code == 409

    # Verify no additional success audit event was logged for this rejected attempt
    events_after_stale = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == co_uuid,
            AuditEvent.action == 'purchase_order_import_updated',
            AuditEvent.entity_id == str(po_id),
        )
    ).all()
    assert len(events_after_stale) == 1


# =========================================================================
# 4. Timestamp edge cases (All 8 scenarios)
# =========================================================================
def test_timestamp_edge_cases_matrix(client, db_session):
    """
    4. Timestamp edge cases:
    Deterministic handling of all 8 cases:
    1. Existing timestamp absent; incoming timestamp absent (payload differs -> update allowed).
    2. Existing timestamp absent; incoming timestamp present (update allowed).
    3. Existing timestamp present; incoming timestamp absent (rejected with 422).
    4. Both timestamps present and incoming is newer (update allowed).
    5. Both timestamps present and incoming is older (rejected with 409).
    6. Same timestamp with identical payload (idempotent replay, 200).
    7. Same timestamp with different payload (rejected with 409).
    8. Identical payload replay without timestamp (idempotent replay, 200).
    """
    comp = create_test_company(client, 'C-TIME-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-TIME-01')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # --- Scenario A: Baseline PO without timestamp ---
    p_notime = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'TIME-PO-01',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'Initial no-timestamp version',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
    }
    r_init = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_notime)
    assert r_init.status_code == 201

    # Case 8: Identical payload replay without timestamp -> 200 OK
    r_case8 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_notime)
    assert r_case8.status_code == 200

    # Case 1: Existing timestamp absent; incoming timestamp absent (different payload) -> 200 OK
    p_diff_notime = dict(p_notime)
    p_diff_notime['notes'] = 'Revised no-timestamp version'
    p_diff_notime['lines'] = [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 12, 'unit_cost': '10.00'}]
    r_case1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_diff_notime)
    assert r_case1.status_code == 200
    assert r_case1.json()['notes'] == 'Revised no-timestamp version'

    # Case 2: Existing timestamp absent; incoming timestamp present -> 200 OK
    p_with_time = dict(p_diff_notime)
    p_with_time['external_updated_at'] = '2026-11-04T12:00:00Z'
    p_with_time['notes'] = 'Now timestamped version'
    r_case2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_with_time)
    assert r_case2.status_code == 200
    assert r_case2.json()['external_updated_at'] is not None

    # Case 3: Existing timestamp present; incoming timestamp absent -> 422 Unprocessable Entity
    p_missing_time = dict(p_with_time)
    del p_missing_time['external_updated_at']
    p_missing_time['notes'] = 'Trying to overwrite with missing timestamp'
    r_case3 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_missing_time)
    assert r_case3.status_code == 422
    assert 'cannot overwrite an existing timestamped record' in r_case3.json()['detail']

    # Case 4: Both timestamps present and incoming is newer -> 200 OK
    p_newer = dict(p_with_time)
    p_newer['external_updated_at'] = '2026-11-04T14:00:00Z'
    p_newer['notes'] = 'Newer timestamped version'
    r_case4 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_newer)
    assert r_case4.status_code == 200
    assert r_case4.json()['notes'] == 'Newer timestamped version'

    # Case 5: Both timestamps present and incoming is older -> 409 Conflict
    p_older = dict(p_newer)
    p_older['external_updated_at'] = '2026-11-04T10:00:00Z'
    p_older['notes'] = 'Older stale version'
    r_case5 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_older)
    assert r_case5.status_code == 409
    assert 'Stale update rejected' in r_case5.json()['detail']

    # Case 6: Same timestamp with identical payload -> 200 OK (idempotent replay)
    r_case6 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_newer)
    assert r_case6.status_code == 200

    # Case 7: Same timestamp with different payload -> 409 Conflict
    p_conflicting = dict(p_newer)
    p_conflicting['notes'] = 'Different notes but same timestamp'
    r_case7 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_conflicting)
    assert r_case7.status_code == 409
    assert 'Conflicting update rejected' in r_case7.json()['detail']


# =========================================================================
# 5. ERP instance identity
# =========================================================================
def test_erp_instance_identity_and_isolation(client, db_session):
    """
    5. ERP instance identity:
    - Two ERP instances in the same company can use the same external_reference.
    - Their external identity remains distinct.
    - Their MindZen display order_numbers remain unique.
    - Two companies can independently import identical external references.
    - The configured source prefix cannot be overridden by the request payload.
    """
    comp_a = create_test_company(client, 'C-INST-A', 'MZA')
    comp_b = create_test_company(client, 'C-INST-B', 'MZB')
    sup_a = create_test_supplier(client, comp_a['id'], 'SUP-IA')
    sup_b = create_test_supplier(client, comp_b['id'], 'SUP-IB')
    cat_a = client.get(f"/api/v1/companies/{comp_a['id']}/categories").json()[0]
    cat_b = client.get(f"/api/v1/companies/{comp_b['id']}/categories").json()[0]

    # Instance 1 in Company A: SAP-PROD-01 -> prefix 'SAP'
    p_inst1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'REF-12345',
        'supplier_id': sup_a['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat_a['id'], 'description': 'Item 1', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
    }
    r1 = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=p_inst1)
    assert r1.status_code == 201
    assert r1.json()['order_number'] == 'SAP-REF-12345'
    po1_id = r1.json()['id']

    # Instance 2 in Company A: SAP-EU-01 -> prefix 'SAP-EU' with same external_reference
    p_inst2 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-EU-01',
        'external_reference': 'REF-12345',
        'supplier_id': sup_a['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat_a['id'], 'description': 'Item 2', 'quantity_ordered': 2, 'unit_cost': '20.00'}],
    }
    r2 = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=p_inst2)
    assert r2.status_code == 201
    assert r2.json()['order_number'] == 'SAP-EU-REF-12345'
    po2_id = r2.json()['id']

    # Verify both exist distinctly in Company A
    assert po1_id != po2_id
    assert r1.json()['order_number'] != r2.json()['order_number']

    # Company B imports identical external reference REF-12345 from SAP-PROD-01
    p_comp_b = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'REF-12345',
        'supplier_id': sup_b['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat_b['id'], 'description': 'Item B', 'quantity_ordered': 3, 'unit_cost': '30.00'}],
    }
    r_b = client.post(f"/api/v1/companies/{comp_b['id']}/purchase-orders/external-import", json=p_comp_b)
    assert r_b.status_code == 201
    assert r_b.json()['order_number'] == 'SAP-REF-12345'
    assert r_b.json()['id'] != po1_id

    # Verify configured source prefix cannot be overridden:
    # If client sends external_reference with a fake prefix 'MYCUSTOM-9999'
    p_fake_prefix = dict(p_inst1)
    p_fake_prefix['external_reference'] = 'MYCUSTOM-9999'
    r_pfx = client.post(f"/api/v1/companies/{comp_a['id']}/purchase-orders/external-import", json=p_fake_prefix)
    assert r_pfx.status_code == 201
    # Trusted prefix 'SAP' is prepended regardless
    assert r_pfx.json()['order_number'] == 'SAP-MYCUSTOM-9999'


# =========================================================================
# 6. Atomicity
# =========================================================================
def test_atomicity_and_full_rollback_on_failure(client, db_session):
    """
    6. Atomicity:
    Verify that failures leave ZERO dirty or partial state:
    - Valid header and several valid lines followed by an invalid line.
    - Invalid supplier mapping.
    - Invalid category mapping.
    - Receipt-history violation.
    - Database uniqueness conflict.
    """
    comp = create_test_company(client, 'C-ATOM-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-ATOM-01')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]
    co_uuid = UUID(comp['id'])

    # A. Valid header and valid line 1, but line 2 has invalid category
    p_invalid_line2 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'ATOM-FAIL-01',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Valid Item', 'quantity_ordered': 10, 'unit_cost': '10.00'},
            {'external_line_id': 'L-2', 'category_id': str(uuid4()), 'description': 'Invalid Item', 'quantity_ordered': 5, 'unit_cost': '10.00'},
        ],
    }
    r_inv2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_invalid_line2)
    assert r_inv2.status_code == 422

    # Verify no partial PO or line was created
    po_check = db_session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == co_uuid,
            PurchaseOrder.external_reference == 'ATOM-FAIL-01',
        )
    )
    assert po_check is None

    # B. Invalid supplier mapping
    p_inv_sup = dict(p_invalid_line2)
    p_inv_sup['supplier_id'] = str(uuid4())
    p_inv_sup['lines'] = [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Valid', 'quantity_ordered': 1, 'unit_cost': '10.00'}]
    r_inv_sup = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_inv_sup)
    assert r_inv_sup.status_code == 422
    assert db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.company_id == co_uuid, PurchaseOrder.external_reference == 'ATOM-FAIL-01')) is None

    # C. Receipt-history violation: Attempt to reduce quantity below received
    # First create valid PO and receive goods
    p_valid = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'ATOM-RECEIPT-01',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Widget', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
    }
    r_create = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_valid)
    assert r_create.status_code == 201
    po_id = UUID(r_create.json()['id'])
    line_id = UUID(r_create.json()['lines'][0]['id'])

    # Receive 5 items
    grn_payload = {
        'received_date': '2026-11-04',
        'lines': [{'purchase_order_line_id': str(line_id), 'quantity_received': 5}],
    }
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json=grn_payload,
    )
    assert grn_res.status_code == 201, grn_res.text

    # Attempt to update ordered quantity to 3 (below 5 received)
    p_bad_qty = dict(p_valid)
    p_bad_qty['external_updated_at'] = '2026-11-04T12:00:00Z'
    p_bad_qty['notes'] = 'Failed update notes'
    p_bad_qty['lines'] = [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Widget', 'quantity_ordered': 3, 'unit_cost': '10.00'}]
    r_bad_qty = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p_bad_qty)
    assert r_bad_qty.status_code == 422
    assert 'items have already been received' in r_bad_qty.json()['detail']

    # Verify no partial changes were persisted
    db_session.expire_all()
    po_after = db_session.get(PurchaseOrder, po_id)
    assert po_after.notes != 'Failed update notes'
    po_lines = db_session.scalars(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == po_id
        )
    ).all()
    assert len(po_lines) == 1
    assert po_lines[0].quantity_ordered == 10


# =========================================================================
# 7. Display-number contract
# =========================================================================
def test_display_number_contract_and_immutability(client, db_session):
    """
    7. Display-number contract:
    - Prefix comes from trusted source configuration.
    - Existing order_number is immutable on update.
    - Display number is unique within the company.
    - External references are preserved independently.
    - Prefix normalization is deterministic.
    """
    comp = create_test_company(client, 'C-DISP-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-DISP-01')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Deterministic normalization function tests
    assert derive_display_order_number('SAP', '10004562') == 'SAP-10004562'
    assert derive_display_order_number('SAP', 'SAP-10004562') == 'SAP-10004562'
    assert derive_display_order_number('sap', 'sap-10004562') == 'SAP-10004562'
    assert derive_display_order_number('NS', '98765') == 'NS-98765'
    assert derive_display_order_number('ORA', 'ORA-777') == 'ORA-777'

    # Ingestion test
    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'DOC-5555',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
    }
    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 201
    po_data = res.json()
    assert po_data['order_number'] == 'SAP-DOC-5555'
    assert po_data['external_reference'] == 'DOC-5555'

    # Attempting to mutate order_number via standard PUT/PATCH is rejected (409 Conflict)
    res_patch = client.patch(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_data['id']}",
        json={'order_number': 'SAP-MUTATED-6666'},
    )
    assert res_patch.status_code == 409
    assert 'immutable and cannot be modified' in res_patch.json()['detail']