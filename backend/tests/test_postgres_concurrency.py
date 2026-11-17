import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.database import Base
from app.models import (
    Asset,
    AssetCategory,
    CompanyMembership,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptReversal,
    GoodsReceiptReversalAsset,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
)
from app.schemas import (
    AssetCreate,
    AssignmentCreate,
    CompanyCreate,
    GoodsReceiptCreate,
    GoodsReceiptLineCreate,
    GoodsReceiptReversalCreate,
    PurchaseOrderCancel,
    ReversalLineItem,
)
from app.authentication import password_hasher
from app.security import CurrentActor
from app.security_seed import seed_security_defaults
from app.api.v1.routes.assets import create_asset_assignment
from app.api.v1.routes.procurement import cancel_purchase_order, receive_goods, reverse_goods_receipt
from app.services import create_asset, create_company


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_asset_number_allocation_is_unique():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company = create_company(
            setup,
            CompanyCreate(code='CON', name='Numbering concurrency test', number_prefix='CON'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        company_id, category_id = company.id, category.id

        def create_one(index: int) -> str:
            with sessions() as session:
                return create_asset(
                    session,
                    company_id,
                    AssetCreate(category_id=category_id, serial_number=f'CONCURRENCY-{index}'),
                ).asset_number

        with ThreadPoolExecutor(max_workers=8) as executor:
            numbers = list(executor.map(create_one, range(24)))
        assert len(numbers) == len(set(numbers)) == 24
        assert set(numbers) == {f'CON-AST-{number:06d}' for number in range(1, 25)}
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_asset_assignment_allows_only_one_active_custodian():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CA{uuid4().hex[:12]}', name='Assignment concurrency test'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        asset = create_asset(setup, company.id, AssetCreate(category_id=category.id))
        role = setup.query(Role).filter_by(scope='company', code='read_only_user').one()
        recipient = User(
            email=f'recipient-{uuid4().hex}@example.invalid',
            password_hash='unused-test-hash',
            is_active=True,
        )
        actor = User(
            email=f'actor-{uuid4().hex}@example.invalid',
            password_hash='unused-test-hash',
            is_active=True,
        )
        setup.add_all([recipient, actor])
        setup.flush()
        setup.add(
            CompanyMembership(
                company_id=company.id,
                user_id=recipient.id,
                role_id=role.id,
                status='active',
            )
        )
        setup.commit()
        company_id, asset_id, recipient_id, actor_id = company.id, asset.id, recipient.id, actor.id

        def assign_once() -> int:
            with sessions() as session:
                actor_user = session.get(User, actor_id)
                try:
                    create_asset_assignment(
                        company_id,
                        asset_id,
                        AssignmentCreate(
                            recipient_id=recipient_id,
                            effective_date=date(2026, 10, 15),
                        ),
                        session,
                        CurrentActor(user=actor_user, session=None),
                    )
                    return 201
                except HTTPException as exc:
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: assign_once(), range(8)))
        assert results.count(201) == 1
        assert results.count(409) == 7
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_receipts_cannot_over_receive_purchase_order_line():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'RC{uuid4().hex[:12]}', name='Receipt concurrency test', number_prefix='RC'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CONC', name='Concurrency supplier')
        actor = User(
            email=f'receipt-actor-{uuid4().hex}@example.invalid',
            password_hash='unused-test-hash',
            is_active=True,
        )
        setup.add_all([supplier, actor])
        setup.flush()
        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'PO-{uuid4().hex[:12]}',
            status='open',
            ordered_date=date(2026, 10, 16),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Concurrent laptop',
            quantity_ordered=3,
            unit_cost=1000,
        )
        setup.add(line)
        setup.commit()
        company_id, order_id, line_id, actor_id = company.id, order.id, line.id, actor.id

        def receive_once(index: int) -> int:
            with sessions() as session:
                actor_user = session.get(User, actor_id)
                payload = GoodsReceiptCreate(
                    receipt_number=None,
                    received_date=date(2026, 10, 16),
                    lines=[{
                        'purchase_order_line_id': line_id,
                        'quantity_received': 2,
                    }],
                )
                try:
                    receive_goods(
                        company_id,
                        order_id,
                        payload,
                        session,
                        CurrentActor(user=actor_user, session=None),
                    )
                    return 201
                except HTTPException as exc:
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(receive_once, range(2)))
        assert sorted(results) == [201, 422]
        with sessions() as verify:
            lines = verify.query(GoodsReceiptLine).filter_by(
                company_id=company_id,
                purchase_order_line_id=line_id,
            ).all()
            assert len(lines) == 1
            assert sum(receipt_line.quantity_received for receipt_line in lines) == 2
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_invitation_acceptance_allows_only_one_success():
    from app.authentication import accept_invitation, create_invitation, digest, password_hasher
    from app.models import CompanyMembership, UserInvitation

    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'IV{uuid4().hex[:12]}', name='Invitation concurrency test', number_prefix='INV'),
        )
        admin = User(
            email=f'admin-{uuid4().hex[:8]}@example.invalid',
            password_hash=password_hasher.hash('Admin-Pass-42!'),
            is_active=True,
        )
        setup.add(admin)
        setup.flush()

        role = setup.scalar(select(Role).where(Role.code == 'read_only_user', Role.scope == 'company'))
        # 1. Test concurrent acceptance for new user
        membership, raw_token = create_invitation(
            setup,
            company_id=company.id,
            email=f'new-user-{uuid4().hex[:8]}@example.invalid',
            role=role,
            assigned_by_id=admin.id,
        )
        setup.commit()

        def accept_worker(index: int) -> bool:
            with sessions() as session:
                user = accept_invitation(session, raw_token, 'ValidPass-Concurrent-123!')
                if user is not None:
                    session.commit()
                    return True
                else:
                    session.rollback()
                    return False

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(accept_worker, range(4)))

        # Exactly one acceptance must succeed; all concurrent attempts must be rejected
        assert results.count(True) == 1, f"Expected 1 success, got {results.count(True)}"
        assert results.count(False) == 3, f"Expected 3 rejections, got {results.count(False)}"

        with sessions() as verify:
            inv = verify.scalar(select(UserInvitation).where(UserInvitation.token_hash == digest(raw_token)))
            assert inv.accepted_at is not None
            mem = verify.scalar(select(CompanyMembership).where(CompanyMembership.id == inv.membership_id))
            assert mem.status == 'active'
            usr = verify.scalar(select(User).where(User.id == mem.user_id))
            assert usr.is_active is True

        # 2. Test concurrent acceptance for existing user preserves original password
        orig_pass = 'Existing-Pass-42!'
        existing_user = User(
            email=f'existing-{uuid4().hex[:8]}@example.invalid',
            password_hash=password_hasher.hash(orig_pass),
            is_active=True,
        )
        setup.add(existing_user)
        setup.flush()

        membership2, raw_token2 = create_invitation(
            setup,
            company_id=company.id,
            email=existing_user.email,
            role=role,
            assigned_by_id=admin.id,
        )
        setup.commit()

        def accept_existing_worker(index: int) -> bool:
            with sessions() as session:
                user = accept_invitation(session, raw_token2, 'AttackerPass-Concurrent-999!')
                if user is not None:
                    session.commit()
                    return True
                else:
                    session.rollback()
                    return False

        with ThreadPoolExecutor(max_workers=4) as executor:
            results2 = list(executor.map(accept_existing_worker, range(4)))

        assert results2.count(True) == 1
        assert results2.count(False) == 3

        with sessions() as verify2:
            usr2 = verify2.scalar(select(User).where(User.email == existing_user.email))
            # Verify original password hash is untouched
            assert password_hasher.verify(usr2.password_hash, orig_pass) is True

    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_purchase_order_cancellation():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        company = create_company(
            setup,
            CompanyCreate(code=f'PO{uuid4().hex[:12]}', name='PO Cancel Concurrency', number_prefix='POC'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code=f'SUP-{uuid4().hex[:6]}', name='Supplier PO Cancel')
        setup.add(supplier)
        setup.flush()

        seed_security_defaults(setup)
        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        admin = User(
            email=f'admin-{uuid4().hex[:8]}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add(admin)
        setup.flush()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number='POC-PO-2026-27-00001',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Test cancellation concurrency item',
            quantity_ordered=5,
            unit_cost=100.0,
        )
        setup.add(line)
        setup.commit()

        company_id = company.id
        order_id = order.id
        admin_id = admin.id

        def cancel_worker(index: int):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = cancel_purchase_order(
                        company_id=company_id,
                        purchase_order_id=order_id,
                        payload=PurchaseOrderCancel(reason=f"Concurrent cancellation attempt {index}"),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("OK", res.status)
                except HTTPException as exc:
                    return ("ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(cancel_worker, range(4)))

        # Exactly 1 success (200), and 3 conflicts (409)
        ok_count = sum(1 for r in results if r[0] == "OK")
        err_count = sum(1 for r in results if r[0] == "ERR" and r[1] == 409)
        assert ok_count == 1, f"Expected 1 OK, got {results}"
        assert err_count == 3, f"Expected 3 ERR 409, got {results}"

        with sessions() as verify:
            po = verify.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order.id))
            assert po.status == 'cancelled'
            assert po.cancelled_at is not None
            assert po.cancelled_by_id == admin.id
            assert "Concurrent cancellation attempt" in po.cancellation_reason
    finally:
        setup.close()
        engine.dispose()



@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_reversals_against_same_grn():
    """
    Multiple concurrent reversal attempts against the exact same GRN and assets.
    Verifies that exactly one transaction succeeds, all others receive HTTP 409 Conflict,
    and no duplicate reversal records or corrupted quantities are created.
    """
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CR{uuid4().hex[:12]}', name='Concurrent GRN Reversal Test', number_prefix='CRG'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CRG', name='Concurrency Supplier')
        admin = User(
            email=f'admin-crg-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin])
        setup.flush()

        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        # Create PO
        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CRG-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Concurrent Reversal Asset',
            quantity_ordered=2,
            unit_cost=500.0,
        )
        setup.add(line)
        setup.flush()

        # Create GRN receiving both units
        admin_actor = CurrentActor(user=admin, session=None)
        grn_read = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[
                    GoodsReceiptLineCreate(
                        purchase_order_line_id=line.id,
                        quantity_received=2,
                        quantity_rejected=0,
                        serial_numbers=['CRG-SN-01', 'CRG-SN-02'],
                    )
                ],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        grn_id = grn_read.id
        grn_line_id = grn_read.lines[0].id
        asset_ids = [a.id for a in grn_read.lines[0].assets]
        admin_id = admin.id

        def worker(index: int):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn_id,
                        payload=GoodsReceiptReversalCreate(
                            reason=f"Concurrent reversal attempt {index}",
                            lines=[ReversalLineItem(goods_receipt_line_id=grn_line_id, asset_ids=asset_ids)],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("OK", res.id)
                except HTTPException as exc:
                    return ("ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(worker, range(4)))

        ok_count = sum(1 for r in results if r[0] == "OK")
        err_count = sum(1 for r in results if r[0] == "ERR" and r[1] == 409)
        assert ok_count == 1, f"Expected exactly 1 OK, got {results}"
        assert err_count == 3, f"Expected exactly 3 ERR 409, got {results}"

        with sessions() as verify:
            rev_count = verify.scalar(select(func.count(GoodsReceiptReversal.id)).where(GoodsReceiptReversal.goods_receipt_id == grn_id))
            assert rev_count == 1
            grn = verify.scalar(select(GoodsReceipt).where(GoodsReceipt.id == grn_id))
            assert grn.status == 'reversed'
            po = verify.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order.id))
            assert po.status == 'open'
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_reversals_of_different_grns_same_po():
    """
    Two concurrent reversals against different GRNs belonging to the same Purchase Order.
    Both should serialize cleanly on the shared PurchaseOrder lock, both succeed,
    and recalculate the PO status correctly without deadlock.
    """
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CD{uuid4().hex[:12]}', name='Concurrent Diff GRNs Test', number_prefix='CDG'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CDG', name='Diff GRN Supplier')
        admin = User(
            email=f'admin-cdg-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin])
        setup.flush()

        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        # PO ordered 4 items
        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CDG-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Multi-GRN PO Item',
            quantity_ordered=4,
            unit_cost=250.0,
        )
        setup.add(line)
        setup.flush()

        admin_actor = CurrentActor(user=admin, session=None)
        # GRN 1: receives 2 items
        grn1 = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=2, serial_numbers=['CDG-A1', 'CDG-A2'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        # GRN 2: receives remaining 2 items (PO becomes fully received)
        grn2 = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=2, serial_numbers=['CDG-B1', 'CDG-B2'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        admin_id = admin.id
        grn1_id, grn1_line_id = grn1.id, grn1.lines[0].id
        grn1_assets = [a.id for a in grn1.lines[0].assets]
        grn2_id, grn2_line_id = grn2.id, grn2.lines[0].id
        grn2_assets = [a.id for a in grn2.lines[0].assets]

        def reverse_worker(grn_id, line_id, asset_ids, name):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn_id,
                        payload=GoodsReceiptReversalCreate(
                            reason=f"Concurrent reversal of {name}",
                            lines=[ReversalLineItem(goods_receipt_line_id=line_id, asset_ids=asset_ids)],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("OK", name)
                except HTTPException as exc:
                    return ("ERR", name, exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(reverse_worker, grn1_id, grn1_line_id, grn1_assets, "GRN1")
            fut2 = executor.submit(reverse_worker, grn2_id, grn2_line_id, grn2_assets, "GRN2")
            res1, res2 = fut1.result(), fut2.result()

        assert res1[0] == "OK", f"GRN1 failed: {res1}"
        assert res2[0] == "OK", f"GRN2 failed: {res2}"

        with sessions() as verify:
            po = verify.scalar(select(PurchaseOrder).where(PurchaseOrder.id == order.id))
            assert po.status == 'open'  # Both reversed -> 0 net accepted items
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_asset_assignment_and_reversal_of_same_asset():
    """
    Races an asset assignment against a GRN reversal of the exact same asset.
    Verifies that exactly one operation succeeds, the losing operation receives HTTP 409 Conflict,
    and an assigned asset is NEVER reversed and a reversed asset is NEVER assigned.
    """
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'AR{uuid4().hex[:12]}', name='Concurrent Assign/Reverse Test', number_prefix='CAR'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CAR', name='Assign/Reverse Supplier')
        admin = User(
            email=f'admin-car-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        recipient = User(
            email=f'recipient-car-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin, recipient])
        setup.flush()

        role_admin = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        role_ro = setup.query(Role).filter_by(scope='company', code='read_only_user').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role_admin.id, status='active'))
        setup.add(CompanyMembership(company_id=company.id, user_id=recipient.id, role_id=role_ro.id, status='active'))
        setup.flush()

        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CAR-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Assign vs Reverse Asset',
            quantity_ordered=1,
            unit_cost=800.0,
        )
        setup.add(line)
        setup.flush()

        admin_actor = CurrentActor(user=admin, session=None)
        grn = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=1, serial_numbers=['CAR-SN-01'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        admin_id = admin.id
        recipient_id = recipient.id
        target_asset_id = grn.lines[0].assets[0].id
        grn_id = grn.id
        grn_line_id = grn.lines[0].id

        def assign_task():
            with sessions() as session:
                actor_user = session.get(User, admin_id)
                try:
                    create_asset_assignment(
                        company_id=company_id,
                        asset_id=target_asset_id,
                        payload=AssignmentCreate(recipient_id=recipient_id, effective_date=date.today()),
                        db=session,
                        actor=CurrentActor(user=actor_user, session=None),
                    )
                    return ("ASSIGN_OK",)
                except HTTPException as exc:
                    return ("ASSIGN_ERR", exc.status_code, exc.detail)

        def reverse_task():
            with sessions() as session:
                actor_user = session.get(User, admin_id)
                try:
                    reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn_id,
                        payload=GoodsReceiptReversalCreate(
                            reason="Raced reversal attempt",
                            lines=[ReversalLineItem(goods_receipt_line_id=grn_line_id, asset_ids=[target_asset_id])],
                        ),
                        db=session,
                        actor=CurrentActor(user=actor_user, session=None),
                    )
                    return ("REVERSE_OK",)
                except HTTPException as exc:
                    return ("REVERSE_ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_assign = executor.submit(assign_task)
            f_reverse = executor.submit(reverse_task)
            res_assign = f_assign.result()
            res_reverse = f_reverse.result()

        # Deterministic outcome: Exactly one wins, the other receives 409
        if res_assign[0] == "ASSIGN_OK":
            assert res_reverse[0] == "REVERSE_ERR" and res_reverse[1] == 409
        else:
            assert res_reverse[0] == "REVERSE_OK"
            assert res_assign[0] == "ASSIGN_ERR" and res_assign[1] == 409
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_grn_creation_and_reversal_affecting_same_po():
    """
    Races GRN creation (increasing received items) against a reversal of a prior GRN on the same PO.
    Because both operations acquire row locks starting from PurchaseOrder, both serialize safely
    without deadlocking, and leave the PO status consistent.
    """
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CRV{uuid4().hex[:12]}', name='Concurrent GRN & Reversal Test', number_prefix='CRV'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CRV', name='Receipt/Reverse Supplier')
        admin = User(
            email=f'admin-crv-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin])
        setup.flush()

        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        # PO ordered 4 items
        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CRV-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()
        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Concurrent Receive and Reverse Line',
            quantity_ordered=4,
            unit_cost=100.0,
        )
        setup.add(line)
        setup.flush()

        admin_actor = CurrentActor(user=admin, session=None)
        # GRN 1 receives 2 items initially (PO is partially_received)
        grn1 = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=2, serial_numbers=['CRV-01', 'CRV-02'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        admin_id = admin.id
        po_id = order.id
        po_line_id = line.id
        grn1_id = grn1.id
        grn1_line_id = grn1.lines[0].id
        grn1_assets = [a.id for a in grn1.lines[0].assets]

        # Task 1: Create GRN 2 receiving remaining 2 items
        def receive_more_task():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = receive_goods(
                        company_id=company_id,
                        purchase_order_id=po_id,
                        payload=GoodsReceiptCreate(
                            received_date=date.today(),
                            lines=[GoodsReceiptLineCreate(purchase_order_line_id=po_line_id, quantity_received=2, serial_numbers=['CRV-03', 'CRV-04'])],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("RECV_OK", res.id)
                except HTTPException as exc:
                    return ("RECV_ERR", exc.status_code, exc.detail)

        # Task 2: Reverse GRN 1
        def reverse_first_task():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn1_id,
                        payload=GoodsReceiptReversalCreate(
                            reason="Concurrent reversal of GRN1 while receiving GRN2",
                            lines=[ReversalLineItem(goods_receipt_line_id=grn1_line_id, asset_ids=grn1_assets)],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("REV_OK", res.id)
                except HTTPException as exc:
                    return ("REV_ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(receive_more_task)
            f2 = executor.submit(reverse_first_task)
            r1, r2 = f1.result(), f2.result()

        assert r1[0] == "RECV_OK", f"Receive task failed: {r1}"
        assert r2[0] == "REV_OK", f"Reverse task failed: {r2}"

        with sessions() as verify:
            po = verify.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
            # 2 received on GRN2, 2 reversed on GRN1 -> net accepted is 2 out of 4 -> partially_received!
            assert po.status == 'partially_received'
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_partial_reversals_competing_for_same_quantity():
    """
    Two concurrent workers attempt partial reversals competing for the same remaining line quantity
    or overlapping assets (e.g. Line has 3 units, worker 1 requests 2 units [A0, A1], worker 2 requests 2 units [A1, A2]).
    Verifies that exactly one transaction succeeds, the second receives HTTP 409 Conflict,
    and the line's quantity_reversed never exceeds the accepted quantity.
    """
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CPR{uuid4().hex[:12]}', name='Concurrent Competing Reversals', number_prefix='CPR'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CPR', name='Competing Reversal Supplier')
        admin = User(
            email=f'admin-cpr-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin])
        setup.flush()

        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CPR-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()

        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Competing Reversal Assets',
            quantity_ordered=3,
            unit_cost=100.0,
        )
        setup.add(line)
        setup.flush()

        admin_actor = CurrentActor(user=admin, session=None)
        grn = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=3, serial_numbers=['CPR-01', 'CPR-02', 'CPR-03'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        admin_id = admin.id
        grn_id = grn.id
        grn_line_id = grn.lines[0].id
        assets = [a.id for a in grn.lines[0].assets]

        def worker(asset_subset: list, label: str):
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn_id,
                        payload=GoodsReceiptReversalCreate(
                            reason=f"Competing reversal {label}",
                            lines=[ReversalLineItem(goods_receipt_line_id=grn_line_id, asset_ids=asset_subset)],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("OK", res.id)
                except HTTPException as exc:
                    return ("ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker, [assets[0], assets[1]], "Worker 1")
            f2 = executor.submit(worker, [assets[1], assets[2]], "Worker 2")
            r1, r2 = f1.result(), f2.result()

        ok_count = (1 if r1[0] == "OK" else 0) + (1 if r2[0] == "OK" else 0)
        err_count = (1 if r1[0] == "ERR" and r1[1] == 409 else 0) + (1 if r2[0] == "ERR" and r2[1] == 409 else 0)
        assert ok_count == 1, f"Expected exactly 1 OK, got r1={r1}, r2={r2}"
        assert err_count == 1, f"Expected exactly 1 ERR 409, got r1={r1}, r2={r2}"

        with sessions() as verify:
            grn_line = verify.scalar(select(GoodsReceiptLine).where(GoodsReceiptLine.id == grn_line_id))
            assert grn_line.quantity_reversed == 2
            rev_assets = verify.scalars(select(GoodsReceiptReversalAsset.asset_id).where(GoodsReceiptReversalAsset.company_id == company_id)).all()
            assert len(rev_assets) == 2
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_po_cancellation_and_grn_reversal():
    """
    Races PO cancellation against a GRN reversal on the same PO.
    Because both operations acquire row-level locks on PurchaseOrder at Tier 1, they serialize
    without deadlock. In all execution orderings:
    - Both operations complete successfully.
    - The final PO status is guaranteed to be 'cancelled'.
    """
    from app.api.v1.routes.procurement import cancel_purchase_order
    from app.schemas import PurchaseOrderCancel

    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        seed_security_defaults(setup)
        company = create_company(
            setup,
            CompanyCreate(code=f'CX{uuid4().hex[:12]}', name='Concurrent Cancel & Reverse Test', number_prefix='CCR'),
        )
        category = setup.query(AssetCategory).filter_by(company_id=company.id, code='LAPTOP').one()
        supplier = Supplier(company_id=company.id, code='SUP-CCR', name='Cancel/Reverse Supplier')
        admin = User(
            email=f'admin-ccr-{uuid4().hex}@example.invalid',
            password_hash=password_hasher.hash('Correct-Horse-42!'),
            is_active=True,
        )
        setup.add_all([supplier, admin])
        setup.flush()

        role = setup.query(Role).filter_by(scope='company', code='company_administrator').one()
        setup.add(CompanyMembership(company_id=company.id, user_id=admin.id, role_id=role.id, status='active'))
        setup.flush()

        order = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier.id,
            order_number=f'CCR-PO-{uuid4().hex[:6].upper()}',
            status='open',
            ordered_date=date.today(),
        )
        setup.add(order)
        setup.flush()

        line = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=order.id,
            category_id=category.id,
            description='Cancel vs Reverse Line',
            quantity_ordered=4,
            unit_cost=250.0,
        )
        setup.add(line)
        setup.flush()

        admin_actor = CurrentActor(user=admin, session=None)
        grn = receive_goods(
            company_id=company.id,
            purchase_order_id=order.id,
            payload=GoodsReceiptCreate(
                received_date=date.today(),
                lines=[GoodsReceiptLineCreate(purchase_order_line_id=line.id, quantity_received=2, serial_numbers=['CCR-01', 'CCR-02'])],
            ),
            db=setup,
            actor=admin_actor,
        )
        setup.commit()

        company_id = company.id
        admin_id = admin.id
        po_id = order.id
        grn_id = grn.id
        grn_line_id = grn.lines[0].id
        asset_ids = [a.id for a in grn.lines[0].assets]

        def cancel_task():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = cancel_purchase_order(
                        company_id=company_id,
                        purchase_order_id=po_id,
                        payload=PurchaseOrderCancel(reason="Concurrent PO short-close"),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("CANCEL_OK", res.status)
                except HTTPException as exc:
                    return ("CANCEL_ERR", exc.status_code, exc.detail)

        def reverse_task():
            with sessions() as session:
                worker_actor = CurrentActor(user=session.get(User, admin_id), session=None)
                try:
                    res = reverse_goods_receipt(
                        company_id=company_id,
                        goods_receipt_id=grn_id,
                        payload=GoodsReceiptReversalCreate(
                            reason="Concurrent GRN reversal during cancellation",
                            lines=[ReversalLineItem(goods_receipt_line_id=grn_line_id, asset_ids=asset_ids)],
                        ),
                        db=session,
                        actor=worker_actor,
                    )
                    return ("REVERSE_OK", res.id)
                except HTTPException as exc:
                    return ("REVERSE_ERR", exc.status_code, exc.detail)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_cancel = executor.submit(cancel_task)
            f_reverse = executor.submit(reverse_task)
            r_cancel = f_cancel.result()
            r_reverse = f_reverse.result()

        assert r_cancel[0] == "CANCEL_OK", f"Cancellation failed: {r_cancel}"
        assert r_reverse[0] == "REVERSE_OK", f"Reversal failed: {r_reverse}"

        with sessions() as verify:
            final_po = verify.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
            assert final_po.status == 'cancelled', f"PO status must remain cancelled, got {final_po.status}"
            final_grn = verify.scalar(select(GoodsReceipt).where(GoodsReceipt.id == grn_id))
            assert final_grn.status == 'reversed'
    finally:
        setup.close()
        engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='set TEST_DATABASE_URL to run PostgreSQL concurrency integration')
def test_concurrent_company_creation_reference_allocation_is_unique():
    engine = create_engine(os.environ['TEST_DATABASE_URL'], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    setup = sessions()
    try:
        def create_one(index: int) -> str:
            with sessions() as session:
                co = create_company(
                    session,
                    CompanyCreate(code=f'CC_{uuid4().hex[:8]}_{index}', name=f'Concurrent Co {index}'),
                )
                return co.reference_number

        with ThreadPoolExecutor(max_workers=8) as executor:
            refs = list(executor.map(create_one, range(16)))

        assert len(refs) == len(set(refs)) == 16, f"Expected 16 unique references, got duplicates: {refs}"
        for ref in refs:
            assert ref.startswith('CMP-'), f"Invalid reference format: {ref}"
    finally:
        setup.close()
        engine.dispose()

