import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.database import Base
from app.models import (
    AssetCategory,
    CompanyMembership,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Supplier,
    User,
)
from app.schemas import AssetCreate, AssignmentCreate, CompanyCreate, GoodsReceiptCreate
from app.security import CurrentActor
from app.security_seed import seed_security_defaults
from app.api.v1.routes.assets import create_asset_assignment
from app.api.v1.routes.procurement import receive_goods
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
            CompanyCreate(code=f'CT{uuid4().hex[:12]}', name='Numbering concurrency test', number_prefix='CON'),
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
        assert set(numbers) == {f'CON-{number:06d}' for number in range(1, 25)}
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
            CompanyCreate(code=f'RC{uuid4().hex[:12]}', name='Receipt concurrency test'),
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
                    receipt_number=f'GRN-CONC-{index}',
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
