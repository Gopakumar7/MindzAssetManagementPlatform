"""Milestone 2E.3: Goods Return to Vendor (GRR) Integration Tests

Comprehensive integration tests covering:
1. Reference number allocation and monotonicity.
2. Composite FK lineage and cross-company tenant isolation.
3. Active asset reservation collision and SAVEPOINT rollback (zero leaked sequence numbers).
4. Draft line deselection and transactional reservation release.
5. Segregation of duties: Creator approval blocked when strict policy is True (403).
6. Segregation of duties: Different officer approval succeeds (200).
7. Configurable policy: Disabled segregation permits self-approval (200, policy snapshot).
8. Dispatch transition: Status -> 'dispatched', Assets -> 'return_pending'.
9. Dispatched return direct cancellation prohibition (409 Conflict).
10. Partial physical warehouse receipt: Subset returned -> 'reversed', document -> 'partially_returned_to_warehouse'.
11. Warehouse receipt correction: Asset -> 'return_pending', reservation reactivated.
12. Completion of partially returned return: Remaining assets -> 'returned_to_vendor', document -> 'completed'.
13. PostgreSQL database trigger immutability: Raw SQL update/delete on warehouse receipts blocked.
"""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.authentication import password_hasher
from app.models import (
    Asset,
    Company,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptReversal,
    GoodsReceiptReversalAsset,
    GoodsReturn,
    GoodsReturnAssetReservation,
    GoodsReturnLine,
    GoodsReturnWarehouseReceipt,
    GoodsReturnWarehouseReceiptLine,
    Role,
    User,
)


def create_test_company(client, code: str, prefix: str):
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


def add_member(db_session, company_id: str, email: str, role_code: str = "company_administrator") -> User:
    cid = UUID(str(company_id))
    role = db_session.scalar(select(Role).where(Role.scope == "company", Role.code == role_code))
    user = User(
        email=email,
        password_hash=password_hasher.hash("Correct-Horse-42!"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        CompanyMembership(
            company_id=cid,
            user_id=user.id,
            role_id=role.id,
            status="active",
        )
    )
    db_session.commit()
    return user


def setup_reversal_scenario(client, comp_code: str, prefix: str, qty: int = 3):
    comp = create_test_company(client, comp_code, prefix)
    sup = create_test_supplier(client, comp["id"], f"SUP-{comp_code}")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": cat["id"],
                    "description": "Enterprise Asset Item",
                    "quantity_ordered": qty,
                    "unit_cost": "1500.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()
    po_line_id = po["lines"][0]["id"]

    serials = [f"SRV-{uuid4().hex[:8].upper()}" for _ in range(qty)]
    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": f"DC-{comp_code}",
            "lines": [
                {
                    "purchase_order_line_id": po_line_id,
                    "quantity_received": qty,
                    "quantity_rejected": 0,
                    "serial_numbers": serials,
                }
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text
    grn = grn_res.json()
    grn_line = grn["lines"][0]
    asset_ids = [a["id"] for a in grn_line["assets"]]

    rev_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Specification mismatch post-delivery",
            "lines": [
                {
                    "goods_receipt_line_id": grn_line["id"],
                    "asset_ids": asset_ids,
                    "notes": "Full reversal for return",
                }
            ],
        },
    )
    assert rev_res.status_code == 201, rev_res.text
    rev = rev_res.json()
    return comp, sup, po, grn, rev


# =========================================================================
# 1. Reference Number Allocation and Monotonicity
# =========================================================================

def test_grr_first_reference_allocation_and_numbering(client, db_session):
    """Verify first reference allocation (e.g. GRR1-GRR-2627-00001) and monotonic increment."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-NUM1", "GRR1", qty=2)

    rev_assets = rev["lines"][0]["assets"]
    # Create Return 1 with asset 0
    res1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Returning asset 1 to vendor",
            "lines": [
                {
                    "goods_receipt_reversal_asset_id": rev_assets[0]["id"],
                    "return_condition": "as_received",
                }
            ],
        },
    )
    assert res1.status_code == 201, res1.text
    grr1 = res1.json()
    assert grr1["return_number"].startswith("GRR1-GRR-")
    assert grr1["return_number"].endswith("-00001")
    assert grr1["status"] == "draft"

    # Create Return 2 with asset 1
    res2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Returning asset 2 to vendor",
            "lines": [
                {
                    "goods_receipt_reversal_asset_id": rev_assets[1]["id"],
                    "return_condition": "as_received",
                }
            ],
        },
    )
    assert res2.status_code == 201, res2.text
    grr2 = res2.json()
    assert grr2["return_number"].endswith("-00002")


# =========================================================================
# 2. Composite FK Lineage & Cross-Company Isolation
# =========================================================================

def test_grr_cross_company_isolation(client, db_session):
    """Returns reject reversal assets originating from a different company."""
    comp_a, sup_a, po_a, grn_a, rev_a = setup_reversal_scenario(client, "GRR-ISOL-A", "ISOA", qty=1)
    comp_b, sup_b, po_b, grn_b, rev_b = setup_reversal_scenario(client, "GRR-ISOL-B", "ISOB", qty=1)

    asset_a_id = rev_a["lines"][0]["assets"][0]["id"]

    # Attempt to create return in Company B using Company A's reversal asset
    res = client.post(
        f"/api/v1/companies/{comp_b['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev_b["id"],
            "return_date": "2026-11-06",
            "return_reason": "Cross-company attack test",
            "lines": [
                {
                    "goods_receipt_reversal_asset_id": asset_a_id,
                    "return_condition": "as_received",
                }
            ],
        },
    )
    assert res.status_code in (404, 422), res.text


# =========================================================================
# 3. Active Reservation Collision & SAVEPOINT Rollback (Zero Leaked Numbers)
# =========================================================================

def test_active_reservation_collision_and_savepoint_rollback(client, db_session):
    """
    When Return 1 actively reserves an asset:
    1. Return 2 attempting to reserve the same asset fails with HTTP 409 Conflict.
    2. SAVEPOINT rolls back: sequence number does NOT leak.
    3. Return 3 with an unreserved asset receives the very next contiguous sequence number.
    """
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-RES1", "RES1", qty=2)
    asset_0_id = rev["lines"][0]["assets"][0]["id"]
    asset_1_id = rev["lines"][0]["assets"][1]["id"]

    # 1. Create Return 1 reserving asset 0 (allocates -00001)
    res1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Return 1",
            "lines": [{"goods_receipt_reversal_asset_id": asset_0_id}],
        },
    )
    assert res1.status_code == 201, res1.text
    grr1 = res1.json()
    assert grr1["return_number"].endswith("-00001")

    # 2. Return 2 attempts to reserve asset 0 again -> 409 Conflict
    res2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Conflicting return attempting duplicate reservation",
            "lines": [{"goods_receipt_reversal_asset_id": asset_0_id}],
        },
    )
    assert res2.status_code == 409, res2.text
    assert "already actively reserved" in res2.json()["detail"]

    # 3. Create Return 3 with asset 1 -> must get contiguous sequence number -00002!
    res3 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Return 3 with valid asset",
            "lines": [{"goods_receipt_reversal_asset_id": asset_1_id}],
        },
    )
    assert res3.status_code == 201, res3.text
    grr3 = res3.json()
    assert grr3["return_number"].endswith("-00002")


# =========================================================================
# 4. Draft Line Deselection & Reservation Release
# =========================================================================

def test_draft_line_deselection_and_reservation_release(client, db_session):
    """Removing a line from draft return releases its reservation ('deselected') and frees the asset."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-DESEL", "DESL", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    # Create draft return with the asset
    res1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Draft to be edited",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    assert res1.status_code == 201, res1.text
    grr1 = res1.json()
    line_id = grr1["lines"][0]["id"]

    # Verify reservation is active
    res_record = db_session.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.goods_return_id == UUID(grr1["id"]),
            GoodsReturnAssetReservation.released_at.is_(None),
        )
    )
    assert res_record is not None

    # Deselect line
    del_res = client.delete(f"/api/v1/companies/{comp['id']}/goods-returns/{grr1['id']}/lines/{line_id}")
    assert del_res.status_code == 200, del_res.text
    updated_grr = del_res.json()
    assert len(updated_grr["lines"]) == 0

    # Verify reservation is marked deselected
    db_session.expire_all()
    res_record = db_session.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.goods_return_id == UUID(grr1["id"]),
        )
    )
    assert res_record.released_at is not None
    assert res_record.release_reason == "deselected"

    # Asset is now free to be reserved in another return
    res2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Subsequent return after deselection",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    assert res2.status_code == 201, res2.text


# =========================================================================
# 5, 6, 7. Segregation of Duties & Approval Policy Snapshot
# =========================================================================

def test_strict_segregation_blocks_creator_approval(client, db_session):
    """When company setting is strict (default), creator cannot approve draft return (403)."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-SEG1", "SEG1", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Approval test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    assert res.status_code == 201, res.text
    grr = res.json()

    # Attempt to self-approve with the same creator actor
    app_res = client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")
    assert app_res.status_code == 403, app_res.text
    assert "Segregation of duties violation" in app_res.json()["detail"]


def test_different_officer_approval_succeeds(client, db_session):
    """Different administrator officer can approve the return."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-SEG2", "SEG2", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Different officer test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    assert res.status_code == 201, res.text
    grr = res.json()

    # Create a secondary administrator user
    officer = add_member(db_session, comp["id"], "officer@example.com", "company_administrator")

    # Authenticate as the officer
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": officer.email, "password": "Correct-Horse-42!"},
    )
    assert login_res.status_code == 200, login_res.text
    client.headers["X-CSRF-Token"] = client.cookies["mindzen_csrf"]

    # Call approve with officer's authenticated session
    app_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve",
    )
    assert app_res.status_code == 200, app_res.text
    approved_grr = app_res.json()
    assert approved_grr["status"] == "approved"
    assert approved_grr["approved_by_id"] == str(officer.id)
    assert approved_grr["policy_strict_approval_applied"] is True

    # Re-login as default admin for clean test client state
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "test-admin@example.invalid", "password": "Correct-Horse-42!"},
    )
    assert admin_login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["mindzen_csrf"]


def test_disabled_segregation_permits_self_approval(client, db_session):
    """Disabling strict approval policy permits creator to approve, persisting snapshot."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-SEG3", "SEG3", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    # Disable strict approval policy
    settings_res = client.put(
        f"/api/v1/companies/{comp['id']}/settings",
        json={
            "procurement_different_person_return_approval": False,
            "reason": "Single administrator organization policy override",
        },
    )
    assert settings_res.status_code == 200, settings_res.text

    # Create return
    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Self-approval permitted test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    assert res.status_code == 201, res.text
    grr = res.json()

    # Self-approve
    app_res = client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")
    assert app_res.status_code == 200, app_res.text
    approved_grr = app_res.json()
    assert approved_grr["status"] == "approved"
    assert approved_grr["policy_strict_approval_applied"] is False


# =========================================================================
# 8 & 9. Dispatch & Cancellation Protection
# =========================================================================

def test_dispatched_grr_asset_status_transition_and_cancellation_prohibition(client, db_session):
    """Dispatching a return transitions assets to 'return_pending' and blocks direct cancellation."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-DISP", "DSP1", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    # Disable strict approval for test brevity
    client.put(
        f"/api/v1/companies/{comp['id']}/settings",
        json={
            "procurement_different_person_return_approval": False,
            "reason": "Policy override for dispatch test",
        },
    )

    # 1. Create and approve
    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Dispatch test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    grr = res.json()
    client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")

    # 2. Dispatch
    disp_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/dispatch",
        json={
            "dispatch_reference": "CARRIER-WAYBILL-999",
            "transport_details": "DHL Express Tracking #999000",
        },
    )
    assert disp_res.status_code == 200, disp_res.text
    dispatched_grr = disp_res.json()
    assert dispatched_grr["status"] == "dispatched"

    # Verify asset is now 'return_pending'
    db_session.expire_all()
    asset = db_session.scalar(select(Asset).where(Asset.id == UUID(grr["lines"][0]["asset_id"])))
    assert asset.status == "return_pending"

    # 3. Direct cancellation on dispatched return is prohibited -> 409 Conflict
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/cancel",
        json={"cancellation_reason": "Attempting illegal cancellation while in transit"},
    )
    assert cancel_res.status_code == 409, cancel_res.text
    assert "Dispatched returns must be received via warehouse receipt" in cancel_res.json()["detail"]


# =========================================================================
# 10, 11, 12. Warehouse Receipt Lifecycle, Correction & Completion
# =========================================================================

def test_warehouse_receipt_lifecycle_correction_and_completion(client, db_session):
    """
    Complete lifecycle with 2 assets:
    1. Dispatch return with 2 assets (both -> 'return_pending').
    2. Partial warehouse receipt of asset 0:
       - Asset 0 -> 'reversed', reservation released ('returned_to_warehouse').
       - Asset 1 -> 'return_pending', reservation active.
       - Document -> 'partially_returned_to_warehouse'.
    3. Correct warehouse receipt line for asset 0:
       - Asset 0 reverts to 'return_pending'.
       - Reservation reactivated (released_at is None).
       - Document status returns to 'dispatched'.
    4. Re-receive asset 0 via warehouse receipt:
       - Document -> 'partially_returned_to_warehouse'.
    5. Complete return for remaining in-transit asset 1:
       - Asset 1 -> 'returned_to_vendor', reservation released ('completed').
       - Document -> 'completed'.
    """
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-WR-LIFECYCLE", "WRLF", qty=2)
    asset_0_ra_id = rev["lines"][0]["assets"][0]["id"]
    asset_1_ra_id = rev["lines"][0]["assets"][1]["id"]

    client.put(
        f"/api/v1/companies/{comp['id']}/settings",
        json={
            "procurement_different_person_return_approval": False,
            "reason": "Testing warehouse receipt lifecycle",
        },
    )

    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Multi-asset return for warehouse tests",
            "lines": [
                {"goods_receipt_reversal_asset_id": asset_0_ra_id},
                {"goods_receipt_reversal_asset_id": asset_1_ra_id},
            ],
        },
    )
    grr = res.json()
    line_0_id = grr["lines"][0]["id"]
    line_1_id = grr["lines"][1]["id"]
    asset_0_id = grr["lines"][0]["asset_id"]
    asset_1_id = grr["lines"][1]["asset_id"]

    client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")
    client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/dispatch",
        json={"dispatch_reference": "DISP-123", "transport_details": "Logistics Van"},
    )

    # 2. Record partial warehouse receipt for line 0
    wr_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts",
        json={
            "receipt_date": "2026-11-07",
            "reason": "Carrier failed delivery for item 0, returned to warehouse",
            "lines": [
                {
                    "goods_return_line_id": line_0_id,
                    "condition_on_return": "intact",
                }
            ],
        },
    )
    assert wr_res.status_code == 201, wr_res.text
    wr = wr_res.json()
    wr_line_0_id = wr["lines"][0]["id"]

    # Verify return status is partially_returned_to_warehouse
    grr_check = client.get(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}").json()
    assert grr_check["status"] == "partially_returned_to_warehouse"

    # Verify asset 0 reverted to reversed and its reservation is released
    db_session.expire_all()
    a0 = db_session.scalar(select(Asset).where(Asset.id == UUID(asset_0_id)))
    a1 = db_session.scalar(select(Asset).where(Asset.id == UUID(asset_1_id)))
    assert a0.status == "reversed"
    assert a1.status == "return_pending"

    res0 = db_session.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.goods_return_id == UUID(grr["id"]),
            GoodsReturnAssetReservation.asset_id == UUID(asset_0_id),
        )
    )
    assert res0.released_at is not None
    assert res0.release_reason == "returned_to_warehouse"

    # 3. Correct the warehouse receipt line (e.g. clerk clicked wrong item)
    corr_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts/{wr['id']}/lines/{wr_line_0_id}/correct",
        json={"correction_reason": "Clerical mistake: item 0 was not actually returned"},
    )
    assert corr_res.status_code == 200, corr_res.text

    # Verify asset 0 reverts to return_pending, reservation reactivated, return back to dispatched
    db_session.expire_all()
    a0 = db_session.scalar(select(Asset).where(Asset.id == UUID(asset_0_id)))
    assert a0.status == "return_pending"

    # Verify active reservation exists and historical reservation remains intact
    active_res0 = db_session.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.goods_return_id == UUID(grr["id"]),
            GoodsReturnAssetReservation.asset_id == UUID(asset_0_id),
            GoodsReturnAssetReservation.released_at.is_(None),
        )
    )
    assert active_res0 is not None
    assert active_res0.released_at is None

    hist_res0 = db_session.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.goods_return_id == UUID(grr["id"]),
            GoodsReturnAssetReservation.asset_id == UUID(asset_0_id),
            GoodsReturnAssetReservation.release_reason == "returned_to_warehouse",
        )
    )
    assert hist_res0 is not None
    assert hist_res0.released_at is not None

    grr_check = client.get(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}").json()
    assert grr_check["status"] == "dispatched"

    # 4. Re-receive asset 0 legitimately
    wr_res2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts",
        json={
            "receipt_date": "2026-11-08",
            "reason": "Legitimate return of item 0 to warehouse",
            "lines": [
                {
                    "goods_return_line_id": line_0_id,
                    "condition_on_return": "intact",
                }
            ],
        },
    )
    assert wr_res2.status_code == 201, wr_res2.text

    grr_check = client.get(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}").json()
    assert grr_check["status"] == "partially_returned_to_warehouse"

    # 5. Complete return for remaining item 1 (vendor accepted item 1)
    comp_res = client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/complete")
    assert comp_res.status_code == 200, comp_res.text
    final_grr = comp_res.json()
    assert final_grr["status"] == "completed"

    # Verify final states of both assets
    db_session.expire_all()
    a0 = db_session.scalar(select(Asset).where(Asset.id == UUID(asset_0_id)))
    a1 = db_session.scalar(select(Asset).where(Asset.id == UUID(asset_1_id)))
    assert a0.status == "reversed"  # safely back in warehouse stock
    assert a1.status == "returned_to_vendor"  # permanently decommissioned with vendor


# =========================================================================
# 13. PostgreSQL Database Trigger Immutability
# =========================================================================

def test_warehouse_receipt_postgresql_trigger_immutability(client, db_session):
    """Raw SQL UPDATE or DELETE on warehouse receipts or receipt lines is rejected by trigger."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-TRG", "TRG1", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    client.put(
        f"/api/v1/companies/{comp['id']}/settings",
        json={
            "procurement_different_person_return_approval": False,
            "reason": "Testing trigger immutability",
        },
    )

    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Trigger test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    grr = res.json()
    line_id = grr["lines"][0]["id"]

    client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")
    client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/dispatch",
        json={"dispatch_reference": "DISP-TRG"},
    )
    wr_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts",
        json={
            "receipt_date": "2026-11-08",
            "reason": "Received in warehouse",
            "lines": [{"goods_return_line_id": line_id}],
        },
    )
    wr = wr_res.json()

    dialect = db_session.bind.dialect.name
    if dialect == "postgresql":
        # Attempt direct SQL UPDATE on header -> must fail
        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("UPDATE goods_return_warehouse_receipts SET reason = 'Tampered' WHERE id = :id"),
                {"id": wr["id"]},
            )
            db_session.commit()
        db_session.rollback()
        assert "trg_no_update_delete" in str(exc_info.value) or "immutable" in str(exc_info.value).lower() or "cannot be deleted" in str(exc_info.value).lower()

        # Attempt direct SQL DELETE on lines -> must fail
        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("DELETE FROM goods_return_warehouse_receipt_lines WHERE warehouse_receipt_id = :id"),
                {"id": wr["id"]},
            )
            db_session.commit()
        db_session.rollback()
        assert "trg_no_update_delete" in str(exc_info.value) or "immutable" in str(exc_info.value).lower() or "cannot be deleted" in str(exc_info.value).lower()


def test_warehouse_receipt_correction_ledger_immutability(client, db_session):
    """Raw SQL UPDATE or DELETE on goods_return_warehouse_receipt_corrections is rejected by PostgreSQL trigger."""
    comp, sup, po, grn, rev = setup_reversal_scenario(client, "GRR-CORR-TRG", "CTRG", qty=1)
    asset_id = rev["lines"][0]["assets"][0]["id"]

    client.put(
        f"/api/v1/companies/{comp['id']}/settings",
        json={
            "procurement_different_person_return_approval": False,
            "reason": "Testing correction immutability",
        },
    )

    res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns",
        json={
            "goods_receipt_reversal_id": rev["id"],
            "return_date": "2026-11-06",
            "return_reason": "Trigger test",
            "lines": [{"goods_receipt_reversal_asset_id": asset_id}],
        },
    )
    grr = res.json()
    line_id = grr["lines"][0]["id"]

    client.post(f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/approve")
    client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/dispatch",
        json={"dispatch_reference": "DISP-TRG"},
    )
    wr_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts",
        json={
            "receipt_date": "2026-11-08",
            "reason": "Received in warehouse",
            "lines": [{"goods_return_line_id": line_id}],
        },
    )
    wr = wr_res.json()
    wr_line_id = wr["lines"][0]["id"]

    # Perform correction
    corr_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-returns/{grr['id']}/warehouse-receipts/{wr['id']}/lines/{wr_line_id}/correct",
        json={
            "correction_reason": "Mistaken scan at gate",
            "notes": "Testing trigger ledger protection",
        },
    )
    assert corr_res.status_code == 200

    corr_row = db_session.execute(
        text("SELECT id FROM goods_return_warehouse_receipt_corrections WHERE warehouse_receipt_line_id = :line_id"),
        {"line_id": wr_line_id},
    ).fetchone()
    assert corr_row is not None
    corr_id = corr_row[0]

    dialect = db_session.bind.dialect.name
    if dialect == "postgresql":
        # Attempt direct SQL UPDATE on correction ledger -> must fail
        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("UPDATE goods_return_warehouse_receipt_corrections SET notes = 'Tampered' WHERE id = :id"),
                {"id": corr_id},
            )
            db_session.commit()
        db_session.rollback()
        assert "immutable" in str(exc_info.value).lower() or "trg_no_update_delete_gr_wr_correction" in str(exc_info.value)

        # Attempt direct SQL DELETE on correction ledger -> must fail
        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("DELETE FROM goods_return_warehouse_receipt_corrections WHERE id = :id"),
                {"id": corr_id},
            )
            db_session.commit()
        db_session.rollback()
        assert "immutable" in str(exc_info.value).lower() or "trg_no_update_delete_gr_wr_correction" in str(exc_info.value)
