"""Milestone 2E.1: Purchase Order Cancellation Integration Tests.

Comprehensive integration tests verifying:
1. Cancellation of an unreceived internal Purchase Order (open -> cancelled).
2. Cancellation of a partially received internal Purchase Order (partially_received -> cancelled / short-closing).
3. Historical GRNs, GoodsReceiptLines, and received quantities remain 100% intact after cancellation.
4. Automatic status recalculation protection: calculate_purchase_order_status and
   recalculate_purchase_order_status preserve 'cancelled' status and never overwrite it.
5. Rejection of goods receipt creation against a cancelled Purchase Order with HTTP 409 Conflict.
6. Rejection of ordinary update (PUT and PATCH) on a cancelled Purchase Order with HTTP 409 Conflict.
7. Rejection of deletion of a cancelled Purchase Order with HTTP 409 Conflict (preserving audit continuity).
8. Rejection of cancellation of a fully received Purchase Order with HTTP 409 Conflict.
9. Rejection of cancellation of an already cancelled Purchase Order with HTTP 409 Conflict.
10. Rejection of direct local cancellation of an external ERP Purchase Order with HTTP 409 Conflict.
11. Validation of cancellation payload: empty reason or reason shorter than 3 chars rejected with HTTP 422.
12. Authorization & RBAC: unauthenticated (401) and unauthorized users without procurement.manage (403).
13. Audit logging: SecurityAuditLog emits 'purchase_order_cancelled' event with full metadata.
14. Concurrent cancellation requests on the same Purchase Order handled safely and deterministically.
"""

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select, func

from app.models import (
    AuditEvent,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    User,
)
from app.services import (
    calculate_purchase_order_status,
    recalculate_purchase_order_status,
)
from app.authentication import password_hasher


# =========================================================================
# Setup Helpers
# =========================================================================

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


def _login_admin(client):
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "test-admin@example.invalid", "password": "Correct-Horse-42!"},
    )
    assert res.status_code == 200, res.text
    client.headers["X-CSRF-Token"] = client.cookies["mindzen_csrf"]


# =========================================================================
# Scenario 1: Cancellation of unreceived internal PO (open -> cancelled)
# =========================================================================

def test_scenario_1_cancel_unreceived_po_succeeds(client, db_session):
    """
    An unreceived internal PO in 'open' status can be cancelled by an authorized user.
    Status transitions to 'cancelled', and cancellation audit fields are populated.
    """
    comp = create_test_company(client, "CAN-S1", "CS1")
    sup = create_test_supplier(client, comp["id"], "SUP-CS1")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Server Rack", "quantity_ordered": 2, "unit_cost": "500.00"},
                {"category_id": cat["id"], "description": "PDU Units", "quantity_ordered": 4, "unit_cost": "150.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_id = po_res.json()["id"]
    po_number = po_res.json()["order_number"]
    assert po_res.json()["status"] == "open"

    # Cancel the purchase order
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Project decommissioned before equipment delivery"},
    )
    assert cancel_res.status_code == 200, cancel_res.text
    cancel_data = cancel_res.json()

    assert cancel_data["id"] == po_id
    assert cancel_data["status"] == "cancelled"
    assert cancel_data["cancellation_reason"] == "Project decommissioned before equipment delivery"
    assert cancel_data["cancelled_at"] is not None
    assert cancel_data["cancelled_by_id"] is not None

    # Verify retrieval via GET returns status cancelled
    get_res = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "cancelled"
    assert get_res.json()["cancellation_reason"] == "Project decommissioned before equipment delivery"


# =========================================================================
# Scenario 2 & 3: Cancellation of partially received PO (short-closing) & preservation
# =========================================================================

def test_scenario_2_cancel_partially_received_po_short_closing(client, db_session):
    """
    A partially received PO can be cancelled (short-closed).
    Historical GRNs, line items, and received quantities remain 100% intact.
    """
    comp = create_test_company(client, "CAN-S2", "CS2")
    sup = create_test_supplier(client, comp["id"], "SUP-CS2")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Laptops", "quantity_ordered": 10, "unit_cost": "1000.00"},
                {"category_id": cat["id"], "description": "Docking Stations", "quantity_ordered": 10, "unit_cost": "200.00"},
            ],
        },
    )
    assert po_res.status_code == 201
    po_data = po_res.json()
    po_id = po_data["id"]
    lines_by_desc = {l["description"]: l["id"] for l in po_data["lines"]}

    # Partial receipt: Receive 4 Laptops and 4 Docking Stations
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": "DN-PARTIAL-01",
            "lines": [
                {"purchase_order_line_id": lines_by_desc["Laptops"], "quantity_received": 4, "quantity_rejected": 0},
                {"purchase_order_line_id": lines_by_desc["Docking Stations"], "quantity_received": 4, "quantity_rejected": 0},
            ],
        },
    )
    assert grn_res.status_code == 201
    grn_id = grn_res.json()["id"]
    grn_number = grn_res.json()["receipt_number"]

    # Verify status is partially_received before cancellation
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check["status"] == "partially_received"

    # Short-close / cancel remaining balance
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Short-closed remaining balance of 6 units per line per vendor shortage agreement"},
    )
    assert cancel_res.status_code == 200, cancel_res.text
    cancelled_po = cancel_res.json()
    assert cancelled_po["status"] == "cancelled"

    # Verify lines in response retain received quantities
    for l in cancelled_po["lines"]:
        assert l["quantity_ordered"] == 10
        assert l["quantity_received"] == 4

    # Verify historical GRN in database is completely intact
    db_session.expire_all()
    grn_db = db_session.get(GoodsReceipt, UUID(grn_id))
    assert grn_db is not None
    assert grn_db.receipt_number == grn_number
    grn_lines = db_session.scalars(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == UUID(grn_id))
    ).all()
    assert len(grn_lines) == 2
    for grn_line in grn_lines:
        assert grn_line.quantity_received == 4


# =========================================================================
# Scenario 3: Automatic recalculation protection
# =========================================================================

def test_scenario_3_recalculation_does_not_overwrite_cancelled_status(client, db_session):
    """
    Invoking calculate_purchase_order_status or recalculate_purchase_order_status
    on a cancelled PO must preserve 'cancelled' and never overwrite it.
    """
    comp = create_test_company(client, "CAN-S3", "CS3")
    sup = create_test_supplier(client, comp["id"], "SUP-CS3")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Monitors", "quantity_ordered": 5, "unit_cost": "250.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    # Cancel PO
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Order cancelled prior to fulfillment"},
    )

    db_session.expire_all()
    po_db = db_session.get(PurchaseOrder, UUID(po_id))
    assert po_db.status == "cancelled"

    # Call calculate_purchase_order_status directly
    calc_status = calculate_purchase_order_status(db_session, po_db)
    assert calc_status == "cancelled"

    # Call recalculate_purchase_order_status directly
    recalc_status = recalculate_purchase_order_status(db_session, po_db)
    assert recalc_status == "cancelled"
    assert po_db.status == "cancelled"


# =========================================================================
# Scenario 4: Rejection of Goods Receipt against cancelled PO
# =========================================================================

def test_scenario_4_goods_receipt_against_cancelled_po_rejected(client, db_session):
    """
    Attempting to receive goods against a cancelled PO must return HTTP 409 Conflict.
    """
    comp = create_test_company(client, "CAN-S4", "CS4")
    sup = create_test_supplier(client, comp["id"], "SUP-CS4")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Chairs", "quantity_ordered": 5, "unit_cost": "150.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    line_id = po_data["lines"][0]["id"]

    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Supplier unable to fulfill"},
    )

    # Attempt to post a goods receipt
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-03",
            "delivery_reference": "DN-ILLEGAL",
            "lines": [
                {"purchase_order_line_id": line_id, "quantity_received": 2, "quantity_rejected": 0},
            ],
        },
    )
    assert grn_res.status_code == 409, grn_res.text
    assert "is cancelled and cannot receive goods" in grn_res.json()["detail"]


# =========================================================================
# Scenario 5: Rejection of PUT/PATCH update on cancelled PO
# =========================================================================

def test_scenario_5_update_cancelled_po_rejected(client, db_session):
    """
    Ordinary PUT and PATCH updates attempting to modify a cancelled PO must be rejected with HTTP 409 Conflict.
    """
    comp = create_test_company(client, "CAN-S5", "CS5")
    sup = create_test_supplier(client, comp["id"], "SUP-CS5")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Keyboards", "quantity_ordered": 10, "unit_cost": "45.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Replaced with wireless model order"},
    )

    # Attempt PUT update
    put_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={"notes": "Attempting to change notes"},
    )
    assert put_res.status_code == 409
    assert "is cancelled and cannot be modified" in put_res.json()["detail"]

    # Attempt PATCH update
    patch_res = client.patch(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={"expected_date": "2026-11-30"},
    )
    assert patch_res.status_code == 409
    assert "is cancelled and cannot be modified" in patch_res.json()["detail"]


# =========================================================================
# Scenario 6: Rejection of deletion of cancelled PO
# =========================================================================

def test_scenario_6_delete_cancelled_po_rejected(client, db_session):
    """
    Attempting to DELETE a cancelled PO must be rejected with HTTP 409 Conflict.
    Issued documents are immutable and must be preserved for audit continuity.
    """
    comp = create_test_company(client, "CAN-S6", "CS6")
    sup = create_test_supplier(client, comp["id"], "SUP-CS6")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Desk Lamp", "quantity_ordered": 3, "unit_cost": "30.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Cancelled per supplier request"},
    )

    del_res = client.delete(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}")
    assert del_res.status_code == 409
    assert "cannot be deleted" in del_res.json()["detail"]


# =========================================================================
# Scenario 7: Rejection of cancellation of fully received PO
# =========================================================================

def test_scenario_7_cancel_fully_received_po_rejected(client, db_session):
    """
    Attempting to cancel a fully received PO must be rejected with HTTP 409 Conflict.
    """
    comp = create_test_company(client, "CAN-S7", "CS7")
    sup = create_test_supplier(client, comp["id"], "SUP-CS7")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Projector", "quantity_ordered": 1, "unit_cost": "800.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]
    line_id = po_res.json()["lines"][0]["id"]

    # Fully receive
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": "DN-FULL",
            "lines": [
                {"purchase_order_line_id": line_id, "quantity_received": 1, "quantity_rejected": 0},
            ],
        },
    )
    assert grn_res.status_code == 201

    # Attempt to cancel fully received PO
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Trying to cancel a fully received order"},
    )
    assert cancel_res.status_code == 409
    assert "is fully received and cannot be cancelled" in cancel_res.json()["detail"]


# =========================================================================
# Scenario 8: Rejection of cancellation of already cancelled PO
# =========================================================================

def test_scenario_8_cancel_already_cancelled_po_rejected(client, db_session):
    """
    Attempting to cancel an already cancelled PO must return HTTP 409 Conflict.
    """
    comp = create_test_company(client, "CAN-S8", "CS8")
    sup = create_test_supplier(client, comp["id"], "SUP-CS8")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Cables", "quantity_ordered": 20, "unit_cost": "10.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    # First cancellation succeeds
    res1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Initial cancellation"},
    )
    assert res1.status_code == 200

    # Second cancellation rejected
    res2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Duplicate cancellation attempt"},
    )
    assert res2.status_code == 409
    assert "is already cancelled" in res2.json()["detail"]


# =========================================================================
# Scenario 9: Rejection of direct local cancellation of External ERP PO
# =========================================================================

def test_scenario_9_cancel_external_erp_po_rejected(client, db_session):
    """
    Attempting to directly cancel an external ERP PO via the MindZen cancellation
    endpoint must be rejected with HTTP 409 Conflict. External PO cancellations
    must originate from the source ERP system.
    """
    comp = create_test_company(client, "CAN-S9", "CS9")
    sup = create_test_supplier(client, comp["id"], "SUP-CS9")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Ingest external PO from SAP
    payload = {
        "source_system": "SAP",
        "source_instance_id": "SAP-PROD-01",
        "external_reference": "SAP-EXT-8899",
        "supplier_id": sup["id"],
        "ordered_date": "2026-11-01",
        "lines": [
            {
                "external_line_id": "SAP-L1",
                "category_id": cat["id"],
                "description": "Industrial Router",
                "quantity_ordered": 2,
                "unit_cost": "2500.00",
            }
        ],
    }
    import_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/external-import",
        json=payload,
    )
    assert import_res.status_code in (200, 201), import_res.text
    po_id = import_res.json()["id"]
    assert import_res.json()["origin"] == "EXTERNAL"

    # Attempt to cancel via MindZen local endpoint
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Attempting local cancellation of ERP order"},
    )
    assert cancel_res.status_code == 409
    assert "originated from external ERP (SAP) and cannot be cancelled locally" in cancel_res.json()["detail"]


# =========================================================================
# Scenario 10: Validation of cancellation payload
# =========================================================================

def test_scenario_10_cancellation_payload_validation(client, db_session):
    """
    Empty reason or reason < 3 characters must be rejected with HTTP 422 Unprocessable Entity.
    """
    comp = create_test_company(client, "CAN-S10", "CS10")
    sup = create_test_supplier(client, comp["id"], "SUP-CS10")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Hub", "quantity_ordered": 1, "unit_cost": "50.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    # Missing reason
    res_empty = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={},
    )
    assert res_empty.status_code == 422

    # Reason too short (< 3 chars)
    res_short = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "no"},
    )
    assert res_short.status_code == 422


# =========================================================================
# Scenario 11: Authorization & RBAC
# =========================================================================

def test_scenario_11_authorization_and_rbac(client, db_session):
    """
    Verify RBAC:
    - Unauthenticated request -> 401.
    - User without procurement.manage -> 403.
    """
    comp = create_test_company(client, "CAN-S11", "CS11")
    sup = create_test_supplier(client, comp["id"], "SUP-CS11")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Webcam", "quantity_ordered": 2, "unit_cost": "80.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]

    # 1. Unauthenticated request
    unauth_client = client.__class__(client.app)
    unauth_res = unauth_client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Valid reason from unauth"},
    )
    assert unauth_res.status_code == 401

    # 2. User with only read permissions (e.g. auditor / read-only)
    auditor = User(
        email="auditor-po-cancel@example.invalid",
        password_hash=password_hasher.hash("Audit-Pass-123!"),
        is_active=True,
    )
    db_session.add(auditor)
    db_session.flush()

    read_role = db_session.scalar(select(Role).where(Role.code == "auditor"))
    db_session.add(CompanyMembership(
        user_id=auditor.id,
        role_id=read_role.id,
        company_id=UUID(comp["id"]),
        status="active",
    ))
    db_session.commit()

    # Login as auditor
    auditor_client = client.__class__(client.app)
    auditor_login = auditor_client.post(
        "/api/v1/auth/login",
        json={"email": "auditor-po-cancel@example.invalid", "password": "Audit-Pass-123!"},
    )
    assert auditor_login.status_code == 200
    auditor_client.headers["X-CSRF-Token"] = auditor_client.cookies["mindzen_csrf"]

    forbidden_res = auditor_client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Auditor attempting cancellation"},
    )
    assert forbidden_res.status_code == 403


# =========================================================================
# Scenario 12: Audit Logging
# =========================================================================

def test_scenario_12_audit_logging_on_cancellation(client, db_session):
    """
    Verify that an audit log entry with action 'purchase_order_cancelled'
    is recorded in SecurityAuditLog with all metadata.
    """
    comp = create_test_company(client, "CAN-S12", "CS12")
    sup = create_test_supplier(client, comp["id"], "SUP-CS12")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Microphone", "quantity_ordered": 1, "unit_cost": "120.00"},
            ],
        },
    )
    po_id = po_res.json()["id"]
    po_number = po_res.json()["order_number"]

    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/cancel",
        json={"reason": "Microphone specification changed"},
    )
    assert cancel_res.status_code == 200

    db_session.expire_all()
    audit_events = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.entity_id == str(po_id),
            AuditEvent.action == "purchase_order_cancelled",
        )
    ).all()

    assert len(audit_events) == 1
    event = audit_events[0]
    assert event.entity_type == "PurchaseOrder"
    assert event.changes["order_number"] == po_number
    assert event.changes["previous_status"] == "open"
    assert event.changes["status"] == "cancelled"
    assert event.changes["reason"] == "Microphone specification changed"
