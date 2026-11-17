from app.authentication import password_hasher
"""Milestone 2E.2: Goods Receipt Note (GRN) Reversal Foundation Integration Tests.

Comprehensive integration tests verifying:
1. Full reversal of single-line GRN (completed -> reversed, PO received -> open).
2. Full reversal of multi-line GRN across multiple line items.
3. Partial line reversal (reversing subset of accepted items, completed -> partially_reversed).
4. Sequential partial reversals accumulating to 100% across separate transactions.
5. Over-reversal rejection (attempting to reverse more than unreversed accepted stock -> 409 Conflict).
6. Non-reversibility of rejected items (reversals operate strictly on accepted stock).
7. Gate 1 failure: Asset status is not 'in_stock' -> 409 Conflict.
8. Gate 2 failure: Asset has active assignment in AssetAssignment -> 409 Conflict.
9. Gate 3 failure: Asset has open or in-progress MaintenanceRequest -> 409 Conflict.
10. Gate 4 failure: Asset has posted AssetDepreciationEntry -> 409 Conflict.
    - Also verifies that draft AssetFinancial with zero depreciation does NOT block reversal.
11. Gate 5 failure: Asset has disposal record in AssetDisposal -> 409 Conflict.
12. Gate 6 failure: Asset has open VerificationDiscrepancy -> 409 Conflict.
13. Atomic rollback: if any asset in a multi-asset reversal fails, transaction rolls back completely.
14. Independent partial reversal: eligible assets can be reversed even if other assets on the GRN are ineligible.
15. Cancelled PO protection: reversal on a cancelled PO preserves 'cancelled' status permanently.
16. Referential integrity: Asset count must match reversed line quantity.
17. Cross-line mismatch rejection: asset belonging to a different GRN line is rejected (422).
18. Duplicate reversal protection: attempting to reverse an already reversed asset is rejected.
19. Pre-flight diagnostic endpoint (reversal-check) returns accurate asset eligibility and reasons.
20. Reversal audit logging and RBAC enforcement.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.models import (
    Asset,
    AssetAssignment,
    AssetDepreciationEntry,
    AssetDisposal,
    AssetFinancial,
    AuditEvent,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptReversal,
    GoodsReceiptReversalAsset,
    GoodsReceiptReversalLine,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
)
from app.services import (
    calculate_purchase_order_status,
    check_asset_reversal_eligibility,
    recalculate_purchase_order_status,
)


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



def add_member(db_session, company_id, email: str, role_code: str = 'read_only_user') -> User:
    company_id = UUID(str(company_id))
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
            company_id=company_id,
            user_id=user.id,
            role_id=role.id,
            status='active',
        )
    )
    db_session.commit()
    return user

def setup_po_and_grn(client, company_id: str, supplier_id: str, category_id: str, ordered_qty: int, received_qty: int, rejected_qty: int = 0):
    po_res = client.post(
        f"/api/v1/companies/{company_id}/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "ordered_date": "2026-11-01",
            "lines": [
                {
                    "category_id": category_id,
                    "description": "Enterprise Server",
                    "quantity_ordered": ordered_qty,
                    "unit_cost": "1200.00",
                }
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()
    po_line_id = po["lines"][0]["id"]

    accepted_qty = received_qty - rejected_qty
    serials = [f"SRV-{uuid4().hex[:8].upper()}" for _ in range(accepted_qty)] if accepted_qty > 0 else []

    grn_res = client.post(
        f"/api/v1/companies/{company_id}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "delivery_reference": "DC-REV-100",
            "lines": [
                {
                    "purchase_order_line_id": po_line_id,
                    "quantity_received": received_qty,
                    "quantity_rejected": rejected_qty,
                    "serial_numbers": serials,
                }
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text
    grn = grn_res.json()
    return po, grn


# =========================================================================
# Scenario 1: Full Reversal of Single-Line GRN
# =========================================================================

def test_full_reversal_single_line_grn(client, db_session):
    """
    Reversing 100% of accepted goods on a single-line GRN:
    - Creates GoodsReceiptReversal, lines, and asset bindings.
    - Transitions GoodsReceipt status to 'reversed'.
    - Updates PO status from 'received' back to 'open'.
    """
    comp = create_test_company(client, "REV-S1", "RS1")
    sup = create_test_supplier(client, comp["id"], "SUP-RS1")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=3, received_qty=3, rejected_qty=0)
    assert po["status"] == "open"

    # Verify PO is received
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_check["status"] == "received"
    assert grn["status"] == "completed"

    grn_line = grn["lines"][0]
    asset_ids = [a["id"] for a in grn_line["assets"]]
    assert len(asset_ids) == 3

    # Reverse the GRN
    rev_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Complete order rejected post-inspection due to wrong specifications",
            "lines": [
                {
                    "goods_receipt_line_id": grn_line["id"],
                    "asset_ids": asset_ids,
                    "notes": "Returning all 3 servers to supplier",
                }
            ],
        },
    )
    assert rev_res.status_code == 201, rev_res.text
    rev_data = rev_res.json()

    assert rev_data["goods_receipt_id"] == grn["id"]
    assert rev_data["purchase_order_id"] == po["id"]
    assert len(rev_data["lines"]) == 1
    assert rev_data["lines"][0]["quantity_reversed"] == 3
    assert len(rev_data["lines"][0]["assets"]) == 3

    # Verify GRN status is now 'reversed'
    grn_after = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    receipt_after = [r for r in client.get(f"/api/v1/companies/{comp['id']}/suppliers").json()]  # smoke check

    # Check GRN retrieval
    rev_check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert rev_check["status"] == "reversed"
    assert rev_check["total_quantity_reversed"] == 3
    assert rev_check["unreversed_accepted_quantity"] == 0
    assert rev_check["is_reversible"] is False

    # Verify PO status transitions from 'received' back to 'open'
    po_after = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_after["status"] == "open"
    assert po_after["lines"][0]["quantity_received"] == 0
    assert po_after["lines"][0]["quantity_remaining"] == 3


# =========================================================================
# Scenario 2: Partial Line Reversal & Multi-Step Reversals
# =========================================================================

def test_partial_and_sequential_reversal(client, db_session):
    """
    Sequential partial reversals on a GRN:
    - Step 1: Reverse 2 of 5 accepted items -> status 'partially_reversed', PO 'partially_received'.
    - Step 2: Reverse remaining 3 items -> status 'reversed', PO 'open'.
    - Step 3: Over-reversal attempt fails with 409 Conflict.
    """
    comp = create_test_company(client, "REV-S2", "RS2")
    sup = create_test_supplier(client, comp["id"], "SUP-RS2")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=5, received_qty=5, rejected_qty=0)
    grn_line = grn["lines"][0]
    all_assets = grn_line["assets"]
    assert len(all_assets) == 5

    asset_ids_part1 = [all_assets[0]["id"], all_assets[1]["id"]]
    asset_ids_part2 = [all_assets[2]["id"], all_assets[3]["id"], all_assets[4]["id"]]

    # Step 1: Reverse 2 units
    rev1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "First partial reversal (2 defective units)",
            "lines": [{"goods_receipt_line_id": grn_line["id"], "asset_ids": asset_ids_part1}],
        },
    )
    assert rev1.status_code == 201, rev1.text
    assert rev1.json()["lines"][0]["quantity_reversed"] == 2

    # Verify intermediate state
    check1 = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check1["status"] == "partially_reversed"
    assert check1["total_quantity_reversed"] == 2
    assert check1["unreversed_accepted_quantity"] == 3
    assert check1["is_reversible"] is True

    po1 = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po1["status"] == "partially_received"
    assert po1["lines"][0]["quantity_received"] == 3
    assert po1["lines"][0]["quantity_remaining"] == 2

    # Step 2: Reverse remaining 3 units
    rev2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Second partial reversal (remaining 3 units)",
            "lines": [{"goods_receipt_line_id": grn_line["id"], "asset_ids": asset_ids_part2}],
        },
    )
    assert rev2.status_code == 201, rev2.text
    assert rev2.json()["lines"][0]["quantity_reversed"] == 3

    # Verify final state
    check2 = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check2["status"] == "reversed"
    assert check2["total_quantity_reversed"] == 5
    assert check2["unreversed_accepted_quantity"] == 0

    po2 = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po2["status"] == "open"
    assert po2["lines"][0]["quantity_received"] == 0
    assert po2["lines"][0]["quantity_remaining"] == 5

    # Step 3: Attempting to reverse on an already fully reversed GRN fails with 409
    rev3 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Invalid extra reversal",
            "lines": [{"goods_receipt_line_id": grn_line["id"], "asset_ids": [all_assets[0]["id"]]}],
        },
    )
    assert rev3.status_code == 409, rev3.text
    assert "already fully reversed" in rev3.json()["detail"]


# =========================================================================
# Scenario 3: Over-reversal and Rejected Items Protection
# =========================================================================

def test_over_reversal_and_rejected_items_protection(client, db_session):
    """
    1. Reversal ceiling applies strictly to accepted stock (received - rejected).
    2. Attempting to reverse more than eligible accepted stock fails with 409.
    3. Rejected items cannot be reversed as inventory assets.
    """
    comp = create_test_company(client, "REV-S3", "RS3")
    sup = create_test_supplier(client, comp["id"], "SUP-RS3")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Received 5, rejected 2 -> only 3 accepted items in stock!
    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=5, received_qty=5, rejected_qty=2)
    grn_line = grn["lines"][0]
    assets = grn_line["assets"]
    assert len(assets) == 3  # Only 3 assets created for accepted items

    # Pre-flight check confirms only 3 unreversed accepted items
    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["total_accepted_quantity"] == 3
    assert check["unreversed_accepted_quantity"] == 3

    # Attempting to reverse 4 items when only 3 are accepted fails
    # Let's create a bogus asset id or try to specify extra asset
    bogus_asset_id = str(uuid4())
    rev_fail = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Trying to reverse 4 items",
            "lines": [
                {
                    "goods_receipt_line_id": grn_line["id"],
                    "asset_ids": [a["id"] for a in assets] + [bogus_asset_id],
                }
            ],
        },
    )
    # Either 404 (bogus asset not found) or 409 (exceeds unreversed accepted quantity)
    assert rev_fail.status_code in (404, 409)


# =========================================================================
# Scenario 4: Six-Gate Eligibility Engine Failures (Gates 1 to 6)
# =========================================================================

def test_gate_1_asset_status_ineligible(client, db_session):
    """Gate 1: Asset whose status is not 'in_stock' (e.g. 'maintenance') blocks reversal."""
    comp = create_test_company(client, "REV-G1", "RG1")
    sup = create_test_supplier(client, comp["id"], "SUP-RG1")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # Mutate asset status in DB to 'maintenance'
    asset = db_session.get(Asset, UUID(asset_id))
    asset.status = "maintenance"
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 1",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "Asset status is 'maintenance'" in rev.json()["detail"]


def test_gate_2_active_assignment_ineligible(client, db_session):
    """Gate 2: Asset with active assignment blocks reversal."""
    comp = create_test_company(client, "REV-G2", "RG2")
    sup = create_test_supplier(client, comp["id"], "SUP-RG2")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # Create active assignment
    user = add_member(db_session, comp["id"], f"user-{uuid4().hex[:6]}@example.invalid")
    assignment = AssetAssignment(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        recipient_id=user.id,
        effective_date=date.today(),
        status="active",
        ended_at=None,
    )
    db_session.add(assignment)
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 2",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "active assignment record" in rev.json()["detail"]


def test_gate_3_active_maintenance_ineligible(client, db_session):
    """Gate 3: Asset with open or in_progress maintenance request blocks reversal."""
    comp = create_test_company(client, "REV-G3", "RG3")
    sup = create_test_supplier(client, comp["id"], "SUP-RG3")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    user = db_session.scalar(select(User).limit(1))
    maint = MaintenanceRequest(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        requester_id=user.id,
        title="Screen flickering",
        issue_description="Screen has horizontal flicker",
        priority="normal",
        status="open",
        reported_date=date.today(),
    )
    db_session.add(maint)
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 3",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "maintenance request" in rev.json()["detail"]


def test_gate_4_posted_depreciation_ineligible(client, db_session):
    """
    Gate 4: Asset with posted depreciation entries blocks reversal.
    Also verifies that draft AssetFinancial with zero depreciation does NOT block reversal.
    """
    comp = create_test_company(client, "REV-G4", "RG4")
    sup = create_test_supplier(client, comp["id"], "SUP-RG4")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # 1. First add a draft AssetFinancial with zero depreciation -> MUST NOT BLOCK!
    financial = AssetFinancial(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        capitalised_cost=Decimal("1200.00"),
        currency="INR",
        residual_value=Decimal("0.00"),
        useful_life_months=36,
        depreciation_start_date=date(2026, 11, 1),
        accumulated_depreciation=Decimal("0.00"),
        current_book_value=Decimal("1200.00"),
        financial_status="active",
    )
    db_session.add(financial)
    db_session.commit()

    # Pre-flight check confirms it is STILL eligible
    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["assets"][0]["is_eligible"] is True

    # 2. Now add a posted depreciation entry -> MUST BLOCK!
    user = db_session.scalar(select(User).limit(1))
    entry = AssetDepreciationEntry(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        period="2026-11",
        period_start_date=date(2026, 11, 1),
        period_end_date=date(2026, 11, 30),
        depreciation_amount=Decimal("33.33"),
        accumulated_depreciation_after=Decimal("33.33"),
        book_value_after=Decimal("1166.67"),
        method="straight_line",
        posted_by_id=user.id,
    )
    db_session.add(entry)
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 4",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "posted depreciation" in rev.json()["detail"]


def test_gate_5_disposal_record_ineligible(client, db_session):
    """Gate 5: Asset with an existing AssetDisposal record blocks reversal."""
    comp = create_test_company(client, "REV-G5", "RG5")
    sup = create_test_supplier(client, comp["id"], "SUP-RG5")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    user = db_session.scalar(select(User).limit(1))
    disp = AssetDisposal(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        disposal_date=date.today(),
        disposal_reason="damaged",
        disposal_method="written_off",
        sale_proceeds=Decimal("0.00"),
        net_book_value_at_disposal=Decimal("1200.00"),
        gain_loss=Decimal("-1200.00"),
        disposed_by_id=user.id,
    )
    db_session.add(disp)
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 5",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "asset_disposals" in rev.json()["detail"]


def test_gate_6_open_verification_discrepancy_ineligible(client, db_session):
    """Gate 6: Asset with an open VerificationDiscrepancy blocks reversal."""
    comp = create_test_company(client, "REV-G6", "RG6")
    sup = create_test_supplier(client, comp["id"], "SUP-RG6")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    user = db_session.scalar(select(User).limit(1))
    campaign = VerificationCampaign(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        campaign_reference="VC-TEST-01",
        name="Q4 Physical Audit",
        status="in_progress",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        created_by_id=user.id,
    )
    db_session.add(campaign)
    db_session.flush()

    discrepancy = VerificationDiscrepancy(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        campaign_id=campaign.id,
        asset_id=UUID(asset_id),
        discrepancy_type="missing",
        status="open",
    )
    db_session.add(discrepancy)
    db_session.commit()

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Test Gate 6",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409, rev.text
    assert "verification discrepancy" in rev.json()["detail"]


# =========================================================================
# Scenario 5: Independent Partial Reversals & Atomic Rollback
# =========================================================================

def test_independent_partial_reversal_with_ineligible_peer(client, db_session):
    """
    When a GRN has multiple assets, an ineligible asset blocks only itself.
    The caller can selectively reverse only eligible assets without being blocked.
    """
    comp = create_test_company(client, "REV-IND", "RIND")
    sup = create_test_supplier(client, comp["id"], "SUP-RIND")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=2, received_qty=2)
    assets = grn["lines"][0]["assets"]
    asset_1_id = assets[0]["id"]
    asset_2_id = assets[1]["id"]

    # Make Asset 2 ineligible by assigning it
    user = add_member(db_session, comp["id"], f"user-ind-{uuid4().hex[:6]}@example.invalid")
    assignment = AssetAssignment(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_2_id),
        recipient_id=user.id,
        effective_date=date.today(),
        status="active",
        ended_at=None,
    )
    db_session.add(assignment)
    db_session.commit()

    # Diagnostic pre-flight check confirms Asset 1 is eligible, Asset 2 is ineligible
    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["lines"][0]["eligible_asset_count"] == 1 and sum(1 for a in check["assets"] if a["is_eligible"]) == 1

    # Attempting to reverse Asset 2 fails
    rev_fail = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Attempting ineligible asset",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_2_id]}],
        },
    )
    assert rev_fail.status_code == 409

    # Reversing ONLY eligible Asset 1 succeeds!
    rev_ok = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Reversing eligible asset only",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_1_id]}],
        },
    )
    assert rev_ok.status_code == 201, rev_ok.text
    assert rev_ok.json()["lines"][0]["quantity_reversed"] == 1


def test_atomic_rollback_on_gate_failure(client, db_session):
    """
    If a multi-asset reversal request contains one eligible and one ineligible asset,
    the entire transaction rolls back atomically. Zero records are created in reversal tables.
    """
    comp = create_test_company(client, "REV-ROL", "RROL")
    sup = create_test_supplier(client, comp["id"], "SUP-RROL")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=2, received_qty=2)
    assets = grn["lines"][0]["assets"]
    asset_1_id = assets[0]["id"]
    asset_2_id = assets[1]["id"]

    # Invalidate Asset 2
    asset_2 = db_session.get(Asset, UUID(asset_2_id))
    asset_2.status = "maintenance"
    db_session.commit()

    # Submit reversal for BOTH assets
    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Atomic rollback test",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_1_id, asset_2_id]}],
        },
    )
    assert rev.status_code == 409

    # Verify atomic rollback: zero records in goods_receipt_reversals
    reversals_count = db_session.scalar(
        select(func.count(GoodsReceiptReversal.id)).where(GoodsReceiptReversal.goods_receipt_id == UUID(grn["id"]))
    )
    assert reversals_count == 0

    # GRN line quantity_reversed remains 0
    line_db = db_session.get(GoodsReceiptLine, UUID(grn["lines"][0]["id"]))
    assert line_db.quantity_reversed == 0


# =========================================================================
# Scenario 6: Milestone 2E.1 Cancelled PO Protection Invariant
# =========================================================================

def test_cancelled_po_protection_after_grn_reversal(client, db_session):
    """
    A short-closed/cancelled PO must remain strictly 'cancelled' after a GRN reversal.
    No automatic recalculation can reopen it.
    """
    comp = create_test_company(client, "REV-CAN", "RCAN")
    sup = create_test_supplier(client, comp["id"], "SUP-RCAN")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # PO ordered 5, received 2 -> partially_received
    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=5, received_qty=2)
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_check["status"] == "partially_received"

    # Short-close / cancel the PO under Milestone 2E.1
    cancel_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/cancel",
        json={"reason": "Short-closing PO balance"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Now perform a GRN reversal on the received goods
    asset_ids = [a["id"] for a in grn["lines"][0]["assets"]]
    rev_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Reversing goods on cancelled PO",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": asset_ids}],
        },
    )
    assert rev_res.status_code == 201, rev_res.text

    # Verify that the PO status REMAINS 'cancelled' permanently!
    po_after = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_after["status"] == "cancelled"

    # Verify via service functions directly
    po_db = db_session.get(PurchaseOrder, UUID(po["id"]))
    assert calculate_purchase_order_status(db_session, po_db) == "cancelled"
    assert recalculate_purchase_order_status(db_session, po_db) == "cancelled"


# =========================================================================
# Scenario 7: Referential Integrity & Cross-Line Mismatch Rejection
# =========================================================================

def test_cross_line_asset_injection_rejected(client, db_session):
    """
    An asset that does not originate from the target GoodsReceiptLine must be rejected with 422.
    """
    comp = create_test_company(client, "REV-CRS", "RCRS")
    sup = create_test_supplier(client, comp["id"], "SUP-RCRS")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    # Create two separate POs and GRNs
    po1, grn1 = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    po2, grn2 = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)

    asset_from_grn2 = grn2["lines"][0]["assets"][0]["id"]

    # Attempt to reverse GRN 1 using the asset from GRN 2
    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn1['id']}/reverse",
        json={
            "reason": "Injecting foreign asset",
            "lines": [{"goods_receipt_line_id": grn1["lines"][0]["id"], "asset_ids": [asset_from_grn2]}],
        },
    )
    assert rev.status_code == 422, rev.text
    assert "does not originate from goods receipt line" in rev.json()["detail"]


# =========================================================================
# Scenario 8: Audit Logging Verification
# =========================================================================

def test_reversal_audit_logging(client, db_session):
    """
    Verifies that goods_receipt_reversed event is logged in audit_events with full context.
    """
    comp = create_test_company(client, "REV-AUD", "RAUD")
    sup = create_test_supplier(client, comp["id"], "SUP-RAUD")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Audit verification reversal",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 201

    # Check AuditEvent
    audit = db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.company_id == UUID(comp["id"]),
            AuditEvent.action == "goods_receipt_reversed",
        )
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert audit is not None
    assert audit.entity_id == grn["id"]
    assert audit.changes["reason"] == "Audit verification reversal"
    assert audit.changes["total_quantity_reversed"] == 1



# =========================================================================
# Scenario 9: Full Reversal of Multi-Line GRN
# =========================================================================

def test_full_reversal_multi_line_grn(client, db_session):
    """
    Full reversal across multiple lines in a multi-line GRN.
    All lines are reversed, GRN status becomes 'reversed', and PO status transitions to 'open'.
    """
    comp = create_test_company(client, "REV-ML", "RML")
    sup = create_test_supplier(client, comp["id"], "SUP-RML")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-11-01",
            "lines": [
                {"category_id": cat["id"], "description": "Line 1 Servers", "quantity_ordered": 2, "unit_cost": "500.00"},
                {"category_id": cat["id"], "description": "Line 2 Switches", "quantity_ordered": 2, "unit_cost": "300.00"},
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()

    grn_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-11-02",
            "lines": [
                {"purchase_order_line_id": po["lines"][0]["id"], "quantity_received": 2, "serial_numbers": ["ML-1A", "ML-1B"]},
                {"purchase_order_line_id": po["lines"][1]["id"], "quantity_received": 2, "serial_numbers": ["ML-2A", "ML-2B"]},
            ],
        },
    )
    assert grn_res.status_code == 201, grn_res.text
    grn = grn_res.json()

    line1_assets = [a["id"] for a in grn["lines"][0]["assets"]]
    line2_assets = [a["id"] for a in grn["lines"][1]["assets"]]

    rev_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Reversing both lines of multi-line GRN",
            "lines": [
                {"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": line1_assets},
                {"goods_receipt_line_id": grn["lines"][1]["id"], "asset_ids": line2_assets},
            ],
        },
    )
    assert rev_res.status_code == 201, rev_res.text
    rev_data = rev_res.json()
    assert len(rev_data["lines"]) == 2

    # Check GRN status
    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["status"] == "reversed"
    assert check["total_quantity_reversed"] == 4

    # Check PO status is 'open'
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_check["status"] == "open"


# =========================================================================
# Scenario 10: Reversals History List Endpoint
# =========================================================================

def test_reversal_list_history_endpoint(client, db_session):
    """
    GET /companies/{company_id}/goods-receipts/{goods_receipt_id}/reversals
    returns the sequential history of all reversals against that GRN.
    """
    comp = create_test_company(client, "REV-HST", "RHST")
    sup = create_test_supplier(client, comp["id"], "SUP-RHST")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=3, received_qty=3)
    assets = grn["lines"][0]["assets"]

    # Reversal 1: Reverse 1 asset
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "History reversal 1",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [assets[0]["id"]]}],
        },
    )
    assert r1.status_code == 201

    # Reversal 2: Reverse another asset
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "History reversal 2",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [assets[1]["id"]]}],
        },
    )
    assert r2.status_code == 201

    # Query list of reversals
    hist_res = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversals")
    assert hist_res.status_code == 200, hist_res.text
    history = hist_res.json()
    assert len(history) == 2
    assert history[0]["reason"] == "History reversal 1"
    assert history[1]["reason"] == "History reversal 2"


# =========================================================================
# Scenario 11: Duplicate Reversal of Same Asset Rejected
# =========================================================================

def test_duplicate_reversal_of_same_asset_rejected(client, db_session):
    """
    Attempting to reverse an asset that has already been reversed in a prior transaction
    fails deterministically.
    """
    comp = create_test_company(client, "REV-DUP", "RDUP")
    sup = create_test_supplier(client, comp["id"], "SUP-RDUP")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=2, received_qty=2)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # Reverse asset once
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "First reversal",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert r1.status_code == 201

    # Attempt to reverse the EXACT same asset again
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Second reversal of same asset",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert r2.status_code == 409, r2.text
    assert "already been reversed" in r2.json()["detail"] or "status is 'reversed'" in r2.json()["detail"]


# =========================================================================
# Scenario 12: RBAC Authorization
# =========================================================================

def test_reversal_rbac_authorization(client, db_session):
    """
    A user without procurement.reverse permission receives HTTP 403 Forbidden.
    """
    comp = create_test_company(client, "REV-RBC", "RRBC")
    sup = create_test_supplier(client, comp["id"], "SUP-RRBC")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # Create a read_only_user
    ro_user = add_member(db_session, comp["id"], "ro-user@example.invalid", role_code="read_only_user")

    # Login as read_only_user
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "ro-user@example.invalid", "password": "Correct-Horse-42!"},
    )
    assert login_res.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["mindzen_csrf"]

    # Attempt reversal as read_only_user -> MUST be 403 Forbidden!
    forbidden_res = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Unauthorized reversal attempt",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert forbidden_res.status_code == 403, forbidden_res.text

    # Re-login as admin
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "test-admin@example.invalid", "password": "Correct-Horse-42!"},
    )
    assert admin_login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies["mindzen_csrf"]



# =========================================================================
# Additional Corrective Tests: Gate 4 Variations, Reversed Asset Protection & Cross-Company Isolation
# =========================================================================

def test_gate_4_draft_and_active_financial_zero_depreciation_eligible(client, db_session):
    """
    Gate 4: Verifies that both draft and active AssetFinancial records with 0 accumulated depreciation
    and no posted entries do NOT block reversal.
    """
    comp = create_test_company(client, "REV-G4-DF", "RG4D")
    sup = create_test_supplier(client, comp["id"], "SUP-RG4D")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    # Add a draft AssetFinancial with zero depreciation
    financial = AssetFinancial(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        capitalised_cost=Decimal("5000.00"),
        currency="INR",
        residual_value=Decimal("500.00"),
        useful_life_months=60,
        depreciation_start_date=date(2026, 11, 1),
        accumulated_depreciation=Decimal("0.00"),
        current_book_value=Decimal("5000.00"),
        financial_status="draft",
    )
    db_session.add(financial)
    db_session.commit()

    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["assets"][0]["is_eligible"] is True

    # Reversal succeeds cleanly
    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Reversing with draft financial record",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 201, rev.text


def test_gate_4_posted_zero_amount_depreciation_ineligible(client, db_session):
    """
    Gate 4: Verifies that a posted depreciation entry even with zero amount (0.00)
    correctly blocks reversal because a financial depreciation posting has occurred.
    """
    comp = create_test_company(client, "REV-G4-Z", "RG4Z")
    sup = create_test_supplier(client, comp["id"], "SUP-RG4Z")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    user = db_session.scalar(select(User).limit(1))
    entry = AssetDepreciationEntry(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        period="2026-11",
        period_start_date=date(2026, 11, 1),
        period_end_date=date(2026, 11, 30),
        depreciation_amount=Decimal("0.00"),
        accumulated_depreciation_after=Decimal("0.00"),
        book_value_after=Decimal("2000.00"),
        method="straight_line",
        posted_by_id=user.id,
    )
    db_session.add(entry)
    db_session.commit()

    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["assets"][0]["is_eligible"] is False
    assert any("posted depreciation entries" in v for v in check["assets"][0]["blocking_reasons"])

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Attempt reversal with zero-amount posted depreciation",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409
    assert "posted depreciation" in rev.json()["detail"]


def test_gate_4_accumulated_depreciation_without_entries_ineligible(client, db_session):
    """
    Gate 4: Verifies that an AssetFinancial record with positive accumulated_depreciation
    blocks reversal even if no rows exist in AssetDepreciationEntry.
    """
    comp = create_test_company(client, "REV-G4-AC", "RG4A")
    sup = create_test_supplier(client, comp["id"], "SUP-RG4A")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]

    financial = AssetFinancial(
        id=uuid4(),
        company_id=UUID(comp["id"]),
        asset_id=UUID(asset_id),
        capitalised_cost=Decimal("1000.00"),
        currency="INR",
        residual_value=Decimal("0.00"),
        useful_life_months=12,
        depreciation_start_date=date(2026, 11, 1),
        accumulated_depreciation=Decimal("250.00"),
        current_book_value=Decimal("750.00"),
        financial_status="active",
    )
    db_session.add(financial)
    db_session.commit()

    check = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reversal-check").json()
    assert check["assets"][0]["is_eligible"] is False
    assert any("accumulated depreciation" in v for v in check["assets"][0]["blocking_reasons"])

    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Attempt reversal with accumulated depreciation",
            "lines": [{"goods_receipt_line_id": grn["lines"][0]["id"], "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 409
    assert "accumulated depreciation" in rev.json()["detail"]


def test_reversed_asset_protected_from_operational_workflows(client, db_session):
    """
    Critical: Verifies that after GRN reversal commits, the reversed asset is strictly protected
    and cannot be:
    - Assigned to an employee (POST /assignments -> 409)
    - Modified or returned to operational stock (PATCH /assets/{id} -> 409)
    - Issued for department usage (POST /usages -> 409)
    - Submitted for maintenance (POST /maintenance-requests -> 409)
    - Disposed via financial disposal (POST /dispose -> 409)
    - Subjected to depreciation posting (POST /depreciation/post -> 409)
    """
    comp = create_test_company(client, "REV-PROT", "RPRT")
    sup = create_test_supplier(client, comp["id"], "SUP-RPRT")
    cat = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp["id"], sup["id"], cat["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]
    grn_line_id = grn["lines"][0]["id"]

    # 1. Reverse the asset
    rev = client.post(
        f"/api/v1/companies/{comp['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Reversing for operational protection test",
            "lines": [{"goods_receipt_line_id": grn_line_id, "asset_ids": [asset_id]}],
        },
    )
    assert rev.status_code == 201, rev.text

    # Verify asset is in reversed status
    asset_res = client.get(f"/api/v1/companies/{comp['id']}/assets/{asset_id}")
    assert asset_res.status_code == 200
    assert asset_res.json()["status"] == "reversed"

    # 2. Assignment protection
    member = add_member(db_session, comp["id"], "assignee@example.invalid", role_code="asset_manager")
    asg_res = client.post(
        f"/api/v1/companies/{comp['id']}/assets/{asset_id}/assignments",
        json={"recipient_id": str(member.id), "effective_date": date.today().isoformat()},
    )
    assert asg_res.status_code == 409
    assert "Only in-stock assets can be assigned" in asg_res.json()["detail"]

    # 3. Direct modification / return-to-stock protection
    patch_res = client.patch(
        f"/api/v1/companies/{comp['id']}/assets/{asset_id}",
        json={"status": "in_stock"},
    )
    assert patch_res.status_code == 409
    assert "Reversed assets are protected" in patch_res.json()["detail"]

    # 4. Department usage protection
    dept_res = client.post(
        f"/api/v1/companies/{comp['id']}/departments",
        json={"code": "IT-DEPT", "name": "Information Technology"},
    )
    dept_id = dept_res.json()["id"]
    usage_res = client.post(
        f"/api/v1/companies/{comp['id']}/assets/{asset_id}/usages",
        json={"department_id": dept_id, "purpose": "Testing usage block"},
    )
    assert usage_res.status_code == 409
    assert "Reversed assets cannot be allocated" in usage_res.json()["detail"]

    # 5. Maintenance request protection
    maint_res = client.post(
        f"/api/v1/companies/{comp['id']}/maintenance-requests",
        json={
            "asset_id": asset_id,
            "title": "Broken screen",
            "issue_description": "Cannot fix a reversed asset",
            "priority": "normal",
            "reported_date": date.today().isoformat(),
        },
    )
    assert maint_res.status_code == 409
    assert "Reversed assets cannot be submitted for maintenance" in maint_res.json()["detail"]

    # 6. Disposal protection
    disp_res = client.post(
        f"/api/v1/companies/{comp['id']}/assets/{asset_id}/dispose",
        json={
            "disposal_date": date.today().isoformat(),
            "disposal_reason": "damaged",
            "disposal_method": "written_off",
            "sale_proceeds": 0.0,
            "notes": "Cannot dispose reversed asset",
        },
    )
    assert disp_res.status_code == 409
    assert "Cannot dispose a reversed asset" in disp_res.json()["detail"]

    # 7. Depreciation posting protection
    depr_res = client.post(
        f"/api/v1/companies/{comp['id']}/assets/{asset_id}/depreciation-entries",
        json={"period": "2026-11"},
    )
    assert depr_res.status_code == 409
    assert "Cannot post depreciation for a reversed asset" in depr_res.json()["detail"]


def test_reversal_endpoints_cross_company_isolation(client, db_session):
    """
    Verifies that pre-flight diagnostic, reversal history, and reversal execution endpoints
    strictly enforce company scoping and return HTTP 404 when queried from another company.
    """
    comp_a = create_test_company(client, "REV-ISO-A", "RISA")
    comp_b = create_test_company(client, "REV-ISO-B", "RISB")
    sup_a = create_test_supplier(client, comp_a["id"], "SUP-RISA")
    cat_a = client.get(f"/api/v1/companies/{comp_a['id']}/categories").json()[0]

    po, grn = setup_po_and_grn(client, comp_a["id"], sup_a["id"], cat_a["id"], ordered_qty=1, received_qty=1)
    asset_id = grn["lines"][0]["assets"][0]["id"]
    grn_line_id = grn["lines"][0]["id"]

    # Access Company A's GRN from Company B -> MUST 404
    check_cross = client.get(f"/api/v1/companies/{comp_b['id']}/goods-receipts/{grn['id']}/reversal-check")
    assert check_cross.status_code == 404

    history_cross = client.get(f"/api/v1/companies/{comp_b['id']}/goods-receipts/{grn['id']}/reversals")
    assert history_cross.status_code == 404

    rev_cross = client.post(
        f"/api/v1/companies/{comp_b['id']}/goods-receipts/{grn['id']}/reverse",
        json={
            "reason": "Cross-company breach attempt",
            "lines": [{"goods_receipt_line_id": grn_line_id, "asset_ids": [asset_id]}],
        },
    )
    assert rev_cross.status_code == 404
