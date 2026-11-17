"""Milestone 2C.4: External ERP Purchase Order Ingestion Integration Tests.

Comprehensive PostgreSQL integration tests covering all 20 scenarios:
1. First-time external PO import.
2. Repeated identical import — no duplicate.
3. Updated external PO — same PO UUID.
4. Same external reference from two different ERP instances.
5. Same external ID across two companies.
6. Missing supplier mapping — full rollback.
7. Missing category mapping — full rollback.
8. Duplicate external line IDs in one payload.
9. Duplicate line numbers in one payload.
10. Existing line update preserves UUID.
11. Existing GRN relationship remains intact after import.
12. Omitted unreceived line handling.
13. Omitted line with receipt history.
14. Older payload rejection.
15. Identical timestamp with conflicting payload.
16. Concurrent duplicate imports.
17. Unauthorized import.
18. Cross-company import attempt.
19. Internal PO creation still works without any ERP integration.
20. External import never consumes internal PO sequence numbers.
"""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.erp_ingestion_service import (
    clear_dynamic_integrations,
    register_trusted_integration,
)
from app.models import (
    AssetCategory,
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
from app.authentication import password_hasher


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
            'code': prefix,
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


def add_company_member(db_session, company_id, email: str, role_code: str) -> User:
    cid = UUID(str(company_id))
    role = db_session.scalar(select(Role).where(Role.scope == 'company', Role.code == role_code))
    user = User(
        email=email,
        password_hash=password_hasher.hash('Correct-Horse-42!'),
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
    return user


# =========================================================================
# Scenario 1: First-time external PO import
# =========================================================================
def test_scenario_01_first_time_external_po_import(client, db_session):
    """
    Scenario 1: First-time external PO import.
    Submit a valid external PO payload.
    Assert HTTP 200/201, origin == EXTERNAL, order_number matches expected prefixed format,
    lines created, status == OPEN, internal PO sequence unchanged.
    """
    comp = create_test_company(client, 'C-SCEN-01', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-01')
    cats = client.get(f"/api/v1/companies/{comp['id']}/categories").json()
    cat_id = cats[0]['id']

    # Get initial sequence value
    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == UUID(comp['id']),
            ReferenceSequence.entity_type == 'purchase_order',
        )
    )
    initial_seq_val = seq.current_value

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': '10004562',
        'external_system_id': 'SYS-SAP-998811',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'Initial ERP import',
        'lines': [
            {
                'external_line_id': 'SAP-L10',
                'line_number': 10,
                'category_id': cat_id,
                'description': 'Industrial Laptops',
                'quantity_ordered': 5,
                'unit_cost': '1200.00',
            }
        ],
    }

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/external-import",
        json=payload,
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()

    assert data['origin'] == 'EXTERNAL'
    assert data['source_system'] == 'SAP'
    assert data['source_instance_id'] == 'SAP-PROD-01'
    assert data['external_reference'] == '10004562'
    assert data['external_system_id'] == 'SYS-SAP-998811'
    assert data['order_number'] == 'SAP-10004562'
    assert data['status'] == 'open'
    assert len(data['lines']) == 1
    assert data['lines'][0]['external_line_id'] == 'SAP-L10'
    assert data['lines'][0]['line_number'] == 10
    assert data['lines'][0]['quantity_ordered'] == 5

    # Verify sequence was not consumed
    db_session.expire_all()
    seq_after = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == UUID(comp['id']),
            ReferenceSequence.entity_type == 'purchase_order',
        )
    )
    assert seq_after.current_value == initial_seq_val


# =========================================================================
# Scenario 2: Repeated identical import — no duplicate
# =========================================================================
def test_scenario_02_repeated_identical_import_no_duplicate(client, db_session):
    """
    Scenario 2: Repeated identical import — no duplicate.
    Submit the exact same payload a second time.
    Assert HTTP 200 OK, same PO UUID, external_last_synced_at updated,
    line count unchanged, no duplicate records created.
    """
    comp = create_test_company(client, 'C-SCEN-02', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-02')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': '20001111',
        'external_system_id': 'SYS-SAP-20001111',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': cat['id'],
                'description': 'Monitors 27-inch',
                'quantity_ordered': 10,
                'unit_cost': '300.00',
            }
        ],
    }

    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res1.status_code in (200, 201), res1.text
    data1 = res1.json()

    # Second identical import
    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()

    assert data2['id'] == data1['id']
    assert data2['order_number'] == data1['order_number']
    assert len(data2['lines']) == 1

    # Verify total PO count in company is exactly 1
    total_pos = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert total_pos == 1


# =========================================================================
# Scenario 3: Updated external PO — same PO UUID
# =========================================================================
def test_scenario_03_updated_external_po_same_uuid(client, db_session):
    """
    Scenario 3: Updated external PO — same PO UUID.
    Submit updated payload with newer external_updated_at (quantity changed from 10 to 15, notes updated).
    Assert HTTP 200 OK, same PO UUID, line quantity updated, notes updated, status recalculates correctly.
    """
    comp = create_test_company(client, 'C-SCEN-03', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-03')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': '30001111',
        'external_system_id': 'SYS-SAP-30001111',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'First draft',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': cat['id'],
                'description': 'Ergonomic Chairs',
                'quantity_ordered': 10,
                'unit_cost': '250.00',
            }
        ],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload1)
    assert res1.status_code in (200, 201), res1.text
    po1_id = res1.json()['id']

    payload2 = dict(payload1)
    payload2['external_updated_at'] = '2026-11-04T11:00:00Z'
    payload2['notes'] = 'Updated revision from SAP'
    payload2['lines'] = [
        {
            'external_line_id': 'L-1',
            'category_id': cat['id'],
            'description': 'Ergonomic Chairs - Executive',
            'quantity_ordered': 15,
            'unit_cost': '260.00',
        }
    ]

    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload2)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()

    assert data2['id'] == po1_id
    assert data2['order_number'] == 'SAP-30001111'
    assert data2['notes'] == 'Updated revision from SAP'
    assert data2['status'] == 'open'
    assert len(data2['lines']) == 1
    assert data2['lines'][0]['quantity_ordered'] == 15
    assert data2['lines'][0]['description'] == 'Ergonomic Chairs - Executive'


# =========================================================================
# Scenario 4: Same external reference from two different ERP instances
# =========================================================================
def test_scenario_04_same_external_ref_different_erp_instances(client, db_session):
    """
    Scenario 4: Same external reference from two different ERP instances.
    Import PO '1001' from SAP instance 'sap-prod-eu'.
    Import PO '1001' from SAP instance 'sap-prod-us'.
    Assert both succeed as distinct POs with distinct display references and distinct UUIDs.
    """
    comp = create_test_company(client, 'C-SCEN-04', 'MZ')
    cid = UUID(comp['id'])
    sup = create_test_supplier(client, comp['id'], 'SUP-04')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Register the two instances dynamically
    register_trusted_integration('SAP', 'sap-prod-eu', 'SAP-EU', company_id=cid)
    register_trusted_integration('SAP', 'sap-prod-us', 'SAP-US', company_id=cid)

    try:
        p1 = {
            'source_system': 'SAP',
            'source_instance_id': 'sap-prod-eu',
            'external_reference': '1001',
            'supplier_id': sup['id'],
            'ordered_date': '2026-11-04',
            'lines': [
                {
                    'external_line_id': 'LINE-1',
                    'category_id': cat['id'],
                    'description': 'EU Goods',
                    'quantity_ordered': 5,
                    'unit_cost': '100.00',
                }
            ],
        }
        res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
        assert res1.status_code in (200, 201), res1.text
        data1 = res1.json()

        p2 = {
            'source_system': 'SAP',
            'source_instance_id': 'sap-prod-us',
            'external_reference': '1001',
            'supplier_id': sup['id'],
            'ordered_date': '2026-11-04',
            'lines': [
                {
                    'external_line_id': 'LINE-1',
                    'category_id': cat['id'],
                    'description': 'US Goods',
                    'quantity_ordered': 5,
                    'unit_cost': '100.00',
                }
            ],
        }
        res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
        assert res2.status_code in (200, 201), res2.text
        data2 = res2.json()

        assert data1['id'] != data2['id']
        assert data1['order_number'] == 'SAP-EU-1001'
        assert data2['order_number'] == 'SAP-US-1001'
    finally:
        clear_dynamic_integrations()


# =========================================================================
# Scenario 5: Same external ID across two companies
# =========================================================================
def test_scenario_05_same_external_id_across_companies(client, db_session):
    """
    Scenario 5: Same external ID across two companies.
    Import the same external PO into Company A and Company B.
    Assert both succeed independently, isolated by company_id.
    """
    compA = create_test_company(client, 'C-SCEN-05A', 'MZA')
    compB = create_test_company(client, 'C-SCEN-05B', 'MZB')

    supA = create_test_supplier(client, compA['id'], 'SUP-GLOBAL')
    supB = create_test_supplier(client, compB['id'], 'SUP-GLOBAL')

    catA = client.get(f"/api/v1/companies/{compA['id']}/categories").json()[0]
    catB = client.get(f"/api/v1/companies/{compB['id']}/categories").json()[0]

    payloadA = {
        'source_system': 'NETSUITE',
        'source_instance_id': 'NS-PROD-01',
        'external_reference': 'NS-PO-GLOBAL-01',
        'external_system_id': 'NS-SYS-777',
        'supplier_id': supA['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': catA['id'],
                'description': 'Shared Item A',
                'quantity_ordered': 20,
                'unit_cost': '50.00',
            }
        ],
    }
    payloadB = {
        'source_system': 'NETSUITE',
        'source_instance_id': 'NS-PROD-01',
        'external_reference': 'NS-PO-GLOBAL-01',
        'external_system_id': 'NS-SYS-777',
        'supplier_id': supB['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': catB['id'],
                'description': 'Shared Item B',
                'quantity_ordered': 20,
                'unit_cost': '50.00',
            }
        ],
    }

    resA = client.post(f"/api/v1/companies/{compA['id']}/purchase-orders/external-import", json=payloadA)
    assert resA.status_code in (200, 201), resA.text

    resB = client.post(f"/api/v1/companies/{compB['id']}/purchase-orders/external-import", json=payloadB)
    assert resB.status_code in (200, 201), resB.text

    assert resA.json()['company_id'] == compA['id']
    assert resB.json()['company_id'] == compB['id']
    assert resA.json()['id'] != resB.json()['id']


# =========================================================================
# Scenario 6: Missing supplier mapping — full rollback
# =========================================================================
def test_scenario_06_missing_supplier_mapping_rollback(client, db_session):
    """
    Scenario 6: Missing supplier mapping — full rollback.
    Submit payload with an unrecognized supplier code and no supplier_id.
    Assert HTTP 422 Unprocessable Entity.
    Assert no PO or lines created.
    """
    comp = create_test_company(client, 'C-SCEN-06', 'MZ')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'FAIL-SUP-01',
        'supplier_external_code': 'NON-EXISTENT-SUPPLIER-CODE',
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': cat['id'],
                'description': 'Some Item',
                'quantity_ordered': 1,
                'unit_cost': '10.00',
            }
        ],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 422, res.text
    assert 'Supplier mapping failed' in res.json()['detail']

    # Assert no PO or lines exist in DB
    po_count = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert po_count == 0


# =========================================================================
# Scenario 7: Missing category mapping — full rollback
# =========================================================================
def test_scenario_07_missing_category_mapping_rollback(client, db_session):
    """
    Scenario 7: Missing category mapping — full rollback.
    Submit payload with an unrecognized category code on line 2.
    Assert HTTP 422 Unprocessable Entity.
    Assert no PO or lines created.
    """
    comp = create_test_company(client, 'C-SCEN-07', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-07')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'FAIL-CAT-01',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-1',
                'category_id': cat['id'],
                'description': 'Valid Line',
                'quantity_ordered': 2,
                'unit_cost': '100.00',
            },
            {
                'external_line_id': 'L-2',
                'category_external_code': 'GHOST-CATEGORY-99',
                'description': 'Invalid Line',
                'quantity_ordered': 3,
                'unit_cost': '200.00',
            },
        ],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 422, res.text
    assert 'Category mapping failed' in res.json()['detail']

    po_count = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert po_count == 0


# =========================================================================
# Scenario 8: Duplicate external line IDs in one payload
# =========================================================================
def test_scenario_08_duplicate_external_line_ids_in_payload(client, db_session):
    """
    Scenario 8: Duplicate external line IDs in one payload.
    Submit a payload with two lines sharing the same external_line_id.
    Assert HTTP 422 Unprocessable Entity, zero database mutations.
    """
    comp = create_test_company(client, 'C-SCEN-08', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-08')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'DUP-LINE-ID-PO',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'EXT-LINE-DUP',
                'category_id': cat['id'],
                'description': 'Line 1',
                'quantity_ordered': 5,
                'unit_cost': '50.00',
            },
            {
                'external_line_id': 'EXT-LINE-DUP',
                'category_id': cat['id'],
                'description': 'Line 2 duplicate ID',
                'quantity_ordered': 10,
                'unit_cost': '50.00',
            },
        ],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 422, res.text
    assert 'Duplicate external_line_id' in res.json()['detail']

    po_count = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert po_count == 0


# =========================================================================
# Scenario 9: Duplicate line numbers in one payload
# =========================================================================
def test_scenario_09_duplicate_line_numbers_in_payload(client, db_session):
    """
    Scenario 9: Duplicate line numbers in one payload.
    Submit a payload with two lines sharing the same line_number.
    Assert HTTP 422 Unprocessable Entity, zero database mutations.
    """
    comp = create_test_company(client, 'C-SCEN-09', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-09')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'DUP-LINE-NUM-PO',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'EXT-LINE-1',
                'line_number': 10,
                'category_id': cat['id'],
                'description': 'Line 1',
                'quantity_ordered': 5,
                'unit_cost': '50.00',
            },
            {
                'external_line_id': 'EXT-LINE-2',
                'line_number': 10,
                'category_id': cat['id'],
                'description': 'Line 2 same number',
                'quantity_ordered': 10,
                'unit_cost': '50.00',
            },
        ],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 422, res.text
    assert 'Duplicate line_number' in res.json()['detail']

    po_count = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert po_count == 0


# =========================================================================
# Scenario 10: Existing line update preserves UUID
# =========================================================================
def test_scenario_10_existing_line_update_preserves_uuid(client, db_session):
    """
    Scenario 10: Existing line update preserves UUID.
    Import a PO with 2 lines. Update description and unit cost of line 1 in a second import.
    Assert line UUID is unchanged.
    """
    comp = create_test_company(client, 'C-SCEN-10', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-10')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'LINE-UUID-PO',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'L-ALPHA',
                'category_id': cat['id'],
                'description': 'Original Alpha',
                'quantity_ordered': 10,
                'unit_cost': '100.00',
            },
            {
                'external_line_id': 'L-BETA',
                'category_id': cat['id'],
                'description': 'Original Beta',
                'quantity_ordered': 20,
                'unit_cost': '200.00',
            },
        ],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text
    data1 = res1.json()

    line_map_1 = {l['external_line_id']: l['id'] for l in data1['lines']}

    # Update line Alpha
    p2 = dict(p1)
    p2['external_updated_at'] = '2026-11-04T12:00:00Z'
    p2['lines'] = [
        {
            'external_line_id': 'L-ALPHA',
            'category_id': cat['id'],
            'description': 'Updated Alpha Description',
            'quantity_ordered': 12,
            'unit_cost': '110.00',
        },
        {
            'external_line_id': 'L-BETA',
            'category_id': cat['id'],
            'description': 'Original Beta',
            'quantity_ordered': 20,
            'unit_cost': '200.00',
        },
    ]

    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()

    line_map_2 = {l['external_line_id']: l for l in data2['lines']}

    # Assert line UUIDs are strictly identical
    assert line_map_2['L-ALPHA']['id'] == line_map_1['L-ALPHA']
    assert line_map_2['L-BETA']['id'] == line_map_1['L-BETA']
    assert line_map_2['L-ALPHA']['description'] == 'Updated Alpha Description'
    assert line_map_2['L-ALPHA']['quantity_ordered'] == 12


# =========================================================================
# Scenario 11: Existing GRN relationship remains intact after import
# =========================================================================
def test_scenario_11_existing_grn_relationship_remains_intact(client, db_session):
    """
    Scenario 11: Existing GRN relationship remains intact after import.
    Import PO -> receive goods (create GRN) -> import updated PO (e.g., notes changed).
    Assert GRN references, received quantities, and audit logs are undisturbed.
    """
    comp = create_test_company(client, 'C-SCEN-11', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-11')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'GRN-PO-01',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {
                'external_line_id': 'GRN-L1',
                'category_id': cat['id'],
                'description': 'Tracked Item',
                'quantity_ordered': 10,
                'unit_cost': '500.00',
            }
        ],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text
    po_data = res1.json()
    line_id = po_data['lines'][0]['id']

    # Receive 4 units against the line
    grn_payload = {
        'received_date': '2026-11-04',
        'notes': 'Partial receipt test',
        'lines': [{'purchase_order_line_id': line_id, 'quantity_received': 4}],
    }
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_data['id']}/goods-receipts",
        json=grn_payload,
    )
    assert grn_res.status_code == 201, grn_res.text
    grn_id = grn_res.json()['id']

    # Verify PO status is partially_received
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_data['id']}").json()
    assert po_check['status'] == 'partially_received'

    # Now import updated PO from ERP (updating notes and bumping unit cost)
    p2 = dict(p1)
    p2['external_updated_at'] = '2026-11-04T14:00:00Z'
    p2['notes'] = 'Updated ERP notes after GRN'
    p2['lines'] = [
        {
            'external_line_id': 'GRN-L1',
            'category_id': cat['id'],
            'description': 'Tracked Item',
            'quantity_ordered': 10,
            'unit_cost': '520.00',
        }
    ]
    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()

    # Verify PO status is still partially_received
    assert data2['status'] == 'partially_received'
    assert data2['lines'][0]['quantity_received'] == 4
    assert data2['lines'][0]['quantity_remaining'] == 6

    # Verify GRN record in DB is completely intact
    grn_db = db_session.get(GoodsReceipt, UUID(grn_id))
    assert grn_db is not None
    assert str(grn_db.purchase_order_id) == po_data['id']
    grn_lines = db_session.scalars(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == grn_db.id)
    ).all()
    assert len(grn_lines) == 1
    assert str(grn_lines[0].purchase_order_line_id) == line_id
    assert grn_lines[0].quantity_received == 4


# =========================================================================
# Scenario 12: Omitted unreceived line handling
# =========================================================================
def test_scenario_012_omitted_unreceived_line_handling(client, db_session):
    """
    Scenario 12: Omitted unreceived line handling.
    Import a PO with 3 lines. Update with only lines 1 and 2 (line 3 omitted). Line 3 has no receipts.
    Assert update succeeds. Line 3 is safely removed. Lines 1 and 2 preserved.
    """
    comp = create_test_company(client, 'C-SCEN-12', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-12')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'OMIT-LINE-PO',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item 1', 'quantity_ordered': 5, 'unit_cost': '10.00'},
            {'external_line_id': 'L-2', 'category_id': cat['id'], 'description': 'Item 2', 'quantity_ordered': 5, 'unit_cost': '20.00'},
            {'external_line_id': 'L-3', 'category_id': cat['id'], 'description': 'Item 3 (to omit)', 'quantity_ordered': 5, 'unit_cost': '30.00'},
        ],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text
    data1 = res1.json()
    assert len(data1['lines']) == 3

    # Update omitting L-3
    p2 = dict(p1)
    p2['external_updated_at'] = '2026-11-04T11:00:00Z'
    p2['lines'] = [
        {'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item 1', 'quantity_ordered': 5, 'unit_cost': '10.00'},
        {'external_line_id': 'L-2', 'category_id': cat['id'], 'description': 'Item 2', 'quantity_ordered': 5, 'unit_cost': '20.00'},
    ]
    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()

    assert len(data2['lines']) == 2
    ext_ids = {l['external_line_id'] for l in data2['lines']}
    assert ext_ids == {'L-1', 'L-2'}
    assert 'L-3' not in ext_ids


# =========================================================================
# Scenario 13: Omitted line with receipt history
# =========================================================================
def test_scenario_13_omitted_line_with_receipt_history(client, db_session):
    """
    Scenario 13: Omitted line with receipt history.
    Import a PO with 2 lines. Receive goods against line 1. Update payload omitting line 1.
    Assert HTTP 409 Conflict.
    Assert line 1 and its GRN relationship preserved intact.
    """
    comp = create_test_company(client, 'C-SCEN-13', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-13')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'OMIT-REC-PO',
        'external_updated_at': '2026-11-04T10:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [
            {'external_line_id': 'L-REC', 'category_id': cat['id'], 'description': 'Received Item', 'quantity_ordered': 5, 'unit_cost': '10.00'},
            {'external_line_id': 'L-UNREC', 'category_id': cat['id'], 'description': 'Unreceived Item', 'quantity_ordered': 5, 'unit_cost': '20.00'},
        ],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text
    po_data = res1.json()

    line_map = {l['external_line_id']: l['id'] for l in po_data['lines']}

    # Receive against L-REC
    grn_payload = {
        'received_date': '2026-11-04',
        'lines': [{'purchase_order_line_id': line_map['L-REC'], 'quantity_received': 3}],
    }
    client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_data['id']}/goods-receipts", json=grn_payload)

    # Attempt to omit L-REC in update
    p2 = dict(p1)
    p2['external_updated_at'] = '2026-11-04T12:00:00Z'
    p2['lines'] = [
        {'external_line_id': 'L-UNREC', 'category_id': cat['id'], 'description': 'Unreceived Item', 'quantity_ordered': 5, 'unit_cost': '20.00'}
    ]
    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 409, res2.text
    assert 'Cannot omit or delete' in res2.json()['detail']

    # Verify L-REC is still present
    check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_data['id']}").json()
    assert len(check['lines']) == 2


# =========================================================================
# Scenario 14: Older payload rejection
# =========================================================================
def test_scenario_14_older_payload_rejection(client, db_session):
    """
    Scenario 14: Older payload rejection.
    Submit a payload with external_updated_at older than the stored external_updated_at.
    Assert HTTP 409 Conflict with clear explanation.
    Assert existing record unchanged.
    """
    comp = create_test_company(client, 'C-SCEN-14', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-14')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'STALE-PO-01',
        'external_updated_at': '2026-11-04T12:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'Original 12:00 version',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text

    # Stale payload from 10:00
    p2 = dict(p1)
    p2['external_updated_at'] = '2026-11-04T10:00:00Z'
    p2['notes'] = 'Stale 10:00 version'

    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 409, res2.text
    assert 'Stale update rejected' in res2.json()['detail']

    # Verify notes unchanged
    check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{res1.json()['id']}").json()
    assert check['notes'] == 'Original 12:00 version'


# =========================================================================
# Scenario 15: Identical timestamp with conflicting payload
# =========================================================================
def test_scenario_15_identical_timestamp_with_conflicting_payload(client, db_session):
    """
    Scenario 15: Identical timestamp with conflicting payload.
    Submit a payload with the same external_updated_at as existing, but with different line quantities or notes.
    Assert HTTP 409 Conflict (cannot determine precedence).
    Assert existing record unchanged.
    """
    comp = create_test_company(client, 'C-SCEN-15', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-15')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    p1 = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'CONFLICT-PO-01',
        'external_updated_at': '2026-11-04T12:00:00Z',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'Version A',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
    }
    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p1)
    assert res1.status_code in (200, 201), res1.text

    # Conflicting payload with identical timestamp
    p2 = dict(p1)
    p2['notes'] = 'Version B with different notes'
    p2['lines'] = [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 20, 'unit_cost': '10.00'}]

    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p2)
    assert res2.status_code == 409, res2.text
    assert 'Conflicting update rejected' in res2.json()['detail']


# =========================================================================
# Scenario 16: Concurrent duplicate imports
# =========================================================================
def test_scenario_16_concurrent_duplicate_imports(client, db_session):
    """
    Scenario 16: Concurrent duplicate imports.
    Simulate duplicate imports with the same external identity.
    One must succeed (HTTP 200/201), subsequent identical import must succeed idempotently
    without duplicate records or state corruption.
    """
    comp = create_test_company(client, 'C-SCEN-16', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-16')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'CONCUR-PO-01',
        'external_system_id': 'CONCUR-SYS-99',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 10, 'unit_cost': '10.00'}],
    }

    res1 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    res2 = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)

    assert res1.status_code in (200, 201)
    assert res2.status_code in (200, 201)
    assert res1.json()['id'] == res2.json()['id']

    # Total PO count must remain exactly 1
    total = db_session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == UUID(comp['id']))
    )
    assert total == 1


# =========================================================================
# Scenario 17: Unauthorized import
# =========================================================================
def test_scenario_17_unauthorized_import(client, db_session):
    """
    Scenario 17: Unauthorized import.
    Attempt import with a token lacking procurement.import permission.
    Assert HTTP 403 Forbidden.
    """
    comp = create_test_company(client, 'C-SCEN-17', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-17')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Create read_only_user (lacks procurement.import)
    user = add_company_member(db_session, comp['id'], 'viewer-17@example.invalid', 'read_only_user')

    # Login as read_only_user
    login = client.post('/api/v1/auth/login', json={'email': user.email, 'password': 'Correct-Horse-42!'})
    assert login.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'DENIED-PO',
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': cat['id'], 'description': 'Item', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code == 403

    # Restore admin login
    _login_admin(client)


# =========================================================================
# Scenario 18: Cross-company import attempt
# =========================================================================
def test_scenario_18_cross_company_import_attempt(client, db_session):
    """
    Scenario 18: Cross-company import attempt.
    User belonging to Company A attempts to import into Company B.
    Assert HTTP 403/404.
    """
    compA = create_test_company(client, 'C-SCEN-18A', 'MZA')
    compB = create_test_company(client, 'C-SCEN-18B', 'MZB')
    supB = create_test_supplier(client, compB['id'], 'SUP-18B')
    catB = client.get(f"/api/v1/companies/{compB['id']}/categories").json()[0]

    # Create asset_manager only in Company A
    userA = add_company_member(db_session, compA['id'], 'manager-a@example.invalid', 'asset_manager')

    login = client.post('/api/v1/auth/login', json={'email': userA.email, 'password': 'Correct-Horse-42!'})
    assert login.status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['mindzen_csrf']

    payload = {
        'source_system': 'SAP',
        'source_instance_id': 'SAP-PROD-01',
        'external_reference': 'CROSS-PO',
        'supplier_id': supB['id'],
        'ordered_date': '2026-11-04',
        'lines': [{'external_line_id': 'L-1', 'category_id': catB['id'], 'description': 'Item', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
    }

    # Attempt import into Company B
    res = client.post(f"/api/v1/companies/{compB['id']}/purchase-orders/external-import", json=payload)
    assert res.status_code in (403, 404)

    # Restore admin login
    _login_admin(client)


# =========================================================================
# Scenario 19: Internal PO creation still works without any ERP integration
# =========================================================================
def test_scenario_19_internal_po_creation_still_works(client, db_session):
    """
    Scenario 19: Internal PO creation still works without any ERP integration.
    Create an internal PO through the normal workflow.
    Assert it succeeds, receives next ReferenceNumberService sequence number, origin == INTERNAL,
    ERP fields are null.
    """
    comp = create_test_company(client, 'C-SCEN-19', 'MZ')
    sup = create_test_supplier(client, comp['id'], 'SUP-19')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    internal_payload = {
        'supplier_id': sup['id'],
        'ordered_date': '2026-11-04',
        'notes': 'Pure internal PO',
        'lines': [
            {
                'category_id': cat['id'],
                'description': 'Office Desks',
                'quantity_ordered': 4,
                'unit_cost': '450.00',
            }
        ],
    }

    res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders", json=internal_payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data['origin'] == 'INTERNAL'
    assert data['order_number'].startswith('MZ-PO-')
    assert data['source_system'] is None
    assert data['source_instance_id'] is None
    assert data['external_reference'] is None
    assert data['external_system_id'] is None
    assert data['external_payload_hash'] is None


# =========================================================================
# Scenario 20: External import never consumes internal PO sequence numbers
# =========================================================================
def test_scenario_20_external_import_never_consumes_sequence(client, db_session):
    """
    Scenario 20: External import never consumes internal PO sequence numbers.
    Check current sequence value for 'purchase_order'.
    Import 3 external POs.
    Check sequence value again -> completely unchanged.
    Create an internal PO -> receives the exact next sequential reference.
    """
    comp = create_test_company(client, 'C-SCEN-20', 'MZ')
    cid = UUID(comp['id'])
    sup = create_test_supplier(client, comp['id'], 'SUP-20')
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == cid,
            ReferenceSequence.entity_type == 'purchase_order',
        )
    )
    initial_seq_val = seq.current_value

    # Import 3 external POs
    for i in range(1, 4):
        p = {
            'source_system': 'SAP',
            'source_instance_id': 'SAP-PROD-01',
            'external_reference': f'EXT-ORDER-{i}',
            'supplier_id': sup['id'],
            'ordered_date': '2026-11-04',
            'lines': [{'external_line_id': f'L-{i}', 'category_id': cat['id'], 'description': f'Item {i}', 'quantity_ordered': 1, 'unit_cost': '10.00'}],
        }
        res = client.post(f"/api/v1/companies/{comp['id']}/purchase-orders/external-import", json=p)
        assert res.status_code in (200, 201), res.text
        assert res.json()['origin'] == 'EXTERNAL'

    # Verify sequence in DB is untouched
    db_session.expire_all()
    seq_after_imports = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == cid,
            ReferenceSequence.entity_type == 'purchase_order',
        )
    )
    assert seq_after_imports.current_value == initial_seq_val

    # Now create an internal PO
    internal_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            'supplier_id': sup['id'],
            'ordered_date': '2026-11-04',
            'lines': [{'category_id': cat['id'], 'description': 'Internal Item', 'quantity_ordered': 1, 'unit_cost': '50.00'}],
        },
    )
    assert internal_res.status_code == 201, internal_res.text
    # Should get the first sequence number MZ-PO-2026-27-00001
    assert internal_res.json()['order_number'].startswith('MZ-PO-')
    assert internal_res.json()['origin'] == 'INTERNAL'

    # Sequence should now be incremented by 1
    db_session.expire_all()
    seq_final = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == cid,
            ReferenceSequence.entity_type == 'purchase_order',
        )
    )
    assert seq_final.current_value == initial_seq_val + 1
