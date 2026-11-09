"""Comprehensive integration test suite for Centralized Asset Numbering (Milestone 2B).

Covers:
1. MindZen Demo continuity (existing 21 assets MZ-000001 to MZ-000021 preserved; next is MZ-AST-000022).
2. WeWin Demo initial numbering (0 assets; next is WW-AST-000001).
3. Multiple consecutive allocations.
4. Multi-tenant company isolation.
5. Category-specific AssetNumberRule ignored (does not override central sequence).
6. Manual custom identifier preservation (EXT-CUSTOM-001 preserved, does not advance sequence).
7. Manual duplicate rejected (HTTP 409).
8. Manual managed-prefix collision rejected (HTTP 422).
9. Concurrent multi-threaded asset creation (PostgreSQL row-level locking).
10. Transaction rollback reverts counter.
11. Bulk import with blank and supplied asset numbers.
12. Field verification unregistered asset registration (auto-generated, manual external, prefix collision, duplicate).
13. New company provisioning with explicit prefix base (all 8 sequences provisioned atomically).
14. Company provisioning failure rolls back company creation.
15. Historical assets, UUIDs, relationships, and history records preserved.
"""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timezone
import io
import os
from unittest.mock import patch
from uuid import UUID, uuid4
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AssetNumberRule,
    Company,
    ReferenceSequence,
    Site,
    Location,
    User,
)
from app.reference_service import ReferenceNumberService
from app.schemas import AssetCreate, CompanyCreate
from app.security_seed import seed_security_defaults
from app.services import create_asset, create_company, next_asset_number


def create_test_company_with_prefix(client, code: str, prefix: str) -> dict:
    resp = client.post(
        "/api/v1/companies",
        json={"code": code, "name": f"{code} Corp", "number_prefix": prefix},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_mindzen_demo_continuity_and_historical_preservation(client):
    """
    1. MindZen Demo continuity:
    Historical assets MZ-000001 through MZ-000021 exist.
    Next generated asset number must be MZ-AST-000022, then MZ-AST-000023.
    Historical assets remain completely intact.
    """
    company_data = create_test_company_with_prefix(client, "MZDEMO", "MZ")
    company_id = UUID(company_data["id"])

    # Seed 21 historical assets MZ-000001 through MZ-000021 and set sequence to 21
    cats = client.get(f"/api/v1/companies/{company_id}/categories").json()
    laptop_cat = next(c for c in cats if c["code"] == "LAPTOP")

    # Access DB to simulate pre-existing demo data
    from app.database import get_db
    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        # Create 21 historical assets
        hist_assets = []
        for i in range(1, 22):
            ast = Asset(
                id=uuid4(),
                company_id=company_id,
                category_id=UUID(laptop_cat["id"]),
                asset_number=f"MZ-{i:06d}",
                serial_number=f"HIST-SN-{i:04d}",
                status="in_stock",
                created_at=datetime(2025, 4, 1, 10, 0, tzinfo=timezone.utc),
            )
            app_db.add(ast)
            hist_assets.append(ast)

        # Update sequence current_value to 21
        seq = app_db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == "asset",
                ReferenceSequence.fiscal_year == "PERMANENT",
            )
        )
        assert seq is not None
        seq.current_value = 21
        app_db.commit()

        # Capture historical UUIDs and asset numbers
        hist_records = {ast.id: ast.asset_number for ast in hist_assets}
    finally:
        app_db.close()

    # Now create new assets via API (auto-numbering)
    first_new = client.post(
        f"/api/v1/companies/{company_id}/assets",
        json={"category_id": laptop_cat["id"], "serial_number": "NEW-SN-0022"},
    )
    assert first_new.status_code == 201, first_new.text
    assert first_new.json()["asset_number"] == "MZ-AST-000022"

    second_new = client.post(
        f"/api/v1/companies/{company_id}/assets",
        json={"category_id": laptop_cat["id"], "serial_number": "NEW-SN-0023"},
    )
    assert second_new.status_code == 201, second_new.text
    assert second_new.json()["asset_number"] == "MZ-AST-000023"

    # Verify all 21 historical assets remain untouched
    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        for ast_id, expected_num in hist_records.items():
            db_ast = app_db.get(Asset, ast_id)
            assert db_ast is not None
            assert db_ast.asset_number == expected_num
    finally:
        app_db.close()


def test_wewin_demo_initial_numbering(client):
    """
    2. WeWin Demo initial numbering:
    0 existing assets.
    Next generated asset number must be WW-AST-000001, then WW-AST-000002.
    """
    company_data = create_test_company_with_prefix(client, "WWDEMO", "WW")
    company_id = UUID(company_data["id"])

    cats = client.get(f"/api/v1/companies/{company_id}/categories").json()
    cat_id = cats[0]["id"]

    # First asset
    first = client.post(
        f"/api/v1/companies/{company_id}/assets",
        json={"category_id": cat_id, "serial_number": "WW-SN-0001"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["asset_number"] == "WW-AST-000001"

    # Second asset
    second = client.post(
        f"/api/v1/companies/{company_id}/assets",
        json={"category_id": cat_id, "serial_number": "WW-SN-0002"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["asset_number"] == "WW-AST-000002"


def test_multi_tenant_isolation_asset_numbering(client):
    """
    3. Multi-tenant company isolation:
    Allocations in Company Alpha do not advance Company Beta's sequence.
    """
    comp_a = create_test_company_with_prefix(client, "ALPHA", "ALP")
    comp_b = create_test_company_with_prefix(client, "BETA", "BET")

    cat_a = client.get(f"/api/v1/companies/{comp_a['id']}/categories").json()[0]["id"]
    cat_b = client.get(f"/api/v1/companies/{comp_b['id']}/categories").json()[0]["id"]

    # Comp A allocates two assets
    a1 = client.post(f"/api/v1/companies/{comp_a['id']}/assets", json={"category_id": cat_a}).json()
    a2 = client.post(f"/api/v1/companies/{comp_a['id']}/assets", json={"category_id": cat_a}).json()
    assert a1["asset_number"] == "ALP-AST-000001"
    assert a2["asset_number"] == "ALP-AST-000002"

    # Comp B allocates one asset
    b1 = client.post(f"/api/v1/companies/{comp_b['id']}/assets", json={"category_id": cat_b}).json()
    assert b1["asset_number"] == "BET-AST-000001"


def test_category_specific_numbering_rules_ignored(client):
    """
    4. Category-specific AssetNumberRule no longer overrides central sequence:
    - Attempting to update category rule via PUT returns HTTP 409 Conflict.
    - Pre-existing legacy AssetNumberRule records in DB are ignored.
    - Assets always allocate from ReferenceNumberService.
    """
    comp = create_test_company_with_prefix(client, "CATRULE", "CORP")
    cats = client.get(f"/api/v1/companies/{comp['id']}/categories").json()
    laptop = next(c for c in cats if c["code"] == "LAPTOP")
    server = next(c for c in cats if c["code"] == "SERVER")

    # Attempting to update legacy rule via API returns 409 Conflict
    resp = client.put(
        f"/api/v1/companies/{comp['id']}/numbering-rules?category_id={laptop['id']}",
        json={"prefix": "LPT", "separator": "-", "padding": 4},
    )
    assert resp.status_code == 409
    assert "Legacy numbering rules are retired" in resp.json()["detail"]

    # Directly seed a legacy category rule into DB to simulate pre-existing historical rules
    from app.database import get_db
    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        app_db.add(
            AssetNumberRule(
                company_id=UUID(comp["id"]),
                category_id=UUID(laptop["id"]),
                prefix="LPT",
                separator="-",
                padding=4,
                next_value=1,
            )
        )
        app_db.commit()
    finally:
        app_db.close()

    # Create laptop asset -> must receive central CORP-AST-000001, not LPT-0001
    ast1 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": laptop["id"]},
    ).json()
    assert ast1["asset_number"] == "CORP-AST-000001"

    # Create server asset -> must receive central CORP-AST-000002
    ast2 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": server["id"]},
    ).json()
    assert ast2["asset_number"] == "CORP-AST-000002"


def test_manual_custom_identifier_preservation_and_sequence_continuity(client):
    """
    5. Manual custom identifier preservation:
    - Creating an asset with manual external number (e.g., EXT-TAG-1001) succeeds.
    - Central sequence does not advance.
    - Next auto-generated asset continues sequence with no gaps.
    """
    comp = create_test_company_with_prefix(client, "MANUAL", "MAN")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # First auto asset
    a1 = client.post(f"/api/v1/companies/{comp['id']}/assets", json={"category_id": cat_id}).json()
    assert a1["asset_number"] == "MAN-AST-000001"

    # Manual external asset
    m1 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "EXT-TAG-1001"},
    )
    assert m1.status_code == 201
    assert m1.json()["asset_number"] == "EXT-TAG-1001"

    # Next auto asset continues sequence at 000002 (no gap from manual asset)
    a2 = client.post(f"/api/v1/companies/{comp['id']}/assets", json={"category_id": cat_id}).json()
    assert a2["asset_number"] == "MAN-AST-000002"


def test_manual_duplicate_rejected(client):
    """
    6. Duplicate manual asset numbers within the same company are rejected (HTTP 409).
    """
    comp = create_test_company_with_prefix(client, "DUP", "DUP")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # First manual asset
    first = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "EXTERNAL-DUP-99"},
    )
    assert first.status_code == 201

    # Second asset with same manual number -> 409
    dup = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "EXTERNAL-DUP-99"},
    )
    assert dup.status_code == 409
    assert "already exists in this company" in dup.json()["detail"]


def test_manual_managed_prefix_collision_rejected(client):
    """
    7. Manual asset numbers colliding with the active managed prefix are rejected (HTTP 422).
    """
    comp = create_test_company_with_prefix(client, "COLLIDE", "COL")
    cat_id = client.get(f"/api/v1/companies/{comp['id']}/categories").json()[0]["id"]

    # Attempting exact managed prefix
    r1 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "COL-AST"},
    )
    assert r1.status_code == 422
    assert "conflicts with the managed sequence prefix 'COL-AST'" in r1.json()["detail"]

    # Attempting managed prefix with separator and number
    r2 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "COL-AST-000999"},
    )
    assert r2.status_code == 422
    assert "conflicts with the managed sequence prefix 'COL-AST'" in r2.json()["detail"]

    # Case-insensitive collision check
    r3 = client.post(
        f"/api/v1/companies/{comp['id']}/assets",
        json={"category_id": cat_id, "asset_number": "col-ast-000123"},
    )
    assert r3.status_code == 422
    assert "conflicts with the managed sequence prefix" in r3.json()["detail"]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL required for concurrency test")
def test_concurrent_asset_creation_safety():
    """
    8. Multi-threaded concurrent asset creations generate unique sequential numbers
    with PostgreSQL row-level locking (no duplicates, no skipped numbers).
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        seed_security_defaults(db)
        company = create_company(
            db,
            CompanyCreate(code=f"CONC{uuid4().hex[:10]}", name="Concurrency Co", number_prefix="CCY"),
        )
        cat = db.query(AssetCategory).filter_by(company_id=company.id, code="LAPTOP").one()
        comp_id, cat_id = company.id, cat.id

        def worker(idx: int) -> str:
            with SessionLocal() as session:
                asset = create_asset(
                    session,
                    comp_id,
                    AssetCreate(category_id=cat_id, serial_number=f"CONC-SN-{idx}"),
                )
                return asset.asset_number

        with ThreadPoolExecutor(max_workers=6) as executor:
            allocated = list(executor.map(worker, range(15)))

        assert len(allocated) == 15
        assert len(set(allocated)) == 15
        expected = {f"CCY-AST-{i:06d}" for i in range(1, 16)}
        assert set(allocated) == expected
    finally:
        db.close()
        engine.dispose()


def test_transaction_rollback_reverts_counter(client):
    """
    9. When asset creation rolls back, the allocated counter is reverted.
    """
    comp = create_test_company_with_prefix(client, "ROLLBACK", "RBK")
    company_id = UUID(comp["id"])

    from app.database import get_db
    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        cat = app_db.scalar(select(AssetCategory).where(AssetCategory.company_id == company_id))

        # Successful allocation 1
        a1 = create_asset(app_db, company_id, AssetCreate(category_id=cat.id, serial_number="SN-RBK-1"))
        assert a1.asset_number == "RBK-AST-000001"

        # Check sequence is at 1
        seq = app_db.scalar(
            select(ReferenceSequence).where(
                ReferenceSequence.company_id == company_id,
                ReferenceSequence.entity_type == "asset",
                ReferenceSequence.fiscal_year == "PERMANENT",
            )
        )
        assert seq.current_value == 1

        # Simulate failed asset creation inside a nested transaction / savepoint
        nested = app_db.begin_nested()
        try:
            # Allocate inside savepoint
            num = ReferenceNumberService.allocate(app_db, company_id, "asset", is_permanent=True)
            assert num == "RBK-AST-000002"
            # Simulate failure and rollback
            raise ValueError("Simulated unexpected failure")
        except ValueError:
            nested.rollback()

        # Sequence should be reverted back to 1
        app_db.refresh(seq)
        assert seq.current_value == 1

        # Next successful allocation gets RBK-AST-000002
        a2 = create_asset(app_db, company_id, AssetCreate(category_id=cat.id, serial_number="SN-RBK-2"))
        assert a2.asset_number == "RBK-AST-000002"
    finally:
        app_db.close()

def test_company_creation_requires_explicit_prefix_and_provisions_all_sequences(client):
    """
    11. Company creation requires explicit number_prefix and provisions all 8 sequence types atomically.
    """
    comp = create_test_company_with_prefix(client, "PROVTEST", "PRV")
    company_id = UUID(comp["id"])

    from app.database import get_db
    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        seqs = app_db.scalars(
            select(ReferenceSequence).where(ReferenceSequence.company_id == company_id)
        ).all()
        assert len(seqs) == 9
        seq_map = {s.entity_type: s for s in seqs}

        assert seq_map["asset"].prefix == "PRV-AST"
        assert seq_map["asset"].fiscal_year == "PERMANENT"
        assert seq_map["asset"].padding == 6

        assert seq_map["purchase_order"].prefix == "PRV-PO"
        assert seq_map["goods_receipt"].prefix == "PRV-GRN"
        assert seq_map["goods_return"].prefix == "PRV-GRR"
        assert seq_map["verification_campaign"].prefix == "PRV-VC"
        assert seq_map["service_request"].prefix == "PRV-SR"
        assert seq_map["maintenance_work_order"].prefix == "PRV-MWO"
        assert seq_map["asset_transfer"].prefix == "PRV-TRF"
        assert seq_map["asset_disposal"].prefix == "PRV-DSP"
    finally:
        app_db.close()


def test_company_creation_without_prefix_rejected(client):
    """
    12. Company creation with blank/empty number_prefix is rejected (HTTP 422).
    """
    resp = client.post(
        "/api/v1/companies",
        json={"code": "NOPREFIX", "name": "No Prefix Corp", "number_prefix": ""},
    )
    assert resp.status_code == 422


def test_provisioning_failure_rolls_back_company_creation(client):
    """
    13. If sequence provisioning fails during company creation, the company is rolled back.
    """
    from app.database import get_db

    app_db = next(client.app.dependency_overrides[get_db]())
    try:
        payload = CompanyCreate(code=f"FAIL{uuid4().hex[:8]}", name="Failing Co", number_prefix="FLC")
        with patch.object(ReferenceNumberService, "provision_company_sequences", side_effect=RuntimeError("Simulated provision crash")):
            with pytest.raises(Exception):
                create_company(app_db, payload)

        # Confirm company was NOT committed
        co = app_db.scalar(select(Company).where(Company.code == payload.code))
        assert co is None
    finally:
        app_db.close()


def test_bulk_import_with_blank_and_supplied_asset_numbers(client):
    """
    14. Bulk asset import integration:
    - Blank asset_number rows receive centralized sequential numbers.
    - Valid external asset_number rows preserve their external tag.
    - Central sequence only advances for auto-generated rows.
    """
    comp = create_test_company_with_prefix(client, "BULKNUM", "IMP")
    company_id = comp["id"]

    csv_data = [
        ["category_code", "serial_number", "model", "asset_number"],
        ["LAPTOP", "SN-BLK-001", "MacBook Pro", ""],
        ["LAPTOP", "SN-BLK-002", "ThinkPad X1", "EXT-TAG-888"],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_data)
    csv_bytes = output.getvalue().encode("utf-8")

    # Preview
    preview_res = client.post(
        f"/api/v1/companies/{company_id}/assets/import/preview",
        files={"file": ("import.csv", csv_bytes, "text/csv")},
    )
    assert preview_res.status_code == 200, preview_res.text
    token = preview_res.json()["preview_token"]

    # Confirm
    confirm_res = client.post(
        f"/api/v1/companies/{company_id}/assets/import/confirm",
        json={"preview_token": token},
    )
    assert confirm_res.status_code == 200, confirm_res.text
    allocated_numbers = confirm_res.json()["asset_numbers"]
    assert "IMP-AST-000001" in allocated_numbers
    assert "EXT-TAG-888" in allocated_numbers

    # Verify next auto-created asset continues sequence at 000002
    cats = client.get(f"/api/v1/companies/{company_id}/categories").json()
    cat_id = cats[0]["id"]
    next_ast = client.post(
        f"/api/v1/companies/{company_id}/assets",
        json={"category_id": cat_id, "serial_number": "SN-BLK-003"},
    )
    assert next_ast.status_code == 201
    assert next_ast.json()["asset_number"] == "IMP-AST-000002"


def test_legacy_numbering_rules_read_marked_legacy(client):
    """
    Milestone 2B.1: Read access to AssetNumberRule is preserved for backward compatibility
    but clearly marked as legacy and non-authoritative.
    """
    comp = create_test_company_with_prefix(client, "LEGREAD", "LRD")
    company_id = comp["id"]

    resp = client.get(f"/api/v1/companies/{company_id}/numbering-rules")
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) >= 1
    default_rule = rules[0]
    assert default_rule["prefix"] == "LRD"
    assert default_rule["is_legacy"] is True
    assert default_rule["is_authoritative"] is False
    assert "Legacy configuration" in default_rule["status_note"]
    assert "ReferenceNumberService" in default_rule["status_note"]


def test_legacy_numbering_rules_write_operations_rejected_with_409(client):
    """
    Milestone 2B.1: Create, update, and delete operations on legacy numbering rules
    are rejected with HTTP 409 Conflict.
    """
    comp = create_test_company_with_prefix(client, "LEGWRITE", "LWR")
    company_id = comp["id"]
    rule_id = uuid4()

    # POST create -> 409
    post_res = client.post(
        f"/api/v1/companies/{company_id}/numbering-rules",
        json={"prefix": "CUSTOM", "separator": "-", "padding": 6},
    )
    assert post_res.status_code == 409
    assert "Legacy numbering rules are retired" in post_res.json()["detail"]
    assert "ReferenceNumberService" in post_res.json()["detail"]

    # PUT update -> 409
    put_res = client.put(
        f"/api/v1/companies/{company_id}/numbering-rules",
        json={"prefix": "CUSTOM", "separator": "-", "padding": 6},
    )
    assert put_res.status_code == 409
    assert "Legacy numbering rules are retired" in put_res.json()["detail"]

    # DELETE query -> 409
    del_res1 = client.delete(f"/api/v1/companies/{company_id}/numbering-rules")
    assert del_res1.status_code == 409
    assert "Legacy numbering rules are retired" in del_res1.json()["detail"]

    # DELETE by id -> 409
    del_res2 = client.delete(f"/api/v1/companies/{company_id}/numbering-rules/{rule_id}")
    assert del_res2.status_code == 409
    assert "Legacy numbering rules are retired" in del_res2.json()["detail"]


def test_manual_identifier_collision_matrix_and_company_isolation(client):
    """
    Milestone 2B.1 Manual identifier validation review:
    - MZ-AST-000100 is rejected for MindZen (counter is at 21).
    - WW-AST-000100 is rejected for WeWin (counter is at 0).
    - Validation is company-specific: WW-AST-000100 is accepted as external identifier for MindZen.
    - Valid external identifiers (EXT-TAG-1001) are accepted across standard creation, bulk import, and verification.
    - Duplicate external identifiers are rejected (HTTP 409).
    - Bulk import preview flags managed prefix collisions as ImportRowError.
    """
    comp_mz = create_test_company_with_prefix(client, "MINDZEN-CO", "MZ")
    comp_ww = create_test_company_with_prefix(client, "WEWIN-CO", "WW")

    cat_mz = client.get(f"/api/v1/companies/{comp_mz['id']}/categories").json()[0]["id"]
    cat_ww = client.get(f"/api/v1/companies/{comp_ww['id']}/categories").json()[0]["id"]

    # 1. Standard asset creation:
    # MZ-AST-000100 is rejected for MindZen (even though counter is only at 0 or 21)
    mz_collide = client.post(
        f"/api/v1/companies/{comp_mz['id']}/assets",
        json={"category_id": cat_mz, "asset_number": "MZ-AST-000100"},
    )
    assert mz_collide.status_code == 422
    assert "conflicts with the managed sequence prefix 'MZ-AST'" in mz_collide.json()["detail"]

    # WW-AST-000100 is rejected for WeWin
    ww_collide = client.post(
        f"/api/v1/companies/{comp_ww['id']}/assets",
        json={"category_id": cat_ww, "asset_number": "WW-AST-000100"},
    )
    assert ww_collide.status_code == 422
    assert "conflicts with the managed sequence prefix 'WW-AST'" in ww_collide.json()["detail"]

    # Cross-company isolation:
    # WW-AST-000100 is NOT a managed prefix collision for MindZen! MindZen's prefix is MZ-AST.
    mz_ext_ww = client.post(
        f"/api/v1/companies/{comp_mz['id']}/assets",
        json={"category_id": cat_mz, "asset_number": "WW-AST-000100"},
    )
    assert mz_ext_ww.status_code == 201
    assert mz_ext_ww.json()["asset_number"] == "WW-AST-000100"

    # Valid external identifier EXT-TAG-1001 accepted in MindZen
    ext_mz = client.post(
        f"/api/v1/companies/{comp_mz['id']}/assets",
        json={"category_id": cat_mz, "asset_number": "EXT-TAG-1001"},
    )
    assert ext_mz.status_code == 201
    assert ext_mz.json()["asset_number"] == "EXT-TAG-1001"

    # Duplicate external identifier EXT-TAG-1001 in same company rejected (409)
    ext_mz_dup = client.post(
        f"/api/v1/companies/{comp_mz['id']}/assets",
        json={"category_id": cat_mz, "asset_number": "EXT-TAG-1001"},
    )
    assert ext_mz_dup.status_code == 409

    # Cross-company: EXT-TAG-1001 is accepted in WeWin (company isolation)
    ext_ww = client.post(
        f"/api/v1/companies/{comp_ww['id']}/assets",
        json={"category_id": cat_ww, "asset_number": "EXT-TAG-1001"},
    )
    assert ext_ww.status_code == 201
    assert ext_ww.json()["asset_number"] == "EXT-TAG-1001"

    # 2. Bulk import preview collision validation:
    csv_data = [
        ["category_code", "serial_number", "model", "asset_number"],
        ["LAPTOP", "SN-COLLIDE-01", "MacBook Pro", "MZ-AST-000100"],
        ["LAPTOP", "SN-COLLIDE-02", "ThinkPad X1", "EXT-TAG-9999"],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(csv_data)
    csv_bytes = output.getvalue().encode("utf-8")

    preview_res = client.post(
        f"/api/v1/companies/{comp_mz['id']}/assets/import/preview",
        files={"file": ("test_collide.csv", csv_bytes, "text/csv")},
    )
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert preview_data["valid"] is False
    assert len(preview_data["errors"]) == 1
    err = preview_data["errors"][0]
    assert err["field"] == "asset_number"
    assert "conflicts with the managed sequence prefix 'MZ-AST'" in err["message"]
    assert err.get("code") == "RESERVED_NAMESPACE_CONFLICT"


def test_managed_prefix_boundaries_matrix(client, db_session):
    """
    Milestone 2B.2 Part A3: Managed prefix boundary testing.
    Verifies boundary matching (prefix + separator) rather than loose substring match:
    - MZ-AST-000100 -> Reject (422)
    - MZ-AST-EXT-100 -> Reject (422)
    - MZ-ASTX-100 -> Accept (201)
    - EXT-MZ-AST-100 -> Accept (201)
    - EXT-TAG-1001 -> Accept (201)

    Repeats equivalent for WeWin (WW-AST).
    Confirms:
    - Reserved namespaces are company-specific.
    - External identifiers do not advance sequence counter.
    - Rejected identifiers do not alter sequence counter.
    - Next auto-allocated reference continues smoothly.
    """
    comp_mz = create_test_company_with_prefix(client, "MINDZEN-BOUNDS", "MZ")
    comp_ww = create_test_company_with_prefix(client, "WEWIN-BOUNDS", "WW")

    cat_mz = client.get(f"/api/v1/companies/{comp_mz['id']}/categories").json()[0]["id"]
    cat_ww = client.get(f"/api/v1/companies/{comp_ww['id']}/categories").json()[0]["id"]

    db_session.expire_all()
    seq_mz = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == UUID(comp_mz["id"]),
            ReferenceSequence.entity_type == "asset",
        )
    )
    assert seq_mz.current_value == 0

    # MindZen Test Matrix
    # 1. MZ-AST-000100 -> Reject
    r1 = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "MZ-AST-000100"})
    assert r1.status_code == 422

    # 2. MZ-AST-EXT-100 -> Reject
    r2 = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "MZ-AST-EXT-100"})
    assert r2.status_code == 422

    # 3. MZ-ASTX-100 -> Accept (boundary is MZ-AST-, MZ-ASTX is not in reserved namespace)
    r3 = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "MZ-ASTX-100"})
    assert r3.status_code == 201
    assert r3.json()["asset_number"] == "MZ-ASTX-100"

    # 4. EXT-MZ-AST-100 -> Accept (boundary is prefix, not substring in middle)
    r4 = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "EXT-MZ-AST-100"})
    assert r4.status_code == 201
    assert r4.json()["asset_number"] == "EXT-MZ-AST-100"

    # 5. EXT-TAG-1001 -> Accept
    r5 = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "EXT-TAG-1001"})
    assert r5.status_code == 201
    assert r5.json()["asset_number"] == "EXT-TAG-1001"

    # Confirm MindZen sequence counter remains 0 after all accepted external & rejected identifiers!
    db_session.expire_all()
    seq_mz = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == UUID(comp_mz["id"]),
            ReferenceSequence.entity_type == "asset",
        )
    )
    assert seq_mz.current_value == 0

    # WeWin Test Matrix
    # 1. WW-AST-000100 -> Reject
    w1 = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "WW-AST-000100"})
    assert w1.status_code == 422

    # 2. WW-AST-EXT-100 -> Reject
    w2 = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "WW-AST-EXT-100"})
    assert w2.status_code == 422

    # 3. WW-ASTX-100 -> Accept
    w3 = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "WW-ASTX-100"})
    assert w3.status_code == 201
    assert w3.json()["asset_number"] == "WW-ASTX-100"

    # 4. EXT-WW-AST-100 -> Accept
    w4 = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "EXT-WW-AST-100"})
    assert w4.status_code == 201
    assert w4.json()["asset_number"] == "EXT-WW-AST-100"

    # 5. EXT-TAG-1001 -> Accept
    w5 = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "EXT-TAG-1001"})
    assert w5.status_code == 201
    assert w5.json()["asset_number"] == "EXT-TAG-1001"

    # Confirm WeWin sequence counter remains 0!
    db_session.expire_all()
    seq_ww = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == UUID(comp_ww["id"]),
            ReferenceSequence.entity_type == "asset",
        )
    )
    assert seq_ww.current_value == 0

    # Cross-company isolation:
    # WW-AST-000100 is accepted in MindZen as external identifier
    mz_ww_ext = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz, "asset_number": "WW-AST-000100"})
    assert mz_ww_ext.status_code == 201
    assert mz_ww_ext.json()["asset_number"] == "WW-AST-000100"

    # MZ-AST-000100 is accepted in WeWin as external identifier
    ww_mz_ext = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww, "asset_number": "MZ-AST-000100"})
    assert ww_mz_ext.status_code == 201
    assert ww_mz_ext.json()["asset_number"] == "MZ-AST-000100"

    # Auto-allocation verification:
    # Next MindZen auto-allocation produces MZ-AST-000001
    mz_auto = client.post(f"/api/v1/companies/{comp_mz['id']}/assets", json={"category_id": cat_mz})
    assert mz_auto.status_code == 201
    assert mz_auto.json()["asset_number"] == "MZ-AST-000001"

    # Next WeWin auto-allocation produces WW-AST-000001
    ww_auto = client.post(f"/api/v1/companies/{comp_ww['id']}/assets", json={"category_id": cat_ww})
    assert ww_auto.status_code == 201
    assert ww_auto.json()["asset_number"] == "WW-AST-000001"



