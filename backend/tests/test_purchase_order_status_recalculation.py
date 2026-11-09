"""Milestone 2C.3.2: Purchase Order Line-Level Status Verification Integration Tests.

Comprehensive integration tests verifying:
1. Two lines: both fully received -> RECEIVED.
2. Two lines: first fully received, second not received -> PARTIALLY_RECEIVED.
3. Two lines: first over-received, second partially received -> PARTIALLY_RECEIVED (over-receipt never compensates for under-receipt).
4. No line received -> OPEN.
5. Partially received PO: append a new unreceived line -> PARTIALLY_RECEIVED.
6. Fully received PO: append a new unreceived line -> PARTIALLY_RECEIVED.
7. Fully received PO: increase an existing line's ordered quantity above its received quantity -> PARTIALLY_RECEIVED.
8. Delete an unreceived line where permitted and verify status recalculation.
9. Verify that a line with receipt history cannot be deleted or reduced below its received quantity.
10. Verify that failed updates roll back all changes.
11. Empty PO (no active lines) -> OPEN (not marked as RECEIVED).
12. Direct unit/integration verification of calculate_purchase_order_status and recalculate_purchase_order_status.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models import (
    AuditEvent,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.services import (
    calculate_purchase_order_status,
    recalculate_purchase_order_status,
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
# Scenario 1: Two lines: both fully received -> RECEIVED
# =========================================================================


def test_scenario_1_two_lines_both_fully_received_is_received(client, db_session):
    """
    Scenario 1: Two lines where both lines are fully received results in status = 'received'.
    """
    comp = create_test_company(client, "STAT-SCEN-1", "S1")
    sup = create_test_supplier(client, comp["id"], "SUP-S1")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1", "quantity_ordered": 2, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2", "quantity_ordered": 3, "unit_cost": "150.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_data = po_res.json()
    po_id = po_data["id"]
    line_map = {l["description"]: l["id"] for l in po_data["lines"]}
    l1_id = line_map["Line 1"]
    l2_id = line_map["Line 2"]

    # Post receipt fully receiving Line 1 (2/2) and Line 2 (3/3)
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": "DN-S1",
            "lines": [
                {"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0},
                {"purchase_order_line_id": l2_id, "quantity_received": 3, "quantity_rejected": 0},
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text

    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check["status"] == "received"

    # Verify authoritative function directly
    db_session.expire_all()
    po_db = db_session.get(PurchaseOrder, UUID(po_id))
    assert calculate_purchase_order_status(db_session, po_db) == "received"


# =========================================================================
# Scenario 2: Two lines: first fully received, second not received -> PARTIALLY_RECEIVED
# =========================================================================


def test_scenario_2_two_lines_first_fully_received_second_not_received_is_partially_received(client, db_session):
    """
    Scenario 2: Two lines where the first line is fully received and the second line
    has received 0 results in status = 'partially_received'.
    """
    comp = create_test_company(client, "STAT-SCEN-2", "S2")
    sup = create_test_supplier(client, comp["id"], "SUP-S2")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1", "quantity_ordered": 2, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2", "quantity_ordered": 3, "unit_cost": "150.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_data = po_res.json()
    po_id = po_data["id"]
    l1_id = po_data["lines"][0]["id"]

    # Post receipt receiving only Line 1 (2/2)
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": "DN-S2",
            "lines": [
                {"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0},
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text

    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check["status"] == "partially_received"

    db_session.expire_all()
    po_db = db_session.get(PurchaseOrder, UUID(po_id))
    assert calculate_purchase_order_status(db_session, po_db) == "partially_received"


# =========================================================================
# Scenario 3: Two lines: first over-received, second partially received -> PARTIALLY_RECEIVED
# =========================================================================


def test_scenario_3_two_lines_first_over_received_second_partially_received_is_partially_received(client, db_session):
    """
    Scenario 3: Two lines where Line 1 is over-received (3 received vs 2 ordered)
    and Line 2 is partially received (1 received vs 2 ordered).
    Total received = 4, total ordered = 4.
    Under aggregate calculation, this would have incorrectly evaluated to 'received'.
    Under line-level calculation, Line 2 is still outstanding, so status MUST be 'partially_received'.
    Over-receipt on Line 1 must NEVER compensate for under-receipt on Line 2!
    """
    comp = create_test_company(client, "STAT-SCEN-3", "S3")
    sup = create_test_supplier(client, comp["id"], "SUP-S3")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1", "quantity_ordered": 2, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2", "quantity_ordered": 2, "unit_cost": "150.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_data = po_res.json()
    po_id = UUID(po_data["id"])
    line_map = {l["description"]: UUID(l["id"]) for l in po_data["lines"]}
    l1_id = line_map["Line 1"]
    l2_id = line_map["Line 2"]

    # Directly create goods receipt records representing an over-receipt state on Line 1 (3/2) and partial on Line 2 (1/2)
    grn = GoodsReceipt(
        company_id=UUID(comp["id"]),
        purchase_order_id=po_id,
        receipt_number="GRN-S3-OVER",
        received_date=date(2026, 11, 2),
        delivery_reference="DN-S3",
    )
    db_session.add(grn)
    db_session.flush()

    grn_line1 = GoodsReceiptLine(
        company_id=UUID(comp["id"]),
        goods_receipt_id=grn.id,
        purchase_order_id=po_id,
        purchase_order_line_id=l1_id,
        quantity_received=3,  # Over-received: 3 > 2
        quantity_rejected=0,
    )
    grn_line2 = GoodsReceiptLine(
        company_id=UUID(comp["id"]),
        goods_receipt_id=grn.id,
        purchase_order_id=po_id,
        purchase_order_line_id=l2_id,
        quantity_received=1,  # Under-received: 1 < 2
        quantity_rejected=0,
    )
    db_session.add_all([grn_line1, grn_line2])
    db_session.flush()

    po_db = db_session.get(PurchaseOrder, po_id)
    # Status calculation must evaluate to 'partially_received'
    calculated = calculate_purchase_order_status(db_session, po_db)
    assert calculated == "partially_received"

    recalculate_purchase_order_status(db_session, po_db)
    assert po_db.status == "partially_received"
    db_session.commit()

    # Verify through API read
    po_api = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_api["status"] == "partially_received"


# =========================================================================
# Scenario 4: No line received -> OPEN
# =========================================================================


def test_scenario_4_no_line_received_is_open(client, db_session):
    """
    Scenario 4: When no active line has received any quantity, status is 'open'.
    """
    comp = create_test_company(client, "STAT-SCEN-4", "S4")
    sup = create_test_supplier(client, comp["id"], "SUP-S4")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1", "quantity_ordered": 5, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2", "quantity_ordered": 10, "unit_cost": "50.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po_data = po_res.json()
    assert po_data["status"] == "open"

    db_session.expire_all()
    po_db = db_session.get(PurchaseOrder, UUID(po_data["id"]))
    assert calculate_purchase_order_status(db_session, po_db) == "open"


# =========================================================================
# Scenario 5: Partially received PO: append a new unreceived line -> PARTIALLY_RECEIVED
# =========================================================================


def test_scenario_5_partially_received_po_append_unreceived_line_is_partially_received(client, db_session):
    """
    Scenario 5: A partially received PO remains 'partially_received' when a new
    unreceived line is appended.
    """
    comp = create_test_company(client, "STAT-SCEN-5", "S5")
    sup = create_test_supplier(client, comp["id"], "SUP-S5")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1", "quantity_ordered": 4, "unit_cost": "100.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    l1_id = po_data["lines"][0]["id"]

    # Partially receive Line 1 (2/4)
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0}],
        },
    )
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check["status"] == "partially_received"

    # Append new unreceived line
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l1_id, "category_id": cat["id"], "description": "Line 1", "quantity_ordered": 4, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2 Appended", "quantity_ordered": 3, "unit_cost": "200.00"},
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert updated["status"] == "partially_received"
    assert len(updated["lines"]) == 2


# =========================================================================
# Scenario 6: Fully received PO: append a new unreceived line -> PARTIALLY_RECEIVED
# =========================================================================


def test_scenario_6_fully_received_po_append_unreceived_line_transitions_to_partially_received(client, db_session):
    """
    Scenario 6: A fully received PO transitions from 'received' back to 'partially_received'
    when a new unreceived line is appended.
    """
    comp = create_test_company(client, "STAT-SCEN-6", "S6")
    sup = create_test_supplier(client, comp["id"], "SUP-S6")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Initial Line", "quantity_ordered": 2, "unit_cost": "500.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    l1_id = po_data["lines"][0]["id"]

    # Fully receive Line 1 (2/2) -> status becomes 'received'
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0}],
        },
    )
    po_before = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_before["status"] == "received"

    # Append new unreceived Line 2
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l1_id, "category_id": cat["id"], "description": "Initial Line", "quantity_ordered": 2, "unit_cost": "500.00"},
                {"category_id": cat["id"], "description": "Appended Line 2", "quantity_ordered": 4, "unit_cost": "250.00"},
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert updated["status"] == "partially_received"


# =========================================================================
# Scenario 7: Fully received PO: increase quantity -> PARTIALLY_RECEIVED
# =========================================================================


def test_scenario_7_fully_received_po_increase_quantity_transitions_to_partially_received(client, db_session):
    """
    Scenario 7: A fully received PO transitions from 'received' back to 'partially_received'
    when an existing line's ordered quantity is increased above its received quantity.
    """
    comp = create_test_company(client, "STAT-SCEN-7", "S7")
    sup = create_test_supplier(client, comp["id"], "SUP-S7")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Scalable Line", "quantity_ordered": 3, "unit_cost": "100.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    l1_id = po_data["lines"][0]["id"]

    # Fully receive (3/3)
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l1_id, "quantity_received": 3, "quantity_rejected": 0}],
        },
    )
    assert client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()["status"] == "received"

    # Increase quantity from 3 to 6
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l1_id, "category_id": cat["id"], "description": "Scalable Line", "quantity_ordered": 6, "unit_cost": "100.00"},
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert updated["status"] == "partially_received"
    assert updated["lines"][0]["quantity_ordered"] == 6
    assert updated["lines"][0]["quantity_received"] == 3
    assert updated["lines"][0]["quantity_remaining"] == 3


# =========================================================================
# Scenario 8: Delete an unreceived line where permitted -> recalculates to RECEIVED
# =========================================================================


def test_scenario_8_delete_unreceived_line_recalculates_to_received(client, db_session):
    """
    Scenario 8: A PO with Line 1 (fully received) and Line 2 (unreceived) has status
    'partially_received'. When the unreceived Line 2 is deleted, status recalculates
    to 'received' because all remaining active lines are fully received.
    """
    comp = create_test_company(client, "STAT-SCEN-8", "S8")
    sup = create_test_supplier(client, comp["id"], "SUP-S8")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1 - Received", "quantity_ordered": 2, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line 2 - To Delete", "quantity_ordered": 3, "unit_cost": "50.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    line_map = {l["description"]: l["id"] for l in po_data["lines"]}
    l1_id = line_map["Line 1 - Received"]
    l2_id = line_map["Line 2 - To Delete"]

    # Receive only Line 1 (2/2)
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0}],
        },
    )
    assert client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()["status"] == "partially_received"

    # Delete Line 2 (by omitting it from update payload)
    upd_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l1_id, "category_id": cat["id"], "description": "Line 1 - Received", "quantity_ordered": 2, "unit_cost": "100.00"},
            ],
        },
    )
    assert upd_res.status_code == 200, upd_res.text
    updated = upd_res.json()
    assert len(updated["lines"]) == 1
    assert updated["lines"][0]["id"] == l1_id
    assert updated["status"] == "received"


# =========================================================================
# Scenario 9: Receipt history protections (cannot delete, cannot reduce below received)
# =========================================================================


def test_scenario_9_receipt_history_protections_cannot_delete_or_reduce_below_received(client, db_session):
    """
    Scenario 9: A line with receipt history cannot be deleted (HTTP 409) and
    cannot have its quantity_ordered reduced below its received quantity (HTTP 422).
    """
    comp = create_test_company(client, "STAT-SCEN-9", "S9")
    sup = create_test_supplier(client, comp["id"], "SUP-S9")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line A", "quantity_ordered": 5, "unit_cost": "100.00"},
                {"category_id": cat["id"], "description": "Line B", "quantity_ordered": 5, "unit_cost": "100.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    line_map = {l["description"]: l["id"] for l in po_data["lines"]}
    l_a_id = line_map["Line A"]
    l_b_id = line_map["Line B"]

    # Receive 3 on Line A
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l_a_id, "quantity_received": 3, "quantity_rejected": 0}],
        },
    )

    # Attempt to delete Line A (with receipts) -> 409
    del_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l_b_id, "category_id": cat["id"], "description": "Line B", "quantity_ordered": 5, "unit_cost": "100.00"},
            ],
        },
    )
    assert del_res.status_code == 409
    assert "because goods have already been received against it" in del_res.json()["detail"]

    # Attempt to reduce Line A quantity to 2 (< 3 received) -> 422
    reduce_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "lines": [
                {"id": l_a_id, "category_id": cat["id"], "description": "Line A", "quantity_ordered": 2, "unit_cost": "100.00"},
                {"id": l_b_id, "category_id": cat["id"], "description": "Line B", "quantity_ordered": 5, "unit_cost": "100.00"},
            ],
        },
    )
    assert reduce_res.status_code == 422
    assert "because 3 items have already been received" in reduce_res.json()["detail"]


# =========================================================================
# Scenario 10: Failed updates roll back all changes
# =========================================================================


def test_scenario_10_failed_updates_roll_back_all_changes(client, db_session):
    """
    Scenario 10: When an update request fails validation, the database transaction
    rolls back completely. No header modifications, line changes, or audit records persist.
    """
    comp = create_test_company(client, "STAT-SCEN-10", "S10")
    sup = create_test_supplier(client, comp["id"], "SUP-S10")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "notes": "Untouched Notes",
            "lines": [
                {"category_id": cat["id"], "description": "Item 1", "quantity_ordered": 4, "unit_cost": "50.00"},
            ],
        },
    )
    po_data = po_res.json()
    po_id = po_data["id"]
    l1_id = po_data["lines"][0]["id"]

    # Receive 2
    client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [{"purchase_order_line_id": l1_id, "quantity_received": 2, "quantity_rejected": 0}],
        },
    )

    db_session.expire_all()
    events_before = len(
        db_session.scalars(select(AuditEvent).where(AuditEvent.company_id == UUID(comp["id"]))).all()
    )

    # Failed update attempt: modified notes + invalid quantity
    fail_res = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}",
        json={
            "supplier_id": sup["id"],
            "notes": "Should NOT Persist",
            "lines": [
                {"id": l1_id, "category_id": cat["id"], "description": "Item 1", "quantity_ordered": 1, "unit_cost": "50.00"},
            ],
        },
    )
    assert fail_res.status_code == 422

    db_session.expire_all()
    po_db = db_session.get(PurchaseOrder, UUID(po_id))
    assert po_db.notes == "Untouched Notes"
    assert po_db.status == "partially_received"

    events_after = len(
        db_session.scalars(select(AuditEvent).where(AuditEvent.company_id == UUID(comp["id"]))).all()
    )
    assert events_after == events_before


# =========================================================================
# Scenario 11: Empty PO behaviour (does not mark empty PO as RECEIVED)
# =========================================================================


def test_scenario_11_empty_po_does_not_mark_as_received(client, db_session):
    """
    Scenario 11: A PO with no active lines must evaluate to 'open', not 'received'.
    """
    comp = create_test_company(client, "STAT-SCEN-11", "S11")
    sup = create_test_supplier(client, comp["id"], "SUP-S11")

    empty_po = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="S11-PO-EMPTY",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add(empty_po)
    db_session.flush()

    status = calculate_purchase_order_status(db_session, empty_po)
    assert status == "open"
    assert status != "received"

    recalc = recalculate_purchase_order_status(db_session, empty_po)
    assert recalc == "open"
    assert empty_po.status == "open"


# =========================================================================
# Scenario 12: Direct Unit Verification of calculate_purchase_order_status
# =========================================================================


def test_scenario_12_direct_service_status_calculation(client, db_session):
    """
    Scenario 12: Direct verification of calculate_purchase_order_status across all
    state transitions within a single transaction.
    """
    comp = create_test_company(client, "STAT-SCEN-12", "S12")
    sup = create_test_supplier(client, comp["id"], "SUP-S12")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po = PurchaseOrder(
        company_id=UUID(comp["id"]),
        supplier_id=UUID(sup["id"]),
        order_number="S12-PO-DIRECT",
        origin="INTERNAL",
        ordered_date=date(2026, 11, 1),
    )
    db_session.add(po)
    db_session.flush()

    # Step 1: No lines -> 'open'
    assert calculate_purchase_order_status(db_session, po) == "open"

    # Step 2: Add Line 1 (qty 4) and Line 2 (qty 6) with 0 receipts -> 'open'
    l1 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="DLine 1",
        quantity_ordered=4,
        unit_cost=Decimal("10.00"),
    )
    l2 = PurchaseOrderLine(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        category_id=UUID(cat["id"]),
        description="DLine 2",
        quantity_ordered=6,
        unit_cost=Decimal("20.00"),
    )
    db_session.add_all([l1, l2])
    db_session.flush()
    assert calculate_purchase_order_status(db_session, po) == "open"

    # Step 3: Receive 4 on Line 1 (Line 1 fully received, Line 2 untouched) -> 'partially_received'
    grn1 = GoodsReceipt(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        receipt_number="GRN-S12-1",
        received_date=date(2026, 11, 2),
    )
    db_session.add(grn1)
    db_session.flush()

    grn1_l1 = GoodsReceiptLine(
        company_id=UUID(comp["id"]),
        goods_receipt_id=grn1.id,
        purchase_order_id=po.id,
        purchase_order_line_id=l1.id,
        quantity_received=4,
        quantity_rejected=0,
    )
    db_session.add(grn1_l1)
    db_session.flush()
    assert calculate_purchase_order_status(db_session, po) == "partially_received"

    # Step 4: Receive 6 on Line 2 (both lines fully received) -> 'received'
    grn2 = GoodsReceipt(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        receipt_number="GRN-S12-2",
        received_date=date(2026, 11, 3),
    )
    db_session.add(grn2)
    db_session.flush()

    grn2_l2 = GoodsReceiptLine(
        company_id=UUID(comp["id"]),
        goods_receipt_id=grn2.id,
        purchase_order_id=po.id,
        purchase_order_line_id=l2.id,
        quantity_received=6,
        quantity_rejected=0,
    )
    db_session.add(grn2_l2)
    db_session.flush()
    assert calculate_purchase_order_status(db_session, po) == "received"

    # Step 5: Increase Line 2 quantity from 6 to 10 -> 'partially_received'
    l2.quantity_ordered = 10
    db_session.flush()
    assert calculate_purchase_order_status(db_session, po) == "partially_received"

    # Step 6: Receive remaining 4 on Line 2 -> 'received'
    grn3 = GoodsReceipt(
        company_id=UUID(comp["id"]),
        purchase_order_id=po.id,
        receipt_number="GRN-S12-3",
        received_date=date(2026, 11, 4),
    )
    db_session.add(grn3)
    db_session.flush()

    grn3_l2 = GoodsReceiptLine(
        company_id=UUID(comp["id"]),
        goods_receipt_id=grn3.id,
        purchase_order_id=po.id,
        purchase_order_line_id=l2.id,
        quantity_received=4,
        quantity_rejected=0,
    )
    db_session.add(grn3_l2)
    db_session.flush()
    assert calculate_purchase_order_status(db_session, po) == "received"
