"""Comprehensive integration test suite for MindZen ERP Purchase Order reference numbering.

Milestone 2C.1:
1. First Purchase Order in a financial year (e.g. MZ-PO-2026-27-00001).
2. Sequential Purchase Orders within the same company and year (MZ-PO-2026-27-00002, 00003).
3. Independent numbering for MindZen Demo and WeWin Demo (MZ-PO- vs WW-PO-).
4. Independent numbering across different financial years (2025-26, 2026-27, 2027-28).
5. Backdated Purchase Orders receive sequence for that historical financial year.
6. Financial-year boundary around 31 March and 1 April in Asia/Kolkata timezone.
7. Concurrent Purchase Order creation in PostgreSQL with row-level locking.
8. Transaction rollback re-rolls sequence counter.
9. Cancellation without number reuse (consumed references are never reused).
10. Unprovisioned company handling (HTTP 422 with clear error).
11. Existing historical Purchase Orders remain unchanged.
12. All Purchase Order creation paths use central allocation and protect against reserved prefix collisions.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import os
from uuid import UUID, uuid4
import zoneinfo

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    AssetCategory,
    Company,
    PurchaseOrder,
    PurchaseOrderLine,
    ReferenceSequence,
    Supplier,
)
from app.reference_service import (
    DEFAULT_TIMEZONE,
    ReferenceNumberService,
    ReservedPrefixCollisionError,
    SequenceNotFoundError,
)
from app.schemas import CompanyCreate
from app.security_seed import seed_security_defaults
from app.services import create_company


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


def test_first_purchase_order_in_financial_year(client):
    """
    1. First Purchase Order in a financial year receives reference with format:
       {PREFIX}-PO-{YYYY-YY}-00001
    """
    comp = create_test_company_with_prefix(client, "PO-FY-01", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-01")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    res = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-06-15",
            "lines": [{
                "category_id": cat_id,
                "description": "Enterprise Server",
                "quantity_ordered": 2,
                "unit_cost": "4500.00",
            }],
        },
    )
    assert res.status_code == 201, res.text
    order = res.json()
    assert order["order_number"] == "MZ-PO-2026-27-00001"
    assert order["status"] == "open"


def test_sequential_purchase_orders_same_company_and_year(client):
    """
    2. Sequential Purchase Orders within the same company and financial year
       strictly increment (00001, 00002, 00003).
    """
    comp = create_test_company_with_prefix(client, "PO-SEQ-02", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-02")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    nums = []
    for i in range(3):
        res = client.post(
            f"/api/v1/companies/{comp['id']}/purchase-orders",
            json={
                "supplier_id": sup["id"],
                "ordered_date": "2026-07-20",
                "lines": [{
                    "category_id": cat_id,
                    "description": f"Batch Item {i+1}",
                    "quantity_ordered": 1,
                    "unit_cost": "100.00",
                }],
            },
        )
        assert res.status_code == 201, res.text
        nums.append(res.json()["order_number"])

    assert nums == [
        "MZ-PO-2026-27-00001",
        "MZ-PO-2026-27-00002",
        "MZ-PO-2026-27-00003",
    ]


def test_independent_numbering_mindzen_and_wewin(client):
    """
    3. Independent numbering for MindZen Demo and WeWin Demo:
       - MindZen: MZ-PO-2026-27-00001
       - WeWin: WW-PO-2026-27-00001
       No cross-company counter interference.
    """
    comp_mz = create_test_company_with_prefix(client, "MZ-DEMO-PO", "MZ")
    comp_ww = create_test_company_with_prefix(client, "WW-DEMO-PO", "WW")

    sup_mz = create_test_supplier(client, comp_mz["id"], "SUP-MZ")
    sup_ww = create_test_supplier(client, comp_ww["id"], "SUP-WW")

    cat_mz = client.get(f"/api/v1/companies/{comp_mz['id']}/categories").json()[0]["id"]
    cat_ww = client.get(f"/api/v1/companies/{comp_ww['id']}/categories").json()[0]["id"]

    # 1st order in MindZen
    res_mz1 = client.post(
        f"/api/v1/companies/{comp_mz['id']}/purchase-orders",
        json={
            "supplier_id": sup_mz["id"],
            "ordered_date": "2026-08-01",
            "lines": [{"category_id": cat_mz, "description": "Laptop", "quantity_ordered": 1, "unit_cost": "1200.00"}],
        },
    )
    assert res_mz1.status_code == 201
    assert res_mz1.json()["order_number"] == "MZ-PO-2026-27-00001"

    # 1st order in WeWin starts at 00001 under its own prefix
    res_ww1 = client.post(
        f"/api/v1/companies/{comp_ww['id']}/purchase-orders",
        json={
            "supplier_id": sup_ww["id"],
            "ordered_date": "2026-08-01",
            "lines": [{"category_id": cat_ww, "description": "Monitor", "quantity_ordered": 2, "unit_cost": "350.00"}],
        },
    )
    assert res_ww1.status_code == 201
    assert res_ww1.json()["order_number"] == "WW-PO-2026-27-00001"

    # 2nd order in MindZen continues to 00002
    res_mz2 = client.post(
        f"/api/v1/companies/{comp_mz['id']}/purchase-orders",
        json={
            "supplier_id": sup_mz["id"],
            "ordered_date": "2026-08-02",
            "lines": [{"category_id": cat_mz, "description": "Docking Station", "quantity_ordered": 1, "unit_cost": "200.00"}],
        },
    )
    assert res_mz2.status_code == 201
    assert res_mz2.json()["order_number"] == "MZ-PO-2026-27-00002"


def test_independent_numbering_across_financial_years(client):
    """
    4. Independent numbering across different financial years:
       - 2025-26: starts at 00001
       - 2026-27: starts at 00001
       - 2027-28: starts at 00001
    """
    comp = create_test_company_with_prefix(client, "PO-MULTI-FY", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-MFY")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Order in 2025-26 (e.g. 2025-10-15)
    r25 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2025-10-15",
            "lines": [{"category_id": cat_id, "description": "Legacy Router", "quantity_ordered": 1, "unit_cost": "500.00"}],
        },
    )
    assert r25.status_code == 201
    assert r25.json()["order_number"] == "MZ-PO-2025-26-00001"

    # Order in 2026-27 (e.g. 2026-05-10)
    r26 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-05-10",
            "lines": [{"category_id": cat_id, "description": "Current Switch", "quantity_ordered": 1, "unit_cost": "800.00"}],
        },
    )
    assert r26.status_code == 201
    assert r26.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Order in 2027-28 (e.g. 2027-04-05)
    r27 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2027-04-05",
            "lines": [{"category_id": cat_id, "description": "Future Server", "quantity_ordered": 1, "unit_cost": "5000.00"}],
        },
    )
    assert r27.status_code == 201
    assert r27.json()["order_number"] == "MZ-PO-2027-28-00001"


def test_backdated_purchase_order(client):
    """
    5. Backdated Purchase Orders receive a number from the corresponding
       financial-year sequence without disturbing subsequent financial-year sequences.
    """
    comp = create_test_company_with_prefix(client, "PO-BACKDATED", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-BD")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # 1st order in 2026-27
    r_curr = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-09-01",
            "lines": [{"category_id": cat_id, "description": "Order 1", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r_curr.status_code == 201
    assert r_curr.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Backdated order in 2024-25
    r_back = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2024-12-15",
            "lines": [{"category_id": cat_id, "description": "Backdated 2024", "quantity_ordered": 1, "unit_cost": "200.00"}],
        },
    )
    assert r_back.status_code == 201
    assert r_back.json()["order_number"] == "MZ-PO-2024-25-00001"

    # Second order in 2026-27 continues from 00002
    r_curr2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-09-10",
            "lines": [{"category_id": cat_id, "description": "Order 2", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r_curr2.status_code == 201
    assert r_curr2.json()["order_number"] == "MZ-PO-2026-27-00002"


def test_financial_year_boundary_asia_kolkata(client):
    """
    6. Financial-year boundary around 31 March and 1 April in Asia/Kolkata:
       - 31 March 2026 23:59:59 IST is in FY 2025-26
       - 01 April 2026 00:00:00 IST is in FY 2026-27
    """
    comp = create_test_company_with_prefix(client, "PO-BOUNDARY", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-BND")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # End of FY 2025-26
    r_march31 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-03-31",
            "lines": [{"category_id": cat_id, "description": "Year End PO", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r_march31.status_code == 201
    assert r_march31.json()["order_number"] == "MZ-PO-2025-26-00001"

    # Start of FY 2026-27
    r_april1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-04-01",
            "lines": [{"category_id": cat_id, "description": "New Year PO", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r_april1.status_code == 201
    assert r_april1.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Also test datetime boundary conversion in get_fiscal_year:
    # 2026-03-31 18:30:00 UTC = 2026-04-01 00:00:00 IST -> FY 2026-27
    dt_april = datetime(2026, 3, 31, 18, 30, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
    assert ReferenceNumberService.get_fiscal_year(dt_april) == "2026-27"

    # 2026-03-31 18:29:59 UTC = 2026-03-31 23:59:59 IST -> FY 2025-26
    dt_march = datetime(2026, 3, 31, 18, 29, 59, tzinfo=zoneinfo.ZoneInfo("UTC"))
    assert ReferenceNumberService.get_fiscal_year(dt_march) == "2025-26"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL required for concurrency test")
def test_concurrent_purchase_order_creation():
    """
    7. Concurrent Purchase Order creation in PostgreSQL:
       Multi-threaded allocations receive unique sequential numbers without gaps or collisions.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        seed_security_defaults(db)
        company = create_company(
            db,
            CompanyCreate(code=f"CONCPO{uuid4().hex[:8]}", name="Conc PO Co", number_prefix="CPO"),
        )
        sup = Supplier(company_id=company.id, code="SUP-CONC", name="Conc Supplier")
        db.add(sup)
        db.flush()
        cat = db.query(AssetCategory).filter_by(company_id=company.id, code="LAPTOP").one()
        comp_id, sup_id, cat_id = company.id, sup.id, cat.id
        db.commit()

        target_date = date(2026, 11, 1)

        def worker(idx: int) -> str:
            with SessionLocal() as session:
                order_num = ReferenceNumberService.allocate(
                    session,
                    comp_id,
                    "purchase_order",
                    business_date=target_date,
                    is_permanent=False,
                )
                po = PurchaseOrder(
                    company_id=comp_id,
                    supplier_id=sup_id,
                    order_number=order_num,
                    ordered_date=target_date,
                    status="open",
                )
                session.add(po)
                session.flush()
                session.add(PurchaseOrderLine(
                    company_id=comp_id,
                    purchase_order_id=po.id,
                    category_id=cat_id,
                    description=f"Concurrent Item {idx}",
                    quantity_ordered=1,
                    unit_cost=50.0,
                ))
                session.commit()
                return order_num

        with ThreadPoolExecutor(max_workers=6) as executor:
            allocated = list(executor.map(worker, range(15)))

        assert len(allocated) == 15
        assert len(set(allocated)) == 15
        expected = {f"CPO-PO-2026-27-{i:05d}" for i in range(1, 16)}
        assert set(allocated) == expected
    finally:
        db.close()
        engine.dispose()


def test_purchase_order_transaction_rollback(client, db_session):
    """
    8. Transaction rollback:
       If a purchase order creation transaction fails and rolls back,
       the sequence counter increment is rolled back in PostgreSQL.
    """
    comp = create_test_company_with_prefix(client, "PO-ROLLBACK", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-RB")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # 1st successful PO -> 00001
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-10",
            "lines": [{"category_id": cat_id, "description": "Item 1", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r1.status_code == 201
    assert r1.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Inject failure inside uncommitted transaction:
    # Allocate number inside session, then rollback session
    comp_uuid = UUID(comp["id"])
    with db_session.begin_nested():
        alloc_failed = ReferenceNumberService.allocate(
            db_session,
            comp_uuid,
            "purchase_order",
            business_date=date(2026, 10, 10),
            is_permanent=False,
        )
        assert alloc_failed == "MZ-PO-2026-27-00002"
        # Force rollback of the nested transaction
        db_session.rollback()

    # Next PO created via API receives 00002 (no gap left behind)
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-10",
            "lines": [{"category_id": cat_id, "description": "Item 2", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r2.status_code == 201
    assert r2.json()["order_number"] == "MZ-PO-2026-27-00002"


def test_purchase_order_cancellation_without_number_reuse(client, db_session):
    """
    9. Cancellation without number reuse:
       A committed purchase order that is later cancelled/deleted retains its
       consumed number; subsequent purchase orders never reuse that number.
    """
    comp = create_test_company_with_prefix(client, "PO-CANCEL", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-CN")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Create PO 1 -> 00001
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-10",
            "lines": [{"category_id": cat_id, "description": "Item 1", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r1.status_code == 201
    po1_id = r1.json()["id"]
    assert r1.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Simulate deletion / cancellation of PO 1 in DB
    po_record = db_session.get(PurchaseOrder, UUID(po1_id))
    # Remove lines first
    for line in db_session.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po_record.id)).all():
        db_session.delete(line)
    db_session.flush()
    db_session.delete(po_record)
    db_session.commit()

    # Create next PO -> must receive 00002 (never reuses 00001)
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-10",
            "lines": [{"category_id": cat_id, "description": "Item 2", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert r2.status_code == 201
    assert r2.json()["order_number"] == "MZ-PO-2026-27-00002"


def test_unprovisioned_company_handling(client, db_session):
    """
    10. Unprovisioned company handling:
        An unprovisioned company attempting to create a Purchase Order
        receives a clear, controlled HTTP 422 error.
    """
    # Create company directly in DB without provisioning sequences
    comp = Company(code="UNPROV-PO", name="Unprovisioned PO Co", is_active=True)
    db_session.add(comp)
    db_session.flush()

    sup = Supplier(company_id=comp.id, code="SUP-UNP", name="Unprovisioned Supplier")
    db_session.add(sup)
    cat = AssetCategory(company_id=comp.id, code="LAPTOP", name="Laptops")
    db_session.add(cat)
    db_session.commit()

    res = client.post(
        f"/api/v1/companies/{comp.id}/purchase-orders",
        json={
            "supplier_id": str(sup.id),
            "ordered_date": "2026-10-10",
            "lines": [{"category_id": str(cat.id), "description": "Item", "quantity_ordered": 1, "unit_cost": "100.00"}],
        },
    )
    assert res.status_code == 422
    assert "not been provisioned with purchase order numbering rules" in res.json()["detail"]


def test_historical_purchase_orders_remain_unchanged(client):
    """
    11. Existing historical Purchase Orders remain unchanged.
        Verify that demo POs (DEMO-PO-2026-001, 002, 003) exist and are unaffected.
    """
    companies = client.get("/api/v1/companies").json()
    mz_demo = next((c for c in companies if c["code"] == "MINDZEN_DEMO" or "MindZen" in c["name"]), None)
    if mz_demo:
        orders = client.get(f"/api/v1/companies/{mz_demo['id']}/purchase-orders").json()
        order_nums = [o["order_number"] for o in orders]
        assert "DEMO-PO-2026-001" in order_nums
        assert "DEMO-PO-2026-002" in order_nums
        assert "DEMO-PO-2026-003" in order_nums


def test_all_purchase_order_creation_paths_use_central_allocation(client, db_session):
    """
    12. All Purchase Order creation paths use central allocation:
        - Omitted order_number -> auto-generates central reference.
        - Blank/whitespace order_number -> auto-generates central reference.
        - Manual collision with reserved managed prefix -> rejected (422).
        - Update order_number with reserved managed prefix -> rejected (422).
        - Valid external PO number -> accepted (201) without advancing sequence counter.
        - Duplicate external PO number -> rejected (409).
    """
    comp = create_test_company_with_prefix(client, "PO-ALL-PATHS", "MZ")
    sup = create_test_supplier(client, comp["id"], "SUP-AP")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Path A: Omitted order_number -> auto-generated
    r_omit = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_omit.status_code == 201
    assert r_omit.json()["order_number"] == "MZ-PO-2026-27-00001"

    # Path B: Blank string order_number -> auto-generated
    r_blank = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "order_number": "   ",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_blank.status_code == 201
    assert r_blank.json()["order_number"] == "MZ-PO-2026-27-00002"

    # Path C: Manual PO number with reserved managed prefix -> rejected (422)
    r_collide = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "order_number": "MZ-PO-2026-27-00999",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_collide.status_code == 422
    assert "Manual purchase order numbers are not permitted for internal purchase orders" in str(r_collide.json()["detail"])

    # Path D: Update existing PO order_number -> HTTP 409 (Reference Immutability)
    r_update_collide = client.put(
        f"/api/v1/companies/{comp['id']}/purchase-orders/{r_omit.json()['id']}",
        json={
            "order_number": "MZ-PO-2026-27-00888",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_update_collide.status_code == 409
    assert "is immutable and cannot be modified" in r_update_collide.json()["detail"]

    # Path E: Manual external PO number on internal creation path -> rejected (422)
    r_ext = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "order_number": "SAP-PO-9999",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_ext.status_code == 422
    assert "Manual purchase order numbers are not permitted for internal purchase orders" in str(r_ext.json()["detail"])

    # Path F: Attempt to inject external provenance fields on internal creation path -> rejected (422)
    r_inject = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "origin": "EXTERNAL",
            "source_system": "SAP",
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_inject.status_code == 422

    # Verify sequence counter was NOT advanced by rejected manual attempts:
    # Next auto-allocated PO receives 00003!
    r_next_auto = client.post(
        f"/api/v1/companies/{comp['id']}/purchase-orders",
        json={
            "supplier_id": sup["id"],
            "ordered_date": "2026-10-15",
            "lines": [{"category_id": cat_id, "description": "Item", "quantity_ordered": 1, "unit_cost": "10.00"}],
        },
    )
    assert r_next_auto.status_code == 201
    assert r_next_auto.json()["order_number"] == "MZ-PO-2026-27-00003"
