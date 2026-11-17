"""Milestone 2C.3: Purchase Order Origin and External Reference Integration Tests.

Comprehensive PostgreSQL integration tests verifying:
1. Internal PO creation with automatic numbering.
2. Internal PO creation without ERP connectivity.
3. Manual PO reference rejection.
4. External provenance injection rejection on internal creation.
5. Valid origin constraints at database level.
6. Invalid origin rejection at database level.
7. Historical PO classification and reference preservation.
8. Existing GRN and PO line relationship preservation.
9. Company-level display order_number uniqueness.
10. External source identity uniqueness (external_system_id).
11. Different source instances with identical external references.
12. Tenant isolation.
"""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Asset,
    AssetCategory,
    Company,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)


def create_test_company_with_prefix(client, code: str, prefix: str):
    res = client.post(
        "/api/v1/companies",
        json={
            "code": prefix,
            "name": f"Company {code}",
            "number_prefix": prefix,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_supplier(client, company_id: str, code: str):
    res = client.post(
        f"/api/v1/companies/{company_id}/suppliers",
        json={"code": code, "name": f"Supplier {code}"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_internal_po_creation_with_automatic_numbering(client, db_session):
    """
    Test 1: Internal PO creation always sets origin='INTERNAL',
    allocates central order_number via ReferenceNumberService,
    and initializes all external provenance fields as None.
    """
    comp = create_test_company_with_prefix(client, "PO-ORIGIN-AUTO", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-ORIGIN-1")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [
                {
                    "category_id": cat_id,
                    "description": "Standard Workstation",
                    "quantity_ordered": 2,
                    "unit_cost": "1500.00",
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    po_data = res.json()

    assert po_data["origin"] == "INTERNAL"
    assert po_data["order_number"] == "MZ-PO-2026-27-00001"
    assert po_data["source_system"] is None
    assert po_data["source_instance_id"] is None
    assert po_data["external_reference"] is None
    assert po_data["external_system_id"] is None
    assert po_data["external_last_synced_at"] is None
    assert po_data["external_updated_at"] is None
    assert po_data["external_payload_hash"] is None

    # Verify direct DB record
    db_session.expire_all()
    db_po = db_session.get(PurchaseOrder, UUID(po_data["id"]))
    assert db_po is not None
    assert db_po.origin == "INTERNAL"
    assert db_po.order_number == "MZ-PO-2026-27-00001"
    assert db_po.source_system is None
    assert db_po.external_reference is None


def test_internal_po_creation_without_erp_connectivity(client, db_session):
    """
    Test 2: Internal PO creation is completely standalone and succeeds
    without any external ERP configuration, connector, or network connectivity.
    """
    comp = create_test_company_with_prefix(client, "PO-NO-ERP", "NOERP")
    sup = create_test_supplier(client, comp["id"], "SUP-NOERP")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Multiple orders created without any ERP configuration
    for i in range(1, 4):
        res = client.post(
            f"/api/v1/companies/{comp['id']}/purchase-orders",
            json={
                "supplier_id": sup["id"],
                "ordered_date": "2026-10-15",
                "lines": [{"category_id": cat_id, "description": f"Item {i}", "quantity_ordered": 1, "unit_cost": "100.00"}],
            },
        )
        assert res.status_code == 201
        assert res.json()["origin"] == "INTERNAL"
        assert res.json()["order_number"] == f"NOERP-PO-2026-27-0000{i}"


def test_manual_po_reference_rejection(client, db_session):
    """
    Test 3: Internal PO creation path rejects manual order_number input with HTTP 422.
    Manual numbering is strictly disallowed for internal POs.
    """
    comp = create_test_company_with_prefix(client, "PO-MANUAL-REJ", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-MANUAL")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "order_number": "CUSTOM-PO-100",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "50.00"}],
        },
    )
    assert res.status_code == 422
    assert "Manual purchase order numbers are not permitted for internal purchase orders" in str(res.json()["detail"])


def test_external_provenance_injection_rejection(client, db_session):
    """
    Test 4: External provenance fields cannot be injected through the internal PO creation endpoint.
    Extra fields return HTTP 422 Unprocessable Entity.
    """
    comp = create_test_company_with_prefix(client, "PO-INJECT-REJ", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-INJECT")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # 1. Attempt to inject origin
    res1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "origin": "EXTERNAL",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "50.00"}],
        },
    )
    assert res1.status_code == 422

    # 2. Attempt to inject source_system
    res2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "source_system": "SAP",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "50.00"}],
        },
    )
    assert res2.status_code == 422

    # 3. Attempt to inject external_reference
    res3 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "external_reference": "SAP-9999",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "50.00"}],
        },
    )
    assert res3.status_code == 422


def test_valid_origin_constraints_database_level(client, db_session):
    """
    Test 5: Database-level check constraints allow valid INTERNAL and EXTERNAL records.
    """
    comp = create_test_company_with_prefix(client, "PO-VALID-DB", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-VALID-DB")
    sup_id = UUID(sup["id"])

    # 1. Valid INTERNAL PO
    internal_po = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="MZ-PO-2026-27-00001",
        origin="INTERNAL",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(internal_po)
    db_session.commit()
    assert internal_po.id is not None

    # 2. Valid EXTERNAL PO with required provenance
    external_po = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SAP-PO-1001",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-PROD-EU",
        external_reference="PO-1001",
        external_system_id="SAP-DOC-GUID-1001",
        external_last_synced_at=datetime.now(timezone.utc),
        external_updated_at=datetime.now(timezone.utc),
        external_payload_hash="sha256_mock_hash",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(external_po)
    db_session.commit()
    assert external_po.id is not None


def test_invalid_origin_rejection_database_level(client, db_session):
    """
    Test 6: Database-level check constraints reject invalid origin or inconsistent fields.
    """
    comp = create_test_company_with_prefix(client, "PO-INVALID-DB", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-INV-DB")
    sup_id = UUID(sup["id"])

    # 1. Invalid origin value ('HYBRID')
    po_bad_origin = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="BAD-ORIGIN-01",
        origin="HYBRID",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_bad_origin)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "ck_purchase_orders_origin" in str(exc_info.value)
    db_session.rollback()

    # 2. INTERNAL PO with unexpected external provenance fields
    po_internal_with_ext = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="INTERNAL-WITH-EXT",
        origin="INTERNAL",
        source_system="SAP",  # Not allowed for INTERNAL
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_internal_with_ext)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "ck_purchase_orders_origin_fields" in str(exc_info.value)
    db_session.rollback()

    # 3. EXTERNAL PO missing source_system
    po_ext_missing_source = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="EXT-NO-SOURCE",
        origin="EXTERNAL",
        source_system=None,
        source_instance_id="SAP-1",
        external_reference="PO-1",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_ext_missing_source)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "ck_purchase_orders_origin_fields" in str(exc_info.value)
    db_session.rollback()

    # 4. EXTERNAL PO missing external_reference
    po_ext_missing_ref = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="EXT-NO-REF",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-1",
        external_reference=None,
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_ext_missing_ref)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert "ck_purchase_orders_origin_fields" in str(exc_info.value)
    db_session.rollback()


def test_historical_po_classification_and_reference_preservation(client, db_session):
    """
    Test 7: Historical POs are classified as origin='INTERNAL' and preserve their exact
    historical order_number and UUID without modifications.
    """
    comp = create_test_company_with_prefix(client, "PO-HIST-PRESERVE", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-HIST")
    sup_id = UUID(sup["id"])

    # Simulate existing historical POs
    hist_po = PurchaseOrder(
        id=UUID("00000000-1111-2222-3333-444444444444"),
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="LEGACY-PO-SPRINT-2026-01",
        origin="INTERNAL",
        ordered_date=date(2026, 9, 1),
    )
    db_session.add(hist_po)
    db_session.commit()

    # Query via API
    res = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{hist_po.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(hist_po.id)
    assert data["order_number"] == "LEGACY-PO-SPRINT-2026-01"
    assert data["origin"] == "INTERNAL"
    assert data["source_system"] is None


def test_existing_grn_and_po_line_relationship_preservation(client, db_session):
    """
    Test 8: Goods Receipt Notes and PO Lines link via UUIDs.
    Receiving goods against an internal PO preserves all relationship links and updates status.
    """
    comp = create_test_company_with_prefix(client, "PO-GRN-INTEG", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-GRN-1")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Laptops", "quantity_ordered": 5, "unit_cost": "1000.00"}],
        },
    )
    assert po_res.status_code == 201
    po = po_res.json()
    po_id = po["id"]
    line_id = po["lines"][0]["id"]

    # Receive 3 laptops (partial receipt)
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-10-16",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 3,
                    "quantity_rejected": 0,
                }
            ],
        },
    )
    assert grn_res.status_code == 201
    grn = grn_res.json()
    assert grn["purchase_order_id"] == po_id
    assert grn["lines"][0]["purchase_order_line_id"] == line_id
    assert len(grn["lines"][0]["assets"]) == 3

    # Verify PO status updated to partially_received
    po_updated = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_updated["status"] == "partially_received"
    assert po_updated["origin"] == "INTERNAL"


def test_company_level_order_number_uniqueness(client, db_session):
    """
    Test 9: order_number uniqueness at company level is strictly enforced.
    No two POs in the same company can share the same display order_number.
    """
    comp = create_test_company_with_prefix(client, "PO-UNIQ-COMP", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-UNIQ")
    sup_id = UUID(sup["id"])

    # 1. First PO
    po1 = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SHARED-PO-NUM-100",
        origin="INTERNAL",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po1)
    db_session.commit()

    # 2. Second PO with identical order_number in same company -> IntegrityError
    po2 = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SHARED-PO-NUM-100",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-1",
        external_reference="EXT-100",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert any(t in str(exc_info.value) for t in ["uq_purchase_orders_company_number", "UNIQUE constraint failed"])
    db_session.rollback()


def test_external_source_identity_uniqueness(client, db_session):
    """
    Test 10: External source document identity uniqueness.
    Within the same company and source instance, duplicate external_system_id
    or duplicate external_reference is rejected by partial unique indexes.
    """
    comp = create_test_company_with_prefix(client, "PO-EXT-UNIQ", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-EXT-UNIQ")
    sup_id = UUID(sup["id"])

    # 1. Insert external PO with external_system_id
    po1 = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SAP-PO-1001",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-EU",
        external_reference="PO-1001",
        external_system_id="SAP-SYS-ID-9999",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po1)
    db_session.commit()

    # 2. Duplicate external_system_id within same company and instance -> fails
    po1_dup = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SAP-PO-1001-DIFF",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-EU",
        external_reference="PO-1002",
        external_system_id="SAP-SYS-ID-9999",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po1_dup)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert any(t in str(exc_info.value) for t in ["uq_purchase_orders_company_source_ext_id", "UNIQUE constraint failed"])
    db_session.rollback()

    # 3. Test external_reference uniqueness when external_system_id is NULL
    po_no_sys_id1 = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="TALLY-PO-501",
        origin="EXTERNAL",
        source_system="TALLY",
        source_instance_id="TALLY-DELHI",
        external_reference="TALLY-501",
        external_system_id=None,
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_no_sys_id1)
    db_session.commit()

    # Duplicate external_reference for same company, source, instance with NULL external_system_id -> fails
    po_no_sys_id2 = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="TALLY-PO-501-RETRY",
        origin="EXTERNAL",
        source_system="TALLY",
        source_instance_id="TALLY-DELHI",
        external_reference="TALLY-501",
        external_system_id=None,
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_no_sys_id2)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert any(t in str(exc_info.value) for t in ["uq_purchase_orders_company_source_ext_ref", "UNIQUE constraint failed"])
    db_session.rollback()


def test_different_source_instances_with_identical_external_references(client, db_session):
    """
    Test 11: Two different source instances within the same company can supply the same external_reference
    (e.g. 'PO-9000' in SAP-US vs 'PO-9000' in SAP-EU).
    Both are permitted by the external index because source_instance_id differs,
    and distinct display order_numbers preserve company-level uniqueness.
    """
    comp = create_test_company_with_prefix(client, "PO-DIFF-INST", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-DIFF-INST")
    sup_id = UUID(sup["id"])

    # 1. Order from SAP-US
    po_us = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SAP-US-PO-9000",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-US",
        external_reference="PO-9000",
        external_system_id="DOC-US-9000",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_us)
    db_session.commit()

    # 2. Order from SAP-EU with the exact same external_reference 'PO-9000'
    po_eu = PurchaseOrder(
        company_id=comp_id,
        supplier_id=sup_id,
        order_number="SAP-EU-PO-9000",
        origin="EXTERNAL",
        source_system="SAP",
        source_instance_id="SAP-EU",
        external_reference="PO-9000",
        external_system_id="DOC-EU-9000",
        ordered_date=date(2026, 10, 15),
    )
    db_session.add(po_eu)
    db_session.commit()

    assert po_us.id != po_eu.id
    assert po_us.external_reference == po_eu.external_reference == "PO-9000"
    assert po_us.source_instance_id != po_eu.source_instance_id


def test_tenant_isolation_po_origin(client, db_session):
    """
    Test 12: Tenant isolation ensures company A cannot read or access purchase orders of company B,
    regardless of whether they are internal or external.
    """
    comp_a = create_test_company_with_prefix(client, "PO-TENANT-A", "MZA")
    comp_b = create_test_company_with_prefix(client, "PO-TENANT-B", "MZB")
    sup_a = create_test_supplier(client, comp_a["id"], "SUP-TA")
    sup_b = create_test_supplier(client, comp_b["id"], "SUP-TB")
    cat_a = client.get(f"/api/v1/companies/{comp_a['id']}/categories").json()[0]["id"]
    cat_b = client.get(f"/api/v1/companies/{comp_b['id']}/categories").json()[0]["id"]

    po_a = client.post(
        f"/api/v1/companies/{comp_a['id']}/purchase-orders",
        json={
            "supplier_id": sup_a["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_a, "description": "Asset A", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    ).json()

    po_b = client.post(
        f"/api/v1/companies/{comp_b['id']}/purchase-orders",
        json={
            "supplier_id": sup_b["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_b, "description": "Asset B", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    ).json()

    # Company A cannot see Company B's PO
    get_cross = client.get(f"/api/v1/companies/{comp_a['id']}/purchase-orders/{po_b['id']}")
    assert get_cross.status_code == 404

    # Company B cannot see Company A's PO
    get_cross_b = client.get(f"/api/v1/companies/{comp_b['id']}/purchase-orders/{po_a['id']}")
    assert get_cross_b.status_code == 404

