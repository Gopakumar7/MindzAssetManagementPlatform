"""Milestone 2C.3.1: External PO Line Identity and Purchase Order Update Safety Tests.

Comprehensive integration tests verifying:
1. Duplicate external_line_id within the same PO is rejected by partial unique index.
2. Same external_line_id across different POs is allowed.
3. Multiple internal lines with NULL external_line_id are allowed within the same PO.
4. Duplicate line_number within the same PO is rejected by partial unique index.
5. Same line_number across different POs is allowed.
6. Updating header fields (notes, expected_date) after partial receipt succeeds.
7. Attempting to change PO reference (order_number) is rejected with HTTP 409 Conflict.
8. Attempting to delete a line with receipt history is rejected with HTTP 409 Conflict.
9. Attempting to reduce ordered quantity below received quantity is rejected with HTTP 422.
10. Attempting to change category on a line with receipt history is rejected with HTTP 409 Conflict.
11. Attempting to change supplier_id when receipts exist is rejected with HTTP 409 Conflict.
12. Preserving PO line UUIDs and existing GRN relationships across safe updates.
13. Safe line additions and updates on partially received POs correctly recalculate status.
14. Complete transaction rollback when update validation fails.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Asset,
    AssetCategory,
    AuditEvent,
    Company,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)


def create_test_company(client, code: str, prefix: str):
    res = client.post(
        "/api/v1/companies",
        json={
            "code": code,
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


# =========================================================================
# Part A: External PO Line Identity Database Constraints
# =========================================================================


def test_duplicate_external_line_id_same_po_rejected_at_db_level(client, db_session):
    """
    Partial unique index uq_purchase_order_lines_order_ext_line rejects
    duplicate external_line_id within the same Purchase Order.
    """
    comp = create_test_company(client, "LINE-DUP-1", "LD1")
    sup = create_test_supplier(client, comp["id"], "SUP-LD1")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LD1-PO-001",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add(po)
    db_session.flush()

    line1 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="Line 1",
        quantity_ordered=5,
        unit_cost=Decimal("100.00"),
        external_line_id="ERP-LINE-100",
    )
    db_session.add(line1)
    db_session.flush()

    line2 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="Line 2 duplicate external id",
        quantity_ordered=3,
        unit_cost=Decimal("200.00"),
        external_line_id="ERP-LINE-100",  # Duplicate in same PO
    )
    db_session.add(line2)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert any(t in str(exc_info.value) for t in ["uq_purchase_order_lines_order_ext_line", "UNIQUE constraint failed"])
    db_session.rollback()


def test_same_external_line_id_different_pos_allowed(client, db_session):
    """
    Different Purchase Orders may use the same external_line_id without conflict.
    """
    comp = create_test_company(client, "LINE-DIFF-PO", "LDP")
    sup = create_test_supplier(client, comp["id"], "SUP-LDP")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po1 = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LDP-PO-001",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    po2 = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LDP-PO-002",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add_all([po1, po2])
    db_session.flush()

    line1 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po1.id,
        category_id=UUID(cat["id"]),
        description="PO1 Line",
        quantity_ordered=5,
        unit_cost=Decimal("100.00"),
        external_line_id="COMMON-EXT-LINE-01",
    )
    line2 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po2.id,
        category_id=UUID(cat["id"]),
        description="PO2 Line with identical external_line_id",
        quantity_ordered=10,
        unit_cost=Decimal("150.00"),
        external_line_id="COMMON-EXT-LINE-01",
    )
    db_session.add_all([line1, line2])
    db_session.flush()

    assert line1.id is not None
    assert line2.id is not None
    assert line1.external_line_id == line2.external_line_id
    db_session.commit()


def test_multiple_internal_lines_with_null_external_line_id_allowed(client, db_session):
    """
    Internal PO lines have external_line_id = NULL. Multiple lines with NULL
    external_line_id must coexist in the same PO without violating the index.
    """
    comp = create_test_company(client, "LINE-NULL-EXT", "LNE")
    sup = create_test_supplier(client, comp["id"], "SUP-LNE")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LNE-PO-001",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add(po)
    db_session.flush()

    lines = [
        PurchaseOrderLine(
            company_id=UUID(comp["id"]),
            purchase_order_id=po.id,
            category_id=UUID(cat["id"]),
            description=f"Internal Line {i}",
            quantity_ordered=i,
            unit_cost=Decimal("10.00"),
            external_line_id=None,
            line_number=None,
        )
        for i in range(1, 6)
    ]
    db_session.add_all(lines)
    db_session.flush()

    db_session.expire_all()
    queried_lines = db_session.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)
    ).all()
    assert len(queried_lines) == 5
    for ql in queried_lines:
        assert ql.external_line_id is None
        assert ql.line_number is None


def test_duplicate_line_number_same_po_rejected_at_db_level(client, db_session):
    """
    Partial unique index uq_purchase_order_lines_order_line_num rejects
    duplicate line_number within the same Purchase Order.
    """
    comp = create_test_company(client, "LINE-NUM-DUP", "LND")
    sup = create_test_supplier(client, comp["id"], "SUP-LND")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LND-PO-001",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add(po)
    db_session.flush()

    line1 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="Line 1",
        quantity_ordered=5,
        unit_cost=Decimal("100.00"),
        line_number=1,
    )
    db_session.add(line1)
    db_session.flush()

    line2 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="Line 2 with duplicate line_number",
        quantity_ordered=3,
        unit_cost=Decimal("200.00"),
        line_number=1,  # Duplicate in same PO
    )
    db_session.add(line2)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    assert any(t in str(exc_info.value) for t in ["uq_purchase_order_lines_order_line_num", "UNIQUE constraint failed"])
    db_session.rollback()


def test_same_line_number_different_pos_allowed(client, db_session):
    """
    Different Purchase Orders may use the same line_number (e.g. line 1, 2, 3)
    without conflict.
    """
    comp = create_test_company(client, "LINE-NUM-DIFF", "LNDF")
    sup = create_test_supplier(client, comp["id"], "SUP-LNDF")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po1 = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LNDF-PO-001",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    po2 = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="LNDF-PO-002",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add_all([po1, po2])
    db_session.flush()

    line1 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po1.id,
        category_id=UUID(cat["id"]),
        description="PO1 Line 1",
        quantity_ordered=5,
        unit_cost=Decimal("100.00"),
        line_number=1,
    )
    line2 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po2.id,
        category_id=UUID(cat["id"]),
        description="PO2 Line 1",
        quantity_ordered=10,
        unit_cost=Decimal("150.00"),
        line_number=1,
    )
    db_session.add_all([line1, line2])
    db_session.flush()

    assert line1.id is not None
    assert line2.id is not None
    assert line1.line_number == 1
    assert line2.line_number == 1
    db_session.commit()


# =========================================================================
# Part B: Granular Purchase Order Update Safety
# =========================================================================


def test_update_notes_and_expected_date_after_partial_receipt_succeeds(client, db_session):
    """
    Granular update allows editing notes and expected_date on a partially
    received Purchase Order while preserving order status and line details.
    """
    comp = create_test_company(client, "UPD-HEADER", "UH")
    sup = create_test_supplier(client, comp["id"], "SUP-UH")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # 1. Create PO
    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "expected_date": "2026-11-10",
            "notes": "Initial delivery notes",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Enterprise Server",
                    "quantity_ordered": 5,
                    "unit_cost": "2500.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_data = po_res.json()
    po_id = po_data["id"]
    po_line_id = po_data["lines"][0]["id"]

    # 2. Receive 2 of 5
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DEL-UH-1",
            "lines": [
                {
                    "purchase_order_line_id": po_line_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SRV-01", "SRV-02"],
                }
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text

    # Verify PO is partially_received
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders").json()[0]
    assert po_check["status"] == "partially_received"

    # 3. Update notes and expected_date
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "expected_date": "2026-11-25",
            "notes": "Updated delivery instructions: staggered shipment",
            "lines": [
                {
                    "id": po_line_id,
                    "category_id": cat["id"],
                    "description": "Enterprise Server",
                    "quantity_ordered": 5,
                    "unit_cost": "2500.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert updated["expected_date"] == "2026-11-25"
    assert updated["notes"] == "Updated delivery instructions: staggered shipment"
    assert updated["status"] == "partially_received"
    assert updated["lines"][0]["id"] == po_line_id
    assert updated["lines"][0]["quantity_received"] == 2
    assert updated["lines"][0]["quantity_remaining"] == 3


def test_update_cannot_change_order_number(client, db_session):
    """
    Attempting to modify order_number must be rejected with HTTP 409 Conflict
    due to reference immutability.
    """
    comp = create_test_company(client, "UPD-NO-REF", "UNR")
    sup = create_test_supplier(client, comp["id"], "SUP-UNR")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Monitor",
                    "quantity_ordered": 10,
                    "unit_cost": "200.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]

    # Attempt to change order_number
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "order_number": "FORGED-ORDER-NUMBER",
            "lines": [
                {
                    "id": po_data["lines"][0]["id"],
                    "category_id": cat["id"],
                    "description": "Monitor",
                    "quantity_ordered": 10,
                    "unit_cost": "200.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 409
    assert "immutable and cannot be modified" in upd_res.json()["detail"]


def test_update_cannot_delete_line_with_receipt_history(client, db_session):
    """
    Attempting to remove a purchase order line that already has goods received
    must be rejected with HTTP 409 Conflict.
    """
    comp = create_test_company(client, "UPD-NO-DEL-LN", "UNDL")
    sup = create_test_supplier(client, comp["id"], "SUP-UNDL")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Line A - With Receipts",
                    "quantity_ordered": 4,
                    "unit_cost": "100.00",
                },
                {
                    "category_id": cat["id"],
                    "description": "Line B - Without Receipts",
                    "quantity_ordered": 2,
                    "unit_cost": "50.00",
                },
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line_a_id = po_data["lines"][0]["id"]
    line_b_id = po_data["lines"][1]["id"]

    # Receive against Line A
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-1",
            "lines": [
                {
                    "purchase_order_line_id": line_a_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-A1", "SN-A2"],
                }
            ],
        },
    )

    # Attempt to update PO omitting Line A (trying to delete Line A)
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {
                    "id": line_b_id,
                    "category_id": cat["id"],
                    "description": "Line B - Only",
                    "quantity_ordered": 2,
                    "unit_cost": "50.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 409
    assert "because goods have already been received against it" in upd_res.json()["detail"]


def test_update_cannot_reduce_ordered_quantity_below_received_quantity(client, db_session):
    """
    Attempting to reduce quantity_ordered below the already received quantity
    must be rejected with HTTP 422 Unprocessable Entity.
    """
    comp = create_test_company(client, "UPD-QTY-BELOW", "UQB")
    sup = create_test_supplier(client, comp["id"], "SUP-UQB")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Laptops",
                    "quantity_ordered": 5,
                    "unit_cost": "1000.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line_id = po_data["lines"][0]["id"]

    # Receive 3 laptops
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-UQB",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 3,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-UQB-1", "SN-UQB-2", "SN-UQB-3"],
                }
            ],
        },
    )

    # Attempt to reduce quantity_ordered to 2 (below 3)
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {
                    "id": line_id,
                    "category_id": cat["id"],
                    "description": "Laptops",
                    "quantity_ordered": 2,  # < 3 received
                    "unit_cost": "1000.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 422
    assert "because 3 items have already been received" in upd_res.json()["detail"]


def test_update_cannot_change_category_on_line_with_receipt_history(client, db_session):
    """
    Attempting to change category_id on a line with goods receipts must be
    rejected with HTTP 409 Conflict.
    """
    comp = create_test_company(client, "UPD-CAT-CHG", "UCC")
    sup = create_test_supplier(client, comp["id"], "SUP-UCC")
    cats = client.get(f"/api/v1/companies/{comp['id']}/categories").json()
    cat1_id = cats[0]["id"]

    # Create a second category
    cat2_res = client.post(
        f"/api/v1/companies/{comp['id']}/categories",
        json={"code": "SECOND-CAT", "name": "Second Category"},
    )
    assert cat2_res.status_code == 201
    cat2_id = cat2_res.json()["id"]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat1_id,
                    "description": "Category Item",
                    "quantity_ordered": 4,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line_id = po_data["lines"][0]["id"]

    # Receive against line
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-UCC",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 1,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-UCC-1"],
                }
            ],
        },
    )

    # Attempt to change category_id
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {
                    "id": line_id,
                    "category_id": cat2_id,  # Changed category
                    "description": "Category Item",
                    "quantity_ordered": 4,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 409
    assert "because goods have already been received against it" in upd_res.json()["detail"]


def test_update_cannot_change_supplier_if_receipts_exist(client, db_session):
    """
    Attempting to change supplier_id when goods receipts exist must be
    rejected with HTTP 409 Conflict.
    """
    comp = create_test_company(client, "UPD-SUP-CHG", "USC")
    sup1 = create_test_supplier(client, comp["id"], "SUP-USC-1")
    sup2 = create_test_supplier(client, comp["id"], "SUP-USC-2")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup1["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Supplier Item",
                    "quantity_ordered": 2,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line_id = po_data["lines"][0]["id"]

    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-USC",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 1,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-USC-1"],
                }
            ],
        },
    )

    # Attempt to change supplier
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup2["id"],  # Changed supplier
            "lines": [
                {
                    "id": line_id,
                    "category_id": cat["id"],
                    "description": "Supplier Item",
                    "quantity_ordered": 2,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert upd_res.status_code == 409
    assert "Cannot change supplier because goods have already been received" in upd_res.json()["detail"]


def test_update_preserves_line_uuids_and_grn_relationships(client, db_session):
    """
    In-place updates preserve the UUID of existing lines, ensuring that foreign keys
    and goods receipt line relationships remain completely intact.
    """
    comp = create_test_company(client, "UPD-PRESERVE-UUID", "UPU")
    sup = create_test_supplier(client, comp["id"], "SUP-UPU")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Preserved Line 1",
                    "quantity_ordered": 5,
                    "unit_cost": "100.00",
                },
                {
                    "category_id": cat["id"],
                    "description": "Preserved Line 2",
                    "quantity_ordered": 10,
                    "unit_cost": "20.00",
                },
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line1_id = po_data["lines"][0]["id"]
    line2_id = po_data["lines"][1]["id"]

    # Receive against Line 1
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-UPU",
            "lines": [
                {
                    "purchase_order_line_id": line1_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-UPU-1", "SN-UPU-2"],
                }
            ],
        },
    )
    assert grn_res.status_code == 201
    grn_line_id = grn_res.json()["lines"][0]["id"]

    # Update PO: update line 1 description & unit cost, line 2 quantity
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "notes": "Updated line details",
            "lines": [
                {
                    "id": line1_id,
                    "category_id": cat["id"],
                    "description": "Preserved Line 1 - Refined Description",
                    "quantity_ordered": 5,
                    "unit_cost": "105.00",
                },
                {
                    "id": line2_id,
                    "category_id": cat["id"],
                    "description": "Preserved Line 2",
                    "quantity_ordered": 8,  # Safe reduction (0 received)
                    "unit_cost": "20.00",
                },
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated_lines = upd_res.json()["lines"]

    # Verify line UUIDs were preserved
    assert updated_lines[0]["id"] == line1_id
    assert updated_lines[0]["description"] == "Preserved Line 1 - Refined Description"
    assert updated_lines[0]["unit_cost"] == "105.00"
    assert updated_lines[0]["quantity_received"] == 2

    assert updated_lines[1]["id"] == line2_id
    assert updated_lines[1]["quantity_ordered"] == 8

    # Verify database relationship and GRN line integrity
    db_session.expire_all()
    grn_line = db_session.get(GoodsReceiptLine, UUID(grn_line_id))
    assert grn_line is not None
    assert str(grn_line.purchase_order_line_id) == line1_id


def test_safe_line_updates_and_additions_recalculate_status(client, db_session):
    """
    Updating lines or adding new lines to a partially received PO is supported
    and correctly recalculates status ('open', 'partially_received', 'received').
    """
    comp = create_test_company(client, "UPD-STATUS-RECALC", "USR")
    sup = create_test_supplier(client, comp["id"], "SUP-USR")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Line 1",
                    "quantity_ordered": 2,
                    "unit_cost": "500.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line1_id = po_data["lines"][0]["id"]

    # Fully receive line 1 (2 of 2) -> status becomes 'received'
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-USR-1",
            "lines": [
                {
                    "purchase_order_line_id": line1_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-1", "SN-2"],
                }
            ],
        },
    )
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders").json()[0]
    assert po_check["status"] == "received"

    # Add a new line (Line 2 qty 3) -> status recalculates to 'partially_received'
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {
                    "id": line1_id,
                    "category_id": cat["id"],
                    "description": "Line 1",
                    "quantity_ordered": 2,
                    "unit_cost": "500.00",
                },
                {
                    "category_id": cat["id"],
                    "description": "Line 2 - Added",
                    "quantity_ordered": 3,
                    "unit_cost": "300.00",
                },
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert updated["status"] == "partially_received"
    assert len(updated["lines"]) == 2

    line2_id = [l["id"] for l in updated["lines"] if l["id"] != line1_id][0]

    # Receive the remaining 3 on Line 2 -> status becomes 'received' again
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-06",
            "delivery_reference": "DN-USR-2",
            "lines": [
                {
                    "purchase_order_line_id": line2_id,
                    "quantity_received": 3,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-3", "SN-4", "SN-5"],
                }
            ],
        },
    )
    po_final = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders").json()[0]
    assert po_final["status"] == "received"


def test_transaction_rollback_on_update_validation_failure(client, db_session):
    """
    When an update fails validation (e.g. attempting to reduce quantity below received),
    the database transaction rolls back completely. Neither line quantities, header fields,
    nor audit records are committed.
    """
    comp = create_test_company(client, "UPD-ROLLBACK", "URB")
    sup = create_test_supplier(client, comp["id"], "SUP-URB")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "notes": "Original Notes",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Rollback Test Item",
                    "quantity_ordered": 5,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    line_id = po_data["lines"][0]["id"]

    # Receive 2
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-05",
            "delivery_reference": "DN-URB",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["SN-URB-1", "SN-URB-2"],
                }
            ],
        },
    )

    # Count audit events before failed update
    db_session.expire_all()
    events_before = len(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.company_id == UUID(comp["id"]))
        ).all()
    )

    # Attempt invalid update with changed notes and invalid quantity
    fail_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "notes": "Attempted Note Change That Should Rollback",
            "lines": [
                {
                    "id": line_id,
                    "category_id": cat["id"],
                    "description": "Rollback Test Item",
                    "quantity_ordered": 1,  # Invalid: 1 < 2 received
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    assert fail_res.status_code == 422

    # Verify rollback: notes unchanged, quantity unchanged, no new audit events
    db_session.expire_all()
    db_po = db_session.get(PurchaseOrder, UUID(po_id))
    assert db_po.notes == "Original Notes"

    db_line = db_session.get(PurchaseOrderLine, UUID(line_id))
    assert db_line.quantity_ordered == 5

    events_after = len(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.company_id == UUID(comp["id"]))
        ).all()
    )
    assert events_after == events_before

