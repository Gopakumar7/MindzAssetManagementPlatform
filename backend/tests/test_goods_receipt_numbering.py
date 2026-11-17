"""Comprehensive test suite for Goods Receipt Note (GRN) Reference Numbering Integration.

MindZen ERP - Milestone 2D:
- Centralized reference numbering: {COMPANY_PREFIX}-GRN-{FINANCIAL_YEAR}-{SEQUENCE}
- Financial year: April 1 to March 31 in Asia/Kolkata timezone
- Sequence padding: 5 digits (00001, 00002, ...)
- Atomic allocation within GRN transaction
- Safe rollback without orphaned numbers or assets
- Rejection of manual receipt_number (HTTP 422)
- Rejection of missing sequence provisioning (HTTP 422)
- March 31 / April 1 financial-year boundary rollover
- Multi-asset failure rollback with zero orphaned assets
- Historical reference preservation
- PO origin neutrality (INTERNAL and EXTERNAL POs)
- PostgreSQL concurrency with row-level locking
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
import os
from uuid import UUID, uuid4
from fastapi import HTTPException

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Asset,
    AssetCategory,
    Company,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ReferenceSequence,
    Supplier,
    User,
)
from app.reference_service import (
    DEFAULT_TIMEZONE,
    ReferenceNumberService,
    ReservedPrefixCollisionError,
    SequenceNotFoundError,
)
from app.schemas import CompanyCreate, GoodsReceiptCreate
from app.security_seed import seed_security_defaults
from app.services import create_company


def create_test_company_with_prefix(client, code: str, prefix: str):
    res = client.post(
        "/api/v1/companies",
        json={
            "code": prefix,
            "name": f"Company {code}",
            "number_prefix": prefix,
            "is_active": True,
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


def get_default_category(client, company_id: str):
    cats = client.get(f"/api/v1/companies/{company_id}/categories").json()
    assert len(cats) > 0
    return cats[0]


def create_test_internal_po(client, company_id: str, supplier_id: str, cat_id: str, qty: int = 10, unit_cost: str = "100.00"):
    res = client.post(
        f"/api/v1/companies/{company_id}/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "ordered_date": "2026-10-15",
            "lines": [
                {
                    "category_id": cat_id,
                    "description": "Standard Test Item",
                    "quantity_ordered": qty,
                    "unit_cost": unit_cost,
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_external_po(client, company_id: str, supplier_code: str, cat_id: str, ext_ref: str, qty: int = 10, unit_cost: str = "100.00"):
    payload = {
        "external_reference": ext_ref,
        "source_system": "SAP",
        "source_instance_id": "SAP-PROD-1",
        "supplier_code": supplier_code,
        "ordered_date": "2026-10-15",
        "lines": [
            {
                "external_line_id": "LINE-EXT-01",
                "category_id": cat_id,
                "description": "External Test Item",
                "quantity_ordered": qty,
                "unit_cost": unit_cost,
            }
        ],
    }
    res = client.post(
        f"/api/v1/companies/{company_id}/purchase-orders/external-import",
        json=payload,
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


# ==============================================================================
# 1. First GRN for MindZen Demo & WeWin Demo
# ==============================================================================

def test_first_grn_for_mindzen_demo(client, db_session):
    """
    Scenario 1: First GRN created for a company with prefix MZ in FY 2026-27
    allocates MZ-GRN-2026-27-00001.
    """
    comp = create_test_company_with_prefix(client, "MZ-DEMO-GRN", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-MZ-1")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    po_line_id = po["lines"][0]["id"]

    rcv_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "delivery_reference": "DN-MZ-001",
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": 2}],
        },
    )
    assert rcv_res.status_code == 201, rcv_res.text
    grn = rcv_res.json()
    assert grn["receipt_number"] == "MZ-GRN-2026-27-00001"
    assert grn["received_date"] == "2026-10-15"
    assert grn["delivery_reference"] == "DN-MZ-001"


def test_first_grn_for_wewin_demo(client, db_session):
    """
    Scenario 2: First GRN created for a company with prefix WW in FY 2026-27
    allocates WW-GRN-2026-27-00001, isolated from MZ.
    """
    comp = create_test_company_with_prefix(client, "WW-DEMO-GRN", "WW")
    sup = create_test_supplier(client, comp["id"], "SUP-WW-1")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    po_line_id = po["lines"][0]["id"]

    rcv_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "delivery_reference": "DN-WW-001",
            "lines": [{"purchase_order_line_id": po_line_id, "quantity_received": 2}],
        },
    )
    assert rcv_res.status_code == 201, rcv_res.text
    grn = rcv_res.json()
    assert grn["receipt_number"] == "WW-GRN-2026-27-00001"


# ==============================================================================
# 2. Sequential Numbering and Padding
# ==============================================================================

def test_sequential_grn_numbering_within_same_company(client, db_session):
    """
    Scenario 3: Sequential GRN numbering increments sequence monotonically (00001, 00002, 00003).
    """
    comp = create_test_company_with_prefix(client, "SEQ-GRN", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-SEQ-1")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=15)
    line_id = po["lines"][0]["id"]

    expected = ["MZ-GRN-2026-27-00001", "MZ-GRN-2026-27-00002", "MZ-GRN-2026-27-00003"]
    for expected_num in expected:
        res = client.post(
            f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
            json={
                "received_date": "2026-10-15",
                "lines": [{"purchase_order_line_id": line_id, "quantity_received": 1}],
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["receipt_number"] == expected_num


# ==============================================================================
# 3. Financial Year Rollover & Boundaries
# ==============================================================================

def test_financial_year_rollover(client, db_session):
    """
    Scenario 4: Receipts in FY 2026-27 allocate 2026-27 sequence.
    Receipts in FY 2027-28 start fresh at 00001 for 2027-28.
    """
    comp = create_test_company_with_prefix(client, "FY-ROLL", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-FYR")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=10)
    line_id = po["lines"][0]["id"]

    # Receipt in 2026-27
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert r1.status_code == 201
    assert r1.json()["receipt_number"] == "MZ-GRN-2026-27-00001"

    # Receipt in 2027-28 (business receipt date in May 2027)
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2027-05-10",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert r2.status_code == 201
    assert r2.json()["receipt_number"] == "MZ-GRN-2027-28-00001"

    # Another receipt in 2027-28 increments to 00002
    r3 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2027-06-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert r3.status_code == 201
    assert r3.json()["receipt_number"] == "MZ-GRN-2027-28-00002"


def test_march_31_april_1_boundary(client, db_session):
    """
    Scenario 19: Financial year boundary around 31 March and 1 April (Asia/Kolkata timezone).
    - 2026-03-31 belongs to FY 2025-26.
    - 2026-04-01 belongs to FY 2026-27.
    """
    comp = create_test_company_with_prefix(client, "FY-BOUND", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-FYB")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=10)
    line_id = po["lines"][0]["id"]

    # 31 March 2026 -> FY 2025-26
    r_mar31 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-03-31",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 1}],
        },
    )
    assert r_mar31.status_code == 201
    assert r_mar31.json()["receipt_number"] == "MZ-GRN-2025-26-00001"

    # 1 April 2026 -> FY 2026-27
    r_apr01 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-04-01",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 1}],
        },
    )
    assert r_apr01.status_code == 201
    assert r_apr01.json()["receipt_number"] == "MZ-GRN-2026-27-00001"


def test_backdated_receipt_date(client, db_session):
    """
    Scenario 5: Backdated receipt date allocates sequence for that historical financial year.
    Receipt dated 2025-08-12 receives MZ-GRN-2025-26-00001 regardless of current system date.
    """
    comp = create_test_company_with_prefix(client, "BACKDATE-GRN", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-BD")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2025-08-12",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["receipt_number"] == "MZ-GRN-2025-26-00001"


# ==============================================================================
# 4. Multiple GRNs and Partial Receipt Lifecycle
# ==============================================================================

def test_multiple_grns_and_partial_receipt_workflow(client, db_session):
    """
    Scenario 6 & 7: Multiple GRNs against a single Purchase Order with progressive
    fulfillment (open -> partially_received -> received).
    """
    comp = create_test_company_with_prefix(client, "MULTI-GRN", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-MGRN")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=10)
    po_id = po["id"]
    line_id = po["lines"][0]["id"]

    # GRN 1: Receive 3 -> status becomes partially_received
    g1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 3}],
        },
    ).json()
    assert g1["receipt_number"] == "MZ-GRN-2026-27-00001"
    po_check1 = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check1["status"] == "partially_received"
    assert po_check1["lines"][0]["quantity_received"] == 3
    assert po_check1["lines"][0]["quantity_remaining"] == 7

    # GRN 2: Receive 4 -> status remains partially_received
    g2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-10-16",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 4}],
        },
    ).json()
    assert g2["receipt_number"] == "MZ-GRN-2026-27-00002"
    po_check2 = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check2["status"] == "partially_received"
    assert po_check2["lines"][0]["quantity_received"] == 7
    assert po_check2["lines"][0]["quantity_remaining"] == 3

    # GRN 3: Receive remaining 3 -> status becomes received
    g3 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}/goods-receipts",
        json={
            "received_date": "2026-10-17",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 3}],
        },
    ).json()
    assert g3["receipt_number"] == "MZ-GRN-2026-27-00003"
    po_check3 = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po_id}").json()
    assert po_check3["status"] == "received"
    assert po_check3["lines"][0]["quantity_received"] == 10
    assert po_check3["lines"][0]["quantity_remaining"] == 0


# ==============================================================================
# 5. PO Origin Neutrality (INTERNAL vs EXTERNAL)
# ==============================================================================

def test_grn_against_internal_purchase_order(client, db_session):
    """
    Scenario 8: GRN against an internally created PO receives standard numbering.
    """
    comp = create_test_company_with_prefix(client, "GRN-INT-PO", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-INT")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert res.status_code == 201
    assert res.json()["receipt_number"] == "MZ-GRN-2026-27-00001"


def test_grn_against_external_purchase_order(client, db_session):
    """
    Scenario 9: GRN against an externally imported PO receives standard numbering
    from the exact same central sequence.
    """
    comp = create_test_company_with_prefix(client, "GRN-EXT-PO", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-EXT")
    cat = get_default_category(client, comp["id"])
    po = create_test_external_po(client, comp["id"], sup["code"], cat["id"], ext_ref="SAP-PO-9999", qty=8)
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "delivery_reference": "DEL-SAP-99",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 4}],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["receipt_number"] == "MZ-GRN-2026-27-00001"
    assert res.json()["purchase_order_id"] == po["id"]


def test_grn_coexistence_internal_and_external_pos(client, db_session):
    """
    GRNs against internal and external POs share the sequential numbering stream
    within the same company.
    """
    comp = create_test_company_with_prefix(client, "GRN-COEXIST", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-COEX")
    cat = get_default_category(client, comp["id"])

    # 1. Internal PO
    po_int = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    # 2. External PO
    po_ext = create_test_external_po(client, comp["id"], sup["code"], cat["id"], ext_ref="SAP-COEX-01", qty=5)

    # GRN 1 against Internal PO
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_int['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": po_int["lines"][0]["id"], "quantity_received": 2}],
        },
    ).json()
    assert r1["receipt_number"] == "MZ-GRN-2026-27-00001"

    # GRN 2 against External PO
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po_ext['id']}/goods-receipts",
        json={
            "received_date": "2026-10-16",
            "lines": [{"purchase_order_line_id": po_ext["lines"][0]["id"], "quantity_received": 2}],
        },
    ).json()
    assert r2["receipt_number"] == "MZ-GRN-2026-27-00002"


# ==============================================================================
# 6. Manual Receipt Number Rejection & Missing Sequence Provisioning
# ==============================================================================

def test_manual_receipt_number_rejected_with_422(client, db_session):
    """
    Scenario 18: Manual receipt_number provided by client is rejected with HTTP 422.
    References are automatically generated by the reference numbering service.
    """
    comp = create_test_company_with_prefix(client, "MAN-REJ", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-MAN")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "receipt_number": "CUSTOM-GRN-123",
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert res.status_code == 422
    assert "Manual goods receipt numbers are not permitted" in res.json()["detail"]


def test_missing_sequence_provisioning_rejected_with_422(client, db_session):
    """
    Scenario 17: Company without provisioned goods_receipt numbering rule returns HTTP 422.
    """
    comp = create_test_company_with_prefix(client, "NO-SEQ-PROV", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-NOPROV")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    # Delete the goods_receipt sequence for this company to simulate unprovisioned sequence
    db_session.query(ReferenceSequence).filter_by(
        company_id=UUID(comp["id"]), entity_type="goods_receipt"
    ).delete()
    db_session.commit()

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert res.status_code == 422
    assert "has not been provisioned with goods receipt numbering rules" in res.json()["detail"]


# ==============================================================================
# 7. Transaction Atomicity & Rollback Safety (Zero Orphaned Assets)
# ==============================================================================

def test_transaction_rollback_preserves_sequence_counter(client, db_session):
    """
    Scenario 11: When a transaction fails after allocating a sequence (e.g. over-receipt validation),
    the sequence number is not committed. The next valid receipt receives the unconsumed sequence number.
    """
    comp = create_test_company_with_prefix(client, "TX-ROLL-SEQ", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-TRS")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    # 1. Valid receipt -> 00001
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert r1.status_code == 201
    assert r1.json()["receipt_number"] == "MZ-GRN-2026-27-00001"

    # 2. Attempt receipt with quantity > remaining (4 > 3 remaining) -> fails with 422
    r_bad = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 4}],
        },
    )
    assert r_bad.status_code == 422
    assert "exceeds the remaining ordered quantity" in r_bad.json()["detail"]

    # 3. Next valid receipt -> receives 00002 without gaps
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 2}],
        },
    )
    assert r2.status_code == 201
    assert r2.json()["receipt_number"] == "MZ-GRN-2026-27-00002"


def test_failure_during_last_asset_registration_proves_complete_rollback(client, db_session, monkeypatch):
    """
    Scenario 15: Failure during the last asset registration in a multi-asset GRN
    proves complete transaction rollback (zero orphaned assets).
    """
    comp = create_test_company_with_prefix(client, "LAST-ASSET-FAIL", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-LAF")
    cat = get_default_category(client, comp["id"])

    # Create PO with 3 items
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    from app.api.v1.routes import procurement
    original_create_asset = procurement.create_asset
    call_count = 0

    def fail_on_third_asset(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise HTTPException(status_code=422, detail="Simulated failure during last asset registration")
        return original_create_asset(*args, **kwargs)

    monkeypatch.setattr(procurement, "create_asset", fail_on_third_asset)

    # Attempt GRN receiving 3 items with serial numbers
    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 3,
                    "quantity_rejected": 0,
                    "serial_numbers": ["VALID-SN-01", "VALID-SN-02", "FAIL-SN-03"],
                }
            ],
        },
    )
    assert res.status_code == 422
    assert "Simulated failure during last asset registration" in res.json()["detail"]

    # Verify zero orphaned assets created in database
    db_session.expire_all()
    assets = db_session.scalars(select(Asset).where(Asset.company_id == comp_id)).all()
    assert len(assets) == 0, f"Expected 0 assets but found {len(assets)}"

    # Verify zero GRN records created
    receipts = db_session.scalars(select(GoodsReceipt).where(GoodsReceipt.company_id == comp_id)).all()
    assert len(receipts) == 0

    # Verify PO received quantity is still 0
    po_check = client.get(f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}").json()
    assert po_check["lines"][0]["quantity_received"] == 0
    assert po_check["status"] == "open"

    # Restore original create_asset and submit valid receipt
    monkeypatch.undo()

    r_valid = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["CLEAN-SN-01", "CLEAN-SN-02"],
                }
            ],
        },
    )
    assert r_valid.status_code == 201
    assert r_valid.json()["receipt_number"] == "MZ-GRN-2026-27-00001"


# ==============================================================================
# 8. Asset Registration Integration
# ==============================================================================

def test_asset_registration_integration(client, db_session):
    """
    Scenario 14: Serialized items received via GRN are automatically registered
    with central asset numbers (MZ-AST-000001...) in the same transaction.
    """
    comp = create_test_company_with_prefix(client, "AST-REG-INT", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-ARI")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=3, unit_cost="500.00")
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "delivery_reference": "DN-ARI-01",
            "lines": [
                {
                    "purchase_order_line_id": line_id,
                    "quantity_received": 2,
                    "quantity_rejected": 0,
                    "serial_numbers": ["ASSET-SN-101", "ASSET-SN-102"],
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    grn_data = res.json()
    assert grn_data["receipt_number"] == "MZ-GRN-2026-27-00001"

    assets_in_receipt = grn_data["lines"][0]["assets"]
    assert len(assets_in_receipt) == 2
    assert assets_in_receipt[0]["serial_number"] == "ASSET-SN-101"
    assert assets_in_receipt[0]["asset_number"] == "MZ-AST-000001"
    assert assets_in_receipt[1]["serial_number"] == "ASSET-SN-102"
    assert assets_in_receipt[1]["asset_number"] == "MZ-AST-000002"

    db_session.expire_all()
    db_assets = db_session.scalars(
        select(Asset).where(Asset.company_id == comp_id).order_by(Asset.created_at)
    ).all()
    assert len(db_assets) == 2
    assert db_assets[0].goods_receipt_line_id is not None
    assert db_assets[0].status == "in_stock"
    assert db_assets[0].acquisition_cost == Decimal("500.00")
    assert db_assets[0].vendor_reference == sup["code"]


# ==============================================================================
# 9. Historical Reference Preservation & Immutability
# ==============================================================================

def test_historical_grn_references_remain_unchanged(client, db_session):
    """
    Scenario 13: Historical GRN references created prior to central numbering
    remain intact and unchanged in listing and retrieval endpoints.
    """
    comp = create_test_company_with_prefix(client, "HIST-GRN", "MZ")
    comp_id = UUID(comp["id"])
    sup = create_test_supplier(client, comp["id"], "SUP-HIST")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    po_id = UUID(po["id"])

    # Directly insert historical GRN with legacy reference format
    hist_grn = GoodsReceipt(
        company_id=comp_id,
        purchase_order_id=po_id,
        receipt_number="LEGACY-GRN-2023-9999",
        received_date=date(2023, 5, 20),
        delivery_reference="DN-HIST-01",
    )
    db_session.add(hist_grn)
    db_session.commit()

    # Retrieve all GRNs via API
    list_res = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts")
    assert list_res.status_code == 200
    receipt_numbers = [r["receipt_number"] for r in list_res.json()]
    assert "LEGACY-GRN-2023-9999" in receipt_numbers

    # Creating a new GRN via API allocates 00001 from central sequence without touching historical GRN
    new_res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": po["lines"][0]["id"], "quantity_received": 1}],
        },
    )
    assert new_res.status_code == 201
    assert new_res.json()["receipt_number"] == "MZ-GRN-2026-27-00001"

    # Verify both exist
    list_res2 = client.get(f"/api/v1/companies/{comp['id']}/goods-receipts")
    r_nums2 = [r["receipt_number"] for r in list_res2.json()]
    assert "LEGACY-GRN-2023-9999" in r_nums2
    assert "MZ-GRN-2026-27-00001" in r_nums2


def test_grn_immutability_no_update_or_delete_route(client, db_session):
    """
    Scenario 12 & 20: GRN references are immutable after creation.
    No update (PUT/PATCH) or delete (DELETE) routes exist for goods receipts.
    Deletion of committed GRNs is strictly prohibited.
    """
    comp = create_test_company_with_prefix(client, "GRN-IMMUT", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-IMM")
    cat = get_default_category(client, comp["id"])
    po = create_test_internal_po(client, comp["id"], sup["id"], cat["id"], qty=5)
    line_id = po["lines"][0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{po['id']}/goods-receipts",
        json={
            "received_date": "2026-10-15",
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": 1}],
        },
    )
    assert res.status_code == 201
    grn_id = res.json()["id"]

    # PUT attempt -> rejected (no update route exists)
    put_res = client.put(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn_id}", json={"receipt_number": "MODIFIED"})
    assert put_res.status_code in (404, 405)

    # PATCH attempt -> rejected (no patch route exists)
    patch_res = client.patch(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn_id}", json={"notes": "Updated"})
    assert patch_res.status_code in (404, 405)

    # DELETE attempt -> rejected (deletion of committed GRNs is prohibited)
    del_res = client.delete(f"/api/v1/companies/{comp['id']}/goods-receipts/{grn_id}")
    assert del_res.status_code in (404, 405)


# ==============================================================================
# 10. Multi-Company Isolation
# ==============================================================================

def test_company_isolation(client, db_session):
    """
    Scenario 16: Two independent companies maintain completely independent sequences.
    """
    comp_a = create_test_company_with_prefix(client, "ISOL-A", "CA")
    comp_b = create_test_company_with_prefix(client, "ISOL-B", "CB")

    sup_a = create_test_supplier(client, comp_a["id"], "SUP-CA")
    sup_b = create_test_supplier(client, comp_b["id"], "SUP-CB")

    cat_a = get_default_category(client, comp_a["id"])
    cat_b = get_default_category(client, comp_b["id"])

    po_a = create_test_internal_po(client, comp_a["id"], sup_a["id"], cat_a["id"], qty=10)
    po_b = create_test_internal_po(client, comp_b["id"], sup_b["id"], cat_b["id"], qty=10)

    # 1. First receipt in Company A -> CA-GRN-2026-27-00001
    r_a1 = client.post(
        f"/api/v1/companies/{comp_a['id']}/purchase-orders/{po_a['id']}/goods-receipts",
        json={"received_date": "2026-10-15", "lines": [{"purchase_order_line_id": po_a["lines"][0]["id"], "quantity_received": 1}]},
    ).json()
    assert r_a1["receipt_number"] == "CA-GRN-2026-27-00001"

    # 2. First receipt in Company B -> CB-GRN-2026-27-00001
    r_b1 = client.post(
        f"/api/v1/companies/{comp_b['id']}/purchase-orders/{po_b['id']}/goods-receipts",
        json={"received_date": "2026-10-15", "lines": [{"purchase_order_line_id": po_b["lines"][0]["id"], "quantity_received": 1}]},
    ).json()
    assert r_b1["receipt_number"] == "CB-GRN-2026-27-00001"

    # 3. Second receipt in Company A -> CA-GRN-2026-27-00002
    r_a2 = client.post(
        f"/api/v1/companies/{comp_a['id']}/purchase-orders/{po_a['id']}/goods-receipts",
        json={"received_date": "2026-10-16", "lines": [{"purchase_order_line_id": po_a["lines"][0]["id"], "quantity_received": 1}]},
    ).json()
    assert r_a2["receipt_number"] == "CA-GRN-2026-27-00002"

    # Company B sequence remains at 00001
    seq_b = db_session.scalar(
        select(ReferenceSequence.current_value).where(
            ReferenceSequence.company_id == UUID(comp_b["id"]),
            ReferenceSequence.entity_type == "goods_receipt",
        )
    )
    assert seq_b == 1


# ==============================================================================
# 11. PostgreSQL Concurrency Integration
# ==============================================================================

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL concurrency integration requires TEST_DATABASE_URL")
def test_concurrent_grn_creation_postgresql():
    """
    Scenario 10: Concurrent GRN creation with independent PostgreSQL sessions.
    Row-level locking guarantees unique, sequential numbers with zero collisions or duplicates.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = SessionLocal()

    try:
        seed_security_defaults(setup)
        comp = create_company(
            setup,
            CompanyCreate(code="CGC", name="Conc GRN Company", number_prefix="CGC"),
        )
        cat = setup.query(AssetCategory).filter_by(company_id=comp.id, code="LAPTOP").one()
        sup = Supplier(company_id=comp.id, code="SUP-CONC-GRN", name="Conc Supplier")
        user = User(email=f"conc-actor-{uuid4().hex[:8]}@example.invalid", password_hash="test-hash", is_active=True)
        setup.add_all([sup, user])
        setup.flush()

        po = PurchaseOrder(
            company_id=comp.id,
            supplier_id=sup.id,
            order_number=f"CGC-PO-CONC-{uuid4().hex[:6]}",
            status="open",
            ordered_date=date(2026, 10, 15),
        )
        setup.add(po)
        setup.flush()

        # Create 10 lines with 5 quantity ordered each
        lines = []
        for i in range(10):
            line = PurchaseOrderLine(
                company_id=comp.id,
                purchase_order_id=po.id,
                category_id=cat.id,
                description=f"Conc Line {i}",
                quantity_ordered=10,
                unit_cost=Decimal("100.00"),
                line_number=i + 1,
            )
            setup.add(line)
            lines.append(line)
        setup.commit()

        comp_id = comp.id
        po_id = po.id
        line_ids = [line.id for line in lines]

        def create_grn_worker(index: int) -> str:
            with SessionLocal() as session:
                ref = ReferenceNumberService.allocate(
                    session,
                    comp_id,
                    "goods_receipt",
                    business_date=date(2026, 10, 16),
                    is_permanent=False,
                )
                grn = GoodsReceipt(
                    company_id=comp_id,
                    purchase_order_id=po_id,
                    receipt_number=ref,
                    received_date=date(2026, 10, 16),
                )
                session.add(grn)
                session.flush()

                grn_line = GoodsReceiptLine(
                    company_id=comp_id,
                    goods_receipt_id=grn.id,
                    purchase_order_id=po_id,
                    purchase_order_line_id=line_ids[index % len(line_ids)],
                    quantity_received=1,
                    quantity_rejected=0,
                )
                session.add(grn_line)
                session.commit()
                return ref

        # Run 10 concurrent transactions
        with ThreadPoolExecutor(max_workers=5) as executor:
            allocated_numbers = list(executor.map(create_grn_worker, range(10)))

        assert len(allocated_numbers) == 10
        assert len(set(allocated_numbers)) == 10, "Duplicate GRN references allocated under concurrency!"
        expected_set = {f"CGC-GRN-2026-27-{i:05d}" for i in range(1, 11)}
        assert set(allocated_numbers) == expected_set

    finally:
        setup.close()
        engine.dispose()
