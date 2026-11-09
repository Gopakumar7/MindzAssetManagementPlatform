"""Tests for Milestone 2C.1.1: Purchase Order Reference Immutability and Lifecycle Integrity.

Requirements:
- Attempted PO reference modification rejected with HTTP 409 Conflict.
- Updating other PO fields without changing the reference succeeds.
- Manual reference policy (managed prefix collision rejected with 422, central allocation when omitted).
- Historical reference preservation.
- Cancellation and reference non-reuse.
- Deletion restrictions for issued POs (HTTP 409 Conflict).
- Deletion restrictions for POs with goods receipts (HTTP 409 Conflict).
- Audit event preservation.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.models import AuditEvent, GoodsReceipt, PurchaseOrder, PurchaseOrderLine


def create_test_company_with_prefix(client, code: str, prefix: str):
    res = client.post(
        "/api/v1/companies",
        json={
            "code": code,
            "name": f"Company {code}",
            "number_prefix": prefix,
            "is_active": True,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_supplier(client, company_id: str, code: str = "SUP-1"):
    res = client.post(
        f"/api/v1/companies/{company_id}/suppliers",
        json={"code": code, "name": f"Supplier {code}"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_purchase_order_reference_immutability_on_update(client, db_session):
    """
    Section A: Once a PO reference has been issued and committed, it must be immutable.
    An ordinary PUT/PATCH request attempting to change the reference must be rejected with HTTP 409 Conflict.
    """
    comp = create_test_company_with_prefix(client, "PO-IMMUTABLE", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-IMM")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # 1. Create initial PO with centrally allocated reference
    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Laptops", "quantity_ordered": 2, "unit_cost": "1500.00"}],
        },
    )
    assert res.status_code == 201, res.text
    order = res.json()
    order_id = order["id"]
    original_number = order["order_number"]
    assert original_number == "MZ-PO-2026-27-00001"

    # 2. Attempt to modify order_number via PUT to a managed-style number -> HTTP 409 Conflict
    put_collide = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}",
        json={
            "supplier_id": sup["id"],
            "order_number": "MZ-PO-2026-27-00999",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Laptops", "quantity_ordered": 2, "unit_cost": "1500.00"}],
        },
    )
    assert put_collide.status_code == 409
    assert "is immutable and cannot be modified" in put_collide.json()["detail"]

    # 3. Attempt to modify order_number via PUT to an external number -> HTTP 409 Conflict
    put_ext = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}",
        json={
            "supplier_id": sup["id"],
            "order_number": "EXT-CUSTOM-PO-1",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Laptops", "quantity_ordered": 2, "unit_cost": "1500.00"}],
        },
    )
    assert put_ext.status_code == 409
    assert "is immutable and cannot be modified" in put_ext.json()["detail"]

    # 4. Attempt to modify order_number via PATCH -> HTTP 409 Conflict
    patch_res = client.patch(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}",
        json={
            "order_number": "PATCHED-PO-NUMBER",
            "lines": [{"category_id": cat_id, "description": "Laptops", "quantity_ordered": 2, "unit_cost": "1500.00"}],
        },
    )
    assert patch_res.status_code == 409
    assert "is immutable and cannot be modified" in patch_res.json()["detail"]

    # 5. Confirm database record was not modified
    db_session.expire_all()
    db_order = db_session.get(PurchaseOrder, UUID(order_id))
    assert db_order.order_number == original_number


def test_update_unrelated_po_fields_succeeds(client, db_session):
    """
    Section A: Updating unrelated PO fields must continue to work when order_number
    is unchanged or omitted.
    """
    comp = create_test_company_with_prefix(client, "PO-UPDATE-FIELDS", "MZ")
    sup1 = create_test_supplier(client, comp["id"], "SUP-UF1")
    sup2 = create_test_supplier(client, comp["id"], "SUP-UF2")
    categories = client.get(f"/api/v1/companies/{comp['id']}/categories").json()
    cat1, cat2 = categories[0]["id"], categories[1]["id"]

    # Create initial PO
    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup1["id"],
            "ordered_date": "2026-10-15",
            "expected_date": "2026-10-25",
            "notes": "Original notes",
            "lines": [{"category_id": cat1, "description": "Monitors", "quantity_ordered": 5, "unit_cost": "250.00"}],
        },
    )
    assert res.status_code == 201
    order_id = res.json()["id"]
    po_num = res.json()["order_number"]

    # 1. Update with unchanged order_number explicitly passed -> 200 OK
    put_same = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}",
        json={
            "supplier_id": sup2["id"],
            "order_number": po_num,
            "ordered_date": "2026-10-16",
            "expected_date": "2026-11-05",
            "notes": "Updated notes via PUT",
            "lines": [
                {"category_id": cat1, "description": "Monitors", "quantity_ordered": 5, "unit_cost": "250.00"},
                {"category_id": cat2, "description": "HDMI Cables", "quantity_ordered": 10, "unit_cost": "15.00"},
            ],
        },
    )
    assert put_same.status_code == 200, put_same.text
    updated = put_same.json()
    assert updated["order_number"] == po_num
    assert updated["supplier_id"] == sup2["id"]
    assert updated["notes"] == "Updated notes via PUT"
    assert len(updated["lines"]) == 2

    # 2. Update with order_number omitted (None) -> 200 OK
    patch_omit = client.patch(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}",
        json={
            "notes": "Updated notes via PATCH",
            "lines": [{"category_id": cat1, "description": "Monitors", "quantity_ordered": 5, "unit_cost": "250.00"}],
        },
    )
    assert patch_omit.status_code == 200, patch_omit.text
    assert patch_omit.json()["order_number"] == po_num
    assert patch_omit.json()["notes"] == "Updated notes via PATCH"


def test_deletion_restrictions_issued_purchase_orders(client, db_session):
    """
    Section C: Issued or approved POs cannot be physically deleted through ordinary operations.
    DELETE request returns HTTP 409 Conflict.
    """
    comp = create_test_company_with_prefix(client, "PO-DEL-RESTRICT", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-DEL")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Hardware", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert res.status_code == 201
    po = res.json()
    order_id = po["id"]
    po_num = po["order_number"]

    # Attempt deletion of issued PO -> 409 Conflict
    del_res = client.delete(f"/api/v1/companies/{comp['id']}/purchase-orders/{order_id}")
    assert del_res.status_code == 409
    assert f'Purchase order "{po_num}" has been issued (status: "open") and cannot be deleted' in del_res.json()["detail"]

    # Verify PO still exists in DB
    db_session.expire_all()
    assert db_session.get(PurchaseOrder, UUID(order_id)) is not None


def test_deletion_restrictions_pos_with_goods_receipts(client, db_session):
    """
    Section C: POs with associated goods receipts cannot be deleted.
    DELETE request returns HTTP 409 Conflict.
    """
    comp = create_test_company_with_prefix(client, "PO-DEL-RECEIPT", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-RCPT")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Create PO
    order = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Keyboards", "quantity_ordered": 5, "unit_cost": "50.00"}],
        },
    ).json()
    line_id = order["lines"][0]["id"]

    # Receive partial goods
    rcv_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order['id']}/goods-receipts",
        json={
            "received_date": "2026-10-16",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2, "quantity_rejected": 0}],
        },
    )
    assert rcv_res.status_code == 201

    # Attempt deletion of PO with goods receipts -> 409 Conflict
    del_res = client.delete(f"/api/v1/companies/{comp['id']}/purchase-orders/{order['id']}")
    assert del_res.status_code == 409
    assert "Cannot delete purchase order because goods have already been received against it" in del_res.json()["detail"]

    # Foreign key check: verify GoodsReceipt exists in DB
    db_session.expire_all()
    gr = db_session.scalar(select(GoodsReceipt).where(GoodsReceipt.purchase_order_id == UUID(order["id"])))
    assert gr is not None


def test_deletion_non_existent_po_returns_404(client):
    """
    DELETE request on a non-existent PO returns HTTP 404 Not Found.
    """
    comp = create_test_company_with_prefix(client, "PO-DEL-404", "MZ")
    fake_id = "00000000-0000-0000-0000-000000000000"
    del_res = client.delete(f"/api/v1/companies/{comp['id']}/purchase-orders/{fake_id}")
    assert del_res.status_code == 404


def test_audit_event_preservation_on_po_lifecycle(client, db_session):
    """
    Section D: Audit event creation is preserved and accurate on PO creation and updates.
    """
    comp = create_test_company_with_prefix(client, "PO-AUDIT", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-AUD")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # 1. Create PO
    order = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Audit Item", "quantity_ordered": 3, "unit_cost": "200.00"}],
        },
    ).json()

    db_session.expire_all()
    created_audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.entity_type == "PurchaseOrder",
            AuditEvent.action == "purchase_order_created",
            AuditEvent.entity_id == str(order["id"]),
        )
    )
    assert created_audit is not None
    assert created_audit.changes["order_number"] == order["order_number"]

    # 2. Update PO fields
    client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order['id']}",
        json={
            "supplier_id": sup["id"],
            "order_number": order["order_number"],
            "notes": "Audited modification",
            "lines": [{"category_id": cat_id, "description": "Audit Item", "quantity_ordered": 4, "unit_cost": "200.00"}],
        },
    )

    db_session.expire_all()
    updated_audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.entity_type == "PurchaseOrder",
            AuditEvent.action == "purchase_order_updated",
            AuditEvent.entity_id == str(order["id"]),
        )
    )
    assert updated_audit is not None
    assert updated_audit.changes["order_number"] == order["order_number"]

    # 3. Rejected modification (409) does NOT create an updated audit event
    audit_count_before = len(db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.entity_type == "PurchaseOrder",
            AuditEvent.action == "purchase_order_updated",
        )
    ).all())

    client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{order['id']}",
        json={"order_number": "NEW-COLLISION-NUM", "lines": [{"category_id": cat_id, "description": "X", "quantity_ordered": 1, "unit_cost": "1.00"}]},
    )

    db_session.expire_all()
    audit_count_after = len(db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.entity_type == "PurchaseOrder",
            AuditEvent.action == "purchase_order_updated",
        )
    ).all())
    assert audit_count_after == audit_count_before

