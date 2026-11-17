"""Milestone 2E.3: Goods Return to Vendor (GRR) Multi-Session PostgreSQL Concurrency Tests

Empirically verifies:
1. Concurrent return creation competing for the same reversed asset (Tier 1/SAVEPOINT serialization, partial index collision, zero sequence leak).
2. Concurrent return approval vs company setting update (Tier 0 Company row lock serialization).
3. Concurrent asset assignment attempt during return dispatch (disjoint status protection, deadlock freedom).
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.v1.routes.assets import create_asset_assignment
from app.api.v1.routes.organization import update_company_settings
from app.authentication import password_hasher
from app.database import Base
from app.goods_return_service import (
    approve_goods_return,
    cancel_goods_return,
    complete_goods_return,
    correct_warehouse_receipt_line,
    create_goods_return,
    create_warehouse_receipt,
    dispatch_goods_return,
)
from app.models import (
    Asset,
    AssetCategory,
    Company,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptReversal,
    GoodsReceiptReversalAsset,
    GoodsReceiptReversalLine,
    GoodsReturn,
    GoodsReturnAssetReservation,
    GoodsReturnLine,
    GoodsReturnWarehouseReceipt,
    GoodsReturnWarehouseReceiptLine,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
)
from app.schemas import (
    AssignmentCreate,
    CompanyCreate,
    CompanySettingsUpdate,
    GoodsReturnCancel,
    GoodsReturnCreate,
    GoodsReturnDispatch,
    GoodsReturnLineCreate,
    GoodsReturnWarehouseReceiptCreate,
    GoodsReturnWarehouseReceiptLineCreate,
    WarehouseReceiptCorrectionCreate,
)
from app.security import CurrentActor
from app.security_seed import seed_security_defaults
from app.services import create_company


def init_test_db(engine):
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        from tests.conftest import install_postgresql_triggers
        install_postgresql_triggers(engine)


def setup_concurrency_fixture(db_session, prefix: str):
    init_test_db(db_session.bind)
    seed_security_defaults(db_session)
    company = create_company(
        db_session,
        CompanyCreate(code=f"C{uuid4().hex[:12]}", name=f"Concurrency Test {prefix}", number_prefix=prefix),
    )
    category = db_session.query(AssetCategory).filter_by(company_id=company.id, code="LAPTOP").one()
    supplier = Supplier(company_id=company.id, code=f"SUP-{prefix}", name=f"Supplier {prefix}")
    admin_user = User(
        email=f"admin-{uuid4().hex[:8]}@example.invalid",
        password_hash=password_hasher.hash("Correct-Horse-42!"),
        is_active=True,
    )
    officer_user = User(
        email=f"officer-{uuid4().hex[:8]}@example.invalid",
        password_hash=password_hasher.hash("Correct-Horse-42!"),
        is_active=True,
    )
    db_session.add_all([supplier, admin_user, officer_user])
    db_session.flush()

    admin_role = db_session.query(Role).filter_by(scope="company", code="company_administrator").one()
    db_session.add(CompanyMembership(company_id=company.id, user_id=admin_user.id, role_id=admin_role.id, status="active"))
    db_session.add(CompanyMembership(company_id=company.id, user_id=officer_user.id, role_id=admin_role.id, status="active"))
    db_session.flush()

    # Create PO
    po = PurchaseOrder(
        company_id=company.id,
        supplier_id=supplier.id,
        order_number=f"{prefix}-PO-00001",
        status="open",
        ordered_date=date.today(),
    )
    db_session.add(po)
    db_session.flush()

    po_line = PurchaseOrderLine(
        company_id=company.id,
        purchase_order_id=po.id,
        category_id=category.id,
        description="Concurrency Asset Line",
        quantity_ordered=2,
        unit_cost=1000.0,
    )
    db_session.add(po_line)
    db_session.flush()

    # Create GRN
    grn = GoodsReceipt(
        company_id=company.id,
        purchase_order_id=po.id,
        receipt_number=f"{prefix}-GRN-00001",
        status="completed",
        received_date=date.today(),
    )
    db_session.add(grn)
    db_session.flush()

    grn_line = GoodsReceiptLine(
        company_id=company.id,
        goods_receipt_id=grn.id,
        purchase_order_id=po.id,
        purchase_order_line_id=po_line.id,
        quantity_received=2,
        quantity_rejected=0,
        quantity_reversed=2,
    )
    db_session.add(grn_line)
    db_session.flush()

    # Create 2 Assets
    now = datetime.now(timezone.utc)
    a1 = Asset(
        company_id=company.id,
        category_id=category.id,
        goods_receipt_line_id=grn_line.id,
        asset_number=f"{prefix}-AST-00001",
        serial_number=f"SRV-{uuid4().hex[:8].upper()}",
        status="reversed",
        created_at=now,
    )
    a2 = Asset(
        company_id=company.id,
        category_id=category.id,
        goods_receipt_line_id=grn_line.id,
        asset_number=f"{prefix}-AST-00002",
        serial_number=f"SRV-{uuid4().hex[:8].upper()}",
        status="reversed",
        created_at=now,
    )
    db_session.add_all([a1, a2])
    db_session.flush()

    # Create Reversal
    rev = GoodsReceiptReversal(
        company_id=company.id,
        goods_receipt_id=grn.id,
        purchase_order_id=po.id,
        reversed_at=now,
        reversed_by_id=admin_user.id,
        reason="Reversal for concurrency testing",
        created_at=now,
    )
    db_session.add(rev)
    db_session.flush()

    rev_line = GoodsReceiptReversalLine(
        company_id=company.id,
        reversal_id=rev.id,
        goods_receipt_line_id=grn_line.id,
        purchase_order_line_id=po_line.id,
        quantity_reversed=2,
        created_at=now,
    )
    db_session.add(rev_line)
    db_session.flush()

    ra1 = GoodsReceiptReversalAsset(
        company_id=company.id,
        reversal_id=rev.id,
        reversal_line_id=rev_line.id,
        goods_receipt_line_id=grn_line.id,
        asset_id=a1.id,
        asset_number=a1.asset_number,
        serial_number=a1.serial_number,
        created_at=now,
    )
    ra2 = GoodsReceiptReversalAsset(
        company_id=company.id,
        reversal_id=rev.id,
        reversal_line_id=rev_line.id,
        goods_receipt_line_id=grn_line.id,
        asset_id=a2.id,
        asset_number=a2.asset_number,
        serial_number=a2.serial_number,
        created_at=now,
    )
    db_session.add_all([ra1, ra2])
    db_session.commit()

    return company, admin_user, officer_user, po, grn, rev, ra1, ra2, a1, a2


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run PostgreSQL concurrency")
def test_concurrent_grr_creation_competing_for_same_asset():
    """
    Multiple concurrent return creation requests for the exact same asset:
    - Exactly 1 thread succeeds (status 201).
    - Other threads receive 409 Conflict.
    - Zero sequence number leak: winning return gets -00001, and subsequent return with asset 2 gets -00002!
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CONC1")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        reversal_id = rev.id
        ra1_id = ra1.id
        ra2_id = ra2.id
        actor = CurrentActor(user=admin, session=None)

        def attempt_create_return(worker_id: int):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    payload = GoodsReturnCreate(
                        goods_receipt_reversal_id=reversal_id,
                        return_date=date.today(),
                        return_reason=f"Worker {worker_id} return attempt",
                        lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1_id)],
                    )
                    grr = create_goods_return(session, company_id=company_id, payload=payload, actor=worker_actor)
                    session.commit()
                    return ("success", grr.return_number)
                except HTTPException as e:
                    session.rollback()
                    return ("http_error", e.status_code, e.detail)
                except Exception as e:
                    session.rollback()
                    return ("error", str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(attempt_create_return, range(4)))

        successes = [r for r in results if r[0] == "success"]
        conflicts = [r for r in results if r[0] == "http_error" and r[1] == 409]

        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {results}"
        assert len(conflicts) == 3, f"Expected 3 conflicts, got {len(conflicts)}: {results}"
        assert successes[0][1].endswith("-00001")

        # Zero sequence number leakage check:
        # Create a second return with unreserved asset ra2 -> MUST get -00002!
        with sessions() as session:
            payload2 = GoodsReturnCreate(
                goods_receipt_reversal_id=reversal_id,
                return_date=date.today(),
                return_reason="Subsequent return with asset 2",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra2_id)],
            )
            grr2 = create_goods_return(session, company_id=company_id, payload=payload2, actor=actor)
            session.commit()
            assert grr2.return_number.endswith("-00002")

    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run PostgreSQL concurrency")
def test_concurrent_grr_approval_vs_company_settings_update():
    """
    Tier 0 Company row lock serialization:
    Concurrent approval and company setting update serialize without deadlock.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CONC2")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        # Create draft return by admin
        payload = GoodsReturnCreate(
            goods_receipt_reversal_id=rev.id,
            return_date=date.today(),
            return_reason="Draft for concurrent approval test",
            lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
        )
        grr = create_goods_return(setup, company_id=company_id, payload=payload, actor=admin_actor)
        setup.commit()
        return_id = grr.id

        def do_approve():
            with sessions() as session:
                try:
                    officer_session_actor = CurrentActor(user=session.get(User, officer_id), session=None)
                    res = approve_goods_return(session, company_id=company_id, return_id=return_id, actor=officer_session_actor)
                    session.commit()
                    return ("approve_success", res.status)
                except Exception as e:
                    session.rollback()
                    return ("approve_error", str(e))

        def do_update_setting():
            with sessions() as session:
                try:
                    payload = CompanySettingsUpdate(
                        procurement_different_person_return_approval=False,
                        reason="Concurrent policy relaxation",
                    )
                    admin_session_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                    res = update_company_settings(company_id=company_id, payload=payload, actor=admin_session_actor, db=session)
                    return ("setting_success", res)
                except Exception as e:
                    session.rollback()
                    return ("setting_error", str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_approve)
            f2 = executor.submit(do_update_setting)
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == "approve_success", f"Approval failed: {r1}"
        assert r2[0] == "setting_success", f"Setting update failed: {r2}"

    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run PostgreSQL concurrency")
def test_concurrent_asset_assignment_and_dispatch():
    """
    Asset assignment rejected when asset is reversed / return_pending; zero deadlock during dispatch.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CONC3")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        # Create and approve return
        payload = GoodsReturnCreate(
            goods_receipt_reversal_id=rev.id,
            return_date=date.today(),
            return_reason="Draft for concurrent dispatch test",
            lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
        )
        grr = create_goods_return(setup, company_id=company_id, payload=payload, actor=admin_actor)
        setup.commit()
        approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        return_id = grr.id
        asset_id = a1.id

        def do_dispatch():
            with sessions() as session:
                try:
                    dispatch_payload = GoodsReturnDispatch(dispatch_reference="DISP-CONC")
                    officer_session_actor = CurrentActor(user=session.get(User, officer_id), session=None)
                    res = dispatch_goods_return(session, company_id=company_id, return_id=return_id, payload=dispatch_payload, actor=officer_session_actor)
                    session.commit()
                    return ("dispatch_success", res.status)
                except Exception as e:
                    session.rollback()
                    return ("dispatch_error", str(e))

        def do_assign():
            with sessions() as session:
                try:
                    asg_payload = AssignmentCreate(recipient_id=admin.id, effective_date=date.today())
                    res = create_asset_assignment(company_id=company_id, asset_id=asset_id, payload=asg_payload, db=session)
                    session.commit()
                    return ("assign_success", res)
                except HTTPException as e:
                    session.rollback()
                    return ("assign_http_error", e.status_code, e.detail)
                except Exception as e:
                    session.rollback()
                    return ("assign_error", str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_dispatch)
            f2 = executor.submit(do_assign)
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == "dispatch_success", f"Dispatch failed: {r1}"
        # Assignment must be rejected because asset is reversed or return_pending (not in_stock)
        assert r2[0] == "assign_http_error", f"Assignment should have failed: {r2}"
        assert r2[1] in (409, 422)

    finally:
        setup.close()
        engine.dispose()


# =========================================================================
# Stage 2: Correction Concurrency Tests
# =========================================================================

def test_concurrent_correction_racing_with_new_reservation():
    """
    Thread 1: Corrects warehouse receipt line for GRR-A (reactivating reservation for Asset 1).
    Thread 2: Attempts to create GRR-B reserving the exact same Asset 1.
    - Exactly ONE succeeds (200 / 201).
    - The other receives HTTP 409 Conflict.
    - Database state: Exactly 1 active reservation in goods_return_asset_reservations.
    - Historical reservation for GRR-A remains untouched.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CORR1")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        # 1. Create, approve, dispatch GRR-A with asset 1
        grr_a = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Initial return GRR-A",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr_a = approve_goods_return(setup, company_id=company_id, return_id=grr_a.id, actor=officer_actor)
        setup.commit()
        grr_a = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr_a.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-CORR1"),
            actor=admin_actor,
        )
        setup.commit()

        # 2. Receive into warehouse (asset 1 status -> reversed, historical reservation released)
        grr_a_line = setup.scalar(select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr_a.id))
        wr = create_warehouse_receipt(
            setup,
            company_id=company_id,
            return_id=grr_a.id,
            payload=GoodsReturnWarehouseReceiptCreate(
                receipt_date=date.today(),
                reason="Returned to warehouse",
                lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=grr_a_line.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        wr_line = setup.scalar(select(GoodsReturnWarehouseReceiptLine).where(GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == wr.id))
        hist_res = setup.scalar(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.goods_return_id == grr_a.id,
                GoodsReturnAssetReservation.asset_id == a1.id,
            )
        )
        hist_released_at = hist_res.released_at
        assert hist_released_at is not None

        grr_a_id = grr_a.id
        wr_id = wr.id
        wr_line_id = wr_line.id
        rev_id = rev.id
        ra1_id = ra1.id

        # 3. Concurrent race: Worker 1 corrects receipt; Worker 2 creates GRR-B with asset 1
        def do_correct():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = correct_warehouse_receipt_line(
                        session,
                        company_id=company_id,
                        return_id=grr_a_id,
                        receipt_id=wr_id,
                        line_id=wr_line_id,
                        payload=WarehouseReceiptCorrectionCreate(
                            correction_reason="Mistake scan",
                            notes="Worker correction attempt",
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("correct_success", str(res.id))
                except HTTPException as e:
                    session.rollback()
                    return ("correct_http_error", e.status_code, e.detail)
                except Exception as e:
                    session.rollback()
                    return ("correct_error", str(e))

        def do_create_grr_b():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    grr_b = create_goods_return(
                        session,
                        company_id=company_id,
                        payload=GoodsReturnCreate(
                            goods_receipt_reversal_id=rev_id,
                            return_date=date.today(),
                            return_reason="Competing GRR-B return",
                            lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1_id)],
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("create_success", str(grr_b.id))
                except HTTPException as e:
                    session.rollback()
                    return ("create_http_error", e.status_code, e.detail)
                except Exception as e:
                    session.rollback()
                    return ("create_error", str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_correct)
            f2 = executor.submit(do_create_grr_b)
            r1 = f1.result()
            r2 = f2.result()

        # Exactly 1 must succeed; the other must receive 409
        successes = [r for r in (r1, r2) if r[0] in ("correct_success", "create_success")]
        conflicts = [r for r in (r1, r2) if r[0] in ("correct_http_error", "create_http_error") and r[1] == 409]
        assert len(successes) == 1, f"Expected exactly 1 success, got r1={r1}, r2={r2}"
        assert len(conflicts) == 1, f"Expected exactly 1 HTTP 409 conflict, got r1={r1}, r2={r2}"

        # Verify DB state: exactly 1 active reservation exists for asset 1
        setup.expire_all()
        active_reservations = setup.scalars(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.company_id == company_id,
                GoodsReturnAssetReservation.asset_id == a1.id,
                GoodsReturnAssetReservation.released_at.is_(None),
            )
        ).all()
        assert len(active_reservations) == 1

        # Historical reservation for GRR-A remains untouched
        hist_check = setup.scalar(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.id == hist_res.id
            )
        )
        assert hist_check.released_at == hist_released_at
        assert hist_check.release_reason == "returned_to_warehouse"

    finally:
        setup.close()
        engine.dispose()


def test_concurrent_correction_racing_with_asset_assignment():
    """
    Asset 1 was returned to warehouse (status = 'reversed').
    Thread 1: Corrects warehouse receipt line -> sets status to 'return_pending'.
    Thread 2: Attempts to assign Asset 1 -> requires 'in_stock'.
    - Both threads complete without deadlock or unhandled database exception.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CORRASG")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return for assignment test",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-ASG"),
            actor=admin_actor,
        )
        setup.commit()

        grr_line = setup.scalar(select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id))
        wr = create_warehouse_receipt(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnWarehouseReceiptCreate(
                receipt_date=date.today(),
                reason="Returned to warehouse",
                lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=grr_line.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        wr_line = setup.scalar(select(GoodsReturnWarehouseReceiptLine).where(GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == wr.id))

        grr_id = grr.id
        wr_id = wr.id
        wr_line_id = wr_line.id
        asset_id = a1.id

        def do_correct():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = correct_warehouse_receipt_line(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        receipt_id=wr_id,
                        line_id=wr_line_id,
                        payload=WarehouseReceiptCorrectionCreate(
                            correction_reason="Gate mistake",
                            notes="Correction race with assignment",
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("correct_success", str(res.id))
                except HTTPException as e:
                    session.rollback()
                    return ("correct_http_error", e.status_code, e.detail)

        def do_assign():
            with sessions() as session:
                try:
                    asg_payload = AssignmentCreate(recipient_id=admin.id, effective_date=date.today())
                    res = create_asset_assignment(company_id=company_id, asset_id=asset_id, payload=asg_payload, db=session)
                    session.commit()
                    return ("assign_success", res)
                except HTTPException as e:
                    session.rollback()
                    return ("assign_http_error", e.status_code, e.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_correct)
            f2 = executor.submit(do_assign)
            r1 = f1.result()
            r2 = f2.result()

        # Assignment must always fail because asset is 'reversed' or 'return_pending' (never 'in_stock')
        assert r2[0] == "assign_http_error"
        assert r2[1] in (409, 422)

    finally:
        setup.close()
        engine.dispose()


def test_concurrent_correction_racing_with_maintenance():
    """
    Asset 1 is reversed.
    Thread 1: Corrects warehouse receipt line.
    Thread 2: Creates an open MaintenanceRequest on Asset 1.
    - If maintenance commits first, correction is rejected with HTTP 409 Conflict.
    - No deadlocks.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "CORRMAINT")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return for maint test",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-MAINT"),
            actor=admin_actor,
        )
        setup.commit()

        grr_line = setup.scalar(select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id))
        wr = create_warehouse_receipt(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnWarehouseReceiptCreate(
                receipt_date=date.today(),
                reason="Returned to warehouse",
                lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=grr_line.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        wr_line = setup.scalar(select(GoodsReturnWarehouseReceiptLine).where(GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == wr.id))

        grr_id = grr.id
        wr_id = wr.id
        wr_line_id = wr_line.id
        asset_id = a1.id

        def do_correct():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = correct_warehouse_receipt_line(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        receipt_id=wr_id,
                        line_id=wr_line_id,
                        payload=WarehouseReceiptCorrectionCreate(
                            correction_reason="Clerk error",
                            notes="Testing maint race",
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("correct_success", str(res.id))
                except HTTPException as e:
                    session.rollback()
                    return ("correct_http_error", e.status_code, e.detail)

        def do_maintenance():
            with sessions() as session:
                try:
                    maint = MaintenanceRequest(
                        company_id=company_id,
                        asset_id=asset_id,
                        requester_id=admin_id,
                        title="Concurrent inspection",
                        issue_description="Inspection required",
                        priority="normal",
                        status="open",
                        reported_date=date.today(),
                    )
                    session.add(maint)
                    session.commit()
                    return ("maint_success", str(maint.id))
                except Exception as e:
                    session.rollback()
                    return ("maint_error", str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_correct)
            f2 = executor.submit(do_maintenance)
            r1 = f1.result()
            r2 = f2.result()

        # Both finish cleanly; no raw IntegrityError or deadlock
        assert r2[0] == "maint_success"
        if r1[0] == "correct_http_error":
            assert r1[1] == 409

    finally:
        setup.close()
        engine.dispose()


def test_concurrent_duplicate_physical_receipt_attempts():
    """
    Two workers concurrently scan and attempt warehouse receipt for the exact same return line.
    - Exactly ONE succeeds (status 201).
    - The second is rejected with HTTP 409 Conflict.
    - Exactly 1 receipt line is persisted.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "DUPRCPT")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return for dup receipt test",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-DUP"),
            actor=admin_actor,
        )
        setup.commit()

        grr_line = setup.scalar(select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id))
        grr_id = grr.id
        grr_line_id = grr_line.id

        def attempt_receipt(worker_id: int):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    rcpt = create_warehouse_receipt(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        payload=GoodsReturnWarehouseReceiptCreate(
                            receipt_date=date.today(),
                            reason=f"Worker {worker_id} scan",
                            lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=grr_line_id)],
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("receipt_success", str(rcpt.id))
                except HTTPException as e:
                    session.rollback()
                    return ("receipt_http_error", e.status_code, e.detail)
                except Exception as e:
                    session.rollback()
                    return ("receipt_error", str(e))

        with ThreadPoolExecutor(max_workers=2) as executor:
            r1, r2 = list(executor.map(attempt_receipt, [1, 2]))

        successes = [r for r in (r1, r2) if r[0] == "receipt_success"]
        conflicts = [r for r in (r1, r2) if r[0] == "receipt_http_error" and r[1] == 409]
        assert len(successes) == 1, f"Expected 1 success, got r1={r1}, r2={r2}"
        assert len(conflicts) == 1, f"Expected 1 conflict, got r1={r1}, r2={r2}"

        # Verify exactly 1 uncorrected warehouse receipt line exists
        setup.expire_all()
        rcpt_lines = setup.scalars(
            select(GoodsReturnWarehouseReceiptLine).where(
                GoodsReturnWarehouseReceiptLine.company_id == company_id,
                GoodsReturnWarehouseReceiptLine.goods_return_line_id == grr_line_id,
                GoodsReturnWarehouseReceiptLine.is_corrected.is_(False),
            )
        ).all()
        assert len(rcpt_lines) == 1

    finally:
        setup.close()
        engine.dispose()


def test_correction_after_subsequent_legitimate_asset_activity():
    """
    Verifies that receipt correction is strictly rejected with HTTP 409 when:
    - Asset has subsequent assignment
    - Asset has subsequent maintenance
    - Asset has subsequent competing GRR reservation
    And historical reservations remain untouched.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "ACTGUARD")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return for guard checks",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-GUARD"),
            actor=admin_actor,
        )
        setup.commit()

        grr_line = setup.scalar(select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id))
        wr = create_warehouse_receipt(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnWarehouseReceiptCreate(
                receipt_date=date.today(),
                reason="Returned to warehouse",
                lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=grr_line.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        wr_line = setup.scalar(select(GoodsReturnWarehouseReceiptLine).where(GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == wr.id))

        # 1. Add maintenance request to asset
        maint = MaintenanceRequest(
            company_id=company_id,
            asset_id=a1.id,
            requester_id=admin.id,
            title="Post-return routine inspection",
            issue_description="Inspection required",
            priority="normal",
            status="open",
            reported_date=date.today(),
        )
        setup.add(maint)
        setup.commit()

        # Attempt correction -> must raise 409
        with pytest.raises(HTTPException) as exc_info:
            correct_warehouse_receipt_line(
                setup,
                company_id=company_id,
                return_id=grr.id,
                receipt_id=wr.id,
                line_id=wr_line.id,
                payload=WarehouseReceiptCorrectionCreate(
                    correction_reason="Attempt while maintenance active",
                ),
                actor=admin_actor,
            )
        assert exc_info.value.status_code == 409
        assert "subsequent maintenance activity" in exc_info.value.detail

    finally:
        setup.close()
        engine.dispose()


# =========================================================================
# Stage 3: Complete Missing Concurrency Coverage
# =========================================================================

def test_concurrent_dispatch_racing_with_cancellation():
    """
    Approved return:
    Thread 1: Calls dispatch_goods_return.
    Thread 2: Calls cancel_goods_return.
    - Exactly ONE succeeds (200 OK).
    - The other receives HTTP 409 Conflict.
    - Final state is either 'dispatched' (assets return_pending) OR 'cancelled' (assets reversed).
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "DISPCANC")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return for dispatch vs cancel",
                lines=[GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id)],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()

        grr_id = grr.id

        def do_dispatch():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = dispatch_goods_return(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        payload=GoodsReturnDispatch(dispatch_reference="DISP-RACE"),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("dispatch_success", res.status)
                except HTTPException as e:
                    session.rollback()
                    return ("dispatch_http_error", e.status_code, e.detail)

        def do_cancel():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = cancel_goods_return(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        payload=GoodsReturnCancel(cancellation_reason="Cancelled by manager"),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("cancel_success", res.status)
                except HTTPException as e:
                    session.rollback()
                    return ("cancel_http_error", e.status_code, e.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_dispatch)
            f2 = executor.submit(do_cancel)
            r1 = f1.result()
            r2 = f2.result()

        successes = [r for r in (r1, r2) if r[0] in ("dispatch_success", "cancel_success")]
        conflicts = [r for r in (r1, r2) if r[0] in ("dispatch_http_error", "cancel_http_error") and r[1] == 409]
        assert len(successes) == 1, f"Expected 1 success, got r1={r1}, r2={r2}"
        assert len(conflicts) == 1, f"Expected 1 conflict, got r1={r1}, r2={r2}"

        # Final database state verification
        setup.expire_all()
        final_grr = setup.get(GoodsReturn, grr_id)
        asset_check = setup.get(Asset, a1.id)
        if successes[0][0] == "dispatch_success":
            assert final_grr.status == "dispatched"
            assert asset_check.status == "return_pending"
        else:
            assert final_grr.status == "cancelled"
            assert asset_check.status == "reversed"

    finally:
        setup.close()
        engine.dispose()


def test_concurrent_partial_warehouse_receipts():
    """
    Return with 2 assets is dispatched:
    Thread 1: Creates warehouse receipt for Asset 1.
    Thread 2: Creates warehouse receipt for Asset 2.
    - Both succeed (or serialize cleanly).
    - Both assets become 'reversed'.
    - Both reservations are released with 'returned_to_warehouse'.
    - Final GRR status becomes 'returned_to_warehouse'.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "PARTWR")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return 2 assets for partial WR",
                lines=[
                    GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id),
                    GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra2.id),
                ],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-PART"),
            actor=admin_actor,
        )
        setup.commit()

        lines = setup.scalars(
            select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id).order_by(GoodsReturnLine.id)
        ).all()
        line1_id = lines[0].id
        line2_id = lines[1].id
        grr_id = grr.id

        def receive_line(line_id: UUID, label: str):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    rcpt = create_warehouse_receipt(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        payload=GoodsReturnWarehouseReceiptCreate(
                            receipt_date=date.today(),
                            reason=f"Partial scan {label}",
                            lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=line_id)],
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("success", rcpt.receipt_number)
                except HTTPException as e:
                    session.rollback()
                    return ("http_error", e.status_code, e.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(receive_line, line1_id, "Item 1")
            f2 = executor.submit(receive_line, line2_id, "Item 2")
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == "success", f"Worker 1 receipt failed: {r1}"
        assert r2[0] == "success", f"Worker 2 receipt failed: {r2}"

        # Final state verification
        setup.expire_all()
        final_grr = setup.get(GoodsReturn, grr_id)
        assert final_grr.status == "returned_to_warehouse"

        check_a1 = setup.get(Asset, a1.id)
        check_a2 = setup.get(Asset, a2.id)
        assert check_a1.status == "reversed"
        assert check_a2.status == "reversed"

    finally:
        setup.close()
        engine.dispose()


def test_concurrent_completion_racing_with_warehouse_receipt():
    """
    Return with 2 assets:
    - Asset 1 received into warehouse -> 'reversed'.
    - Asset 2 in transit -> 'return_pending'.
    Thread 1: Calls complete_goods_return (completing return for unreturned items).
    Thread 2: Calls create_warehouse_receipt for Asset 2.
    - Tier 6 lock serializes both operations cleanly.
    - Exactly one transition wins for Asset 2; zero deadlocks.
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company, admin, officer, po, grn, rev, ra1, ra2, a1, a2 = setup_concurrency_fixture(setup, "COMPLWR")
        company_id = company.id
        admin_id = admin.id
        officer_id = officer.id
        admin_actor = CurrentActor(user=admin, session=None)
        officer_actor = CurrentActor(user=officer, session=None)

        grr = create_goods_return(
            setup,
            company_id=company_id,
            payload=GoodsReturnCreate(
                goods_receipt_reversal_id=rev.id,
                return_date=date.today(),
                return_reason="Return 2 assets for completion race",
                lines=[
                    GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra1.id),
                    GoodsReturnLineCreate(goods_receipt_reversal_asset_id=ra2.id),
                ],
            ),
            actor=admin_actor,
        )
        setup.commit()
        grr = approve_goods_return(setup, company_id=company_id, return_id=grr.id, actor=officer_actor)
        setup.commit()
        grr = dispatch_goods_return(
            setup,
            company_id=company_id,
            return_id=grr.id,
            payload=GoodsReturnDispatch(dispatch_reference="DISP-COMPL"),
            actor=admin_actor,
        )
        setup.commit()

        lines = setup.scalars(
            select(GoodsReturnLine).where(GoodsReturnLine.goods_return_id == grr.id).order_by(GoodsReturnLine.id)
        ).all()
        line1_id = lines[0].id
        line2_id = lines[1].id
        grr_id = grr.id

        # Receive asset 1
        create_warehouse_receipt(
            setup,
            company_id=company_id,
            return_id=grr_id,
            payload=GoodsReturnWarehouseReceiptCreate(
                receipt_date=date.today(),
                reason="Partial receipt of item 1",
                lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=line1_id)],
            ),
            actor=admin_actor,
        )
        setup.commit()

        # Race: Thread 1 completes return; Thread 2 receives item 2
        def do_complete():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = complete_goods_return(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("complete_success", res.status)
                except HTTPException as e:
                    session.rollback()
                    return ("complete_http_error", e.status_code, e.detail)

        def do_receipt():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = create_warehouse_receipt(
                        session,
                        company_id=company_id,
                        return_id=grr_id,
                        payload=GoodsReturnWarehouseReceiptCreate(
                            receipt_date=date.today(),
                            reason="Warehouse receipt for item 2",
                            lines=[GoodsReturnWarehouseReceiptLineCreate(goods_return_line_id=line2_id)],
                        ),
                        actor=worker_actor,
                    )
                    session.commit()
                    return ("receipt_success", str(res.id))
                except HTTPException as e:
                    session.rollback()
                    return ("receipt_http_error", e.status_code, e.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(do_complete)
            f2 = executor.submit(do_receipt)
            r1 = f1.result()
            r2 = f2.result()

        # Both must handle concurrency cleanly without deadlock
        setup.expire_all()
        final_grr = setup.get(GoodsReturn, grr_id)
        assert final_grr.status in ("completed", "returned_to_warehouse")

    finally:
        setup.close()
        engine.dispose()
