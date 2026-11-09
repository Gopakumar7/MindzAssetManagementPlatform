"""Comprehensive test suite for ReferenceNumberService and sequence allocation.

Covers:
1. Permanent numbering (assets, continuing sequence, no FY token).
2. Financial-year numbering (PO, GRN, VC, SR, MWO, TRF, DSP).
3. Financial-year boundary rollover (March 31 23:59:59 to April 1 00:00:00 IST).
4. Backdated document dates (prior FY attribution).
5. Concurrency safety (multi-threaded concurrent allocation without duplicates).
6. Multi-tenant company isolation.
7. Transaction rollback (counter restored on uncommitted rollback).
8. Cancellation and non-reuse (gap acceptance, references permanently consumed).
9. Prefix immutability (standard updates blocked when current_value > 0).
10. Controlled prefix configuration with mandatory audit logging.
11. Review corrections:
    - IMP-1: Block unprovisioned company allocations.
    - IMP-2: Collision protection on controlled prefix changes & schema safety.
    - IMP-3: Append-only triggers on reference_sequence_audits.
    - MIN-2: Company provisioning helper & independent sequence verification.
    - MIN-3: Inactive sequence allocation rejection (SequenceInactiveError).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from uuid import UUID, uuid4
import zoneinfo
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import Asset, AssetCategory, Company, ReferenceSequence, ReferenceSequenceAudit, User
from app.reference_service import (
    DEFAULT_TIMEZONE,
    PrefixImmutabilityError,
    ReferenceNumberService,
    SequenceInactiveError,
    SequenceNotFoundError,
)


def create_test_company(
    db: Session,
    code: str = "MZ-TEST",
    name: str = "Test Company",
    prefix_base: str | None = None,
    provision: bool = True,
) -> Company:
    """Helper to create a test company, optionally provisioning default sequences."""
    company = Company(id=uuid4(), code=code, name=name, is_active=True)
    db.add(company)
    db.commit()
    db.refresh(company)

    if provision:
        pfx = prefix_base
        if not pfx:
            if "WEWIN" in code.upper() or "WW" in code.upper():
                pfx = "WW"
            elif "ACME" in code.upper():
                pfx = "ACME"
            else:
                pfx = "MZ"
        ReferenceNumberService.provision_company_sequences(db, company.id, prefix_base=pfx)
        db.commit()

    return company


def test_get_fiscal_year_standard():
    """Verify standard financial year calculation (April 1 to March 31)."""
    # Mid-year
    assert ReferenceNumberService.get_fiscal_year(date(2026, 7, 15)) == "2026-27"
    assert ReferenceNumberService.get_fiscal_year(date(2026, 11, 2)) == "2026-27"
    # Q4 (Jan-Mar) belongs to 2026-27
    assert ReferenceNumberService.get_fiscal_year(date(2027, 1, 10)) == "2026-27"
    assert ReferenceNumberService.get_fiscal_year(date(2027, 3, 31)) == "2026-27"
    # April 1 rolls over to 2027-28
    assert ReferenceNumberService.get_fiscal_year(date(2027, 4, 1)) == "2027-28"
    assert ReferenceNumberService.get_fiscal_year(date(2027, 12, 31)) == "2027-28"


def test_get_fiscal_year_datetime_timezone():
    """Verify datetime handling with Asia/Kolkata timezone boundary."""
    # Boundary: March 31 23:59:59 IST
    dt_fy_end = datetime(2027, 3, 31, 23, 59, 59, tzinfo=DEFAULT_TIMEZONE)
    assert ReferenceNumberService.get_fiscal_year(dt_fy_end) == "2026-27"

    # Boundary: April 1 00:00:00 IST
    dt_fy_start = datetime(2027, 4, 1, 0, 0, 0, tzinfo=DEFAULT_TIMEZONE)
    assert ReferenceNumberService.get_fiscal_year(dt_fy_start) == "2027-28"

    # UTC datetime: April 1 01:00:00 IST is March 31 19:30:00 UTC
    utc_tz = zoneinfo.ZoneInfo("UTC")
    dt_utc = datetime(2027, 3, 31, 19, 30, 0, tzinfo=utc_tz)
    # When converted to Asia/Kolkata, it is April 1, 2027
    assert ReferenceNumberService.get_fiscal_year(dt_utc) == "2027-28"


def test_permanent_numbering_continuity(db_session: Session):
    """
    Verify permanent numbering for master records:
    1. Continues existing sequence (seeded at 21 -> next is 22).
    2. Format: MZ-AST-000022 with 6-digit padding and no FY token.
    3. Increments monotonically.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", name="MindZen Demo Company", provision=False)

    # Seed initial asset sequence with current_value = 21 (simulating existing MZ-000001 to MZ-000021)
    seq = ReferenceSequence(
        id=uuid4(),
        company_id=company.id,
        entity_type="asset",
        fiscal_year="PERMANENT",
        prefix="MZ-AST",
        separator="-",
        padding=6,
        current_value=21,
        is_active=True,
    )
    db_session.add(seq)
    db_session.commit()

    ref1 = ReferenceNumberService.allocate(db_session, company.id, "asset", is_permanent=True)
    db_session.commit()
    assert ref1 == "MZ-AST-000022"

    ref2 = ReferenceNumberService.allocate(db_session, company.id, "asset", is_permanent=True)
    db_session.commit()
    assert ref2 == "MZ-AST-000023"

    ref3 = ReferenceNumberService.allocate(db_session, company.id, "asset", is_permanent=True)
    db_session.commit()
    assert ref3 == "MZ-AST-000024"


def test_financial_year_numbering(db_session: Session):
    """
    Verify financial-year scoped numbering for transactional entities:
    Format: MZ-PO-2026-27-00001
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", name="MindZen Demo", provision=True)
    business_date = date(2026, 11, 2)

    # 1. Purchase Orders
    po_ref1 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=business_date)
    po_ref2 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=business_date)
    db_session.commit()
    assert po_ref1 == "MZ-PO-2026-27-00001"
    assert po_ref2 == "MZ-PO-2026-27-00002"

    # 2. Goods Receipts
    grn_ref = ReferenceNumberService.allocate(db_session, company.id, "goods_receipt", business_date=business_date)
    db_session.commit()
    assert grn_ref == "MZ-GRN-2026-27-00001"

    # 3. Verification Campaigns
    vc_ref = ReferenceNumberService.allocate(db_session, company.id, "verification_campaign", business_date=business_date)
    db_session.commit()
    assert vc_ref == "MZ-VC-2026-27-00001"

    # 4. Service Requests
    sr_ref = ReferenceNumberService.allocate(db_session, company.id, "service_request", business_date=business_date)
    db_session.commit()
    assert sr_ref == "MZ-SR-2026-27-00001"

    # 5. Maintenance Work Orders
    mwo_ref = ReferenceNumberService.allocate(db_session, company.id, "maintenance_work_order", business_date=business_date)
    db_session.commit()
    assert mwo_ref == "MZ-MWO-2026-27-00001"

    # 6. Asset Transfers
    trf_ref = ReferenceNumberService.allocate(db_session, company.id, "asset_transfer", business_date=business_date)
    db_session.commit()
    assert trf_ref == "MZ-TRF-2026-27-00001"

    # 7. Asset Disposals
    dsp_ref = ReferenceNumberService.allocate(db_session, company.id, "asset_disposal", business_date=business_date)
    db_session.commit()
    assert dsp_ref == "MZ-DSP-2026-27-00001"


def test_financial_year_boundary_rollover(db_session: Session):
    """
    Verify rollover on April 1:
    - March 31: issues 2026-27 sequence.
    - April 1: lazily initializes and issues 2027-28 sequence resetting to 00001.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # Allocate in 2026-27
    ref_fy26 = ReferenceNumberService.allocate(
        db_session, company.id, "purchase_order", business_date=date(2027, 3, 31)
    )
    db_session.commit()
    assert ref_fy26 == "MZ-PO-2026-27-00001"

    # Allocate across the boundary in 2027-28
    ref_fy27 = ReferenceNumberService.allocate(
        db_session, company.id, "purchase_order", business_date=date(2027, 4, 1)
    )
    db_session.commit()
    assert ref_fy27 == "MZ-PO-2027-28-00001"

    # Next allocation in 2027-28 increments the new counter
    ref_fy27_2 = ReferenceNumberService.allocate(
        db_session, company.id, "purchase_order", business_date=date(2027, 4, 2)
    )
    db_session.commit()
    assert ref_fy27_2 == "MZ-PO-2027-28-00002"


def test_backdated_document_date_handling(db_session: Session):
    """
    Verify that backdated document dates allocate from their corresponding accounting FY.
    Example: On April 10, 2027, a late PO with ordered_date = March 25, 2027 is created.
    It must receive a reference in 2026-27, not 2027-28.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # Existing 2026-27 records
    ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 12, 1))
    db_session.commit()

    # Enter a backdated PO for March 25, 2027
    backdated_ref = ReferenceNumberService.allocate(
        db_session, company.id, "purchase_order", business_date=date(2027, 3, 25)
    )
    db_session.commit()
    assert backdated_ref == "MZ-PO-2026-27-00002"


def test_company_multi_tenant_isolation(db_session: Session):
    """
    Verify strict tenant isolation:
    Allocations in Company A do not alter or advance Company B's counter.
    """
    company_a = create_test_company(db_session, code="MINDZEN-DEMO", name="MindZen Demo", provision=True)
    company_b = create_test_company(db_session, code="WEWIN-DEMO", name="WeWin Demo", provision=True)

    # Allocate for Company A
    a_ref1 = ReferenceNumberService.allocate(db_session, company_a.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert a_ref1 == "MZ-PO-2026-27-00001"

    # Allocate for Company B
    b_ref1 = ReferenceNumberService.allocate(db_session, company_b.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert b_ref1 == "WW-PO-2026-27-00001"

    # Allocate again for Company A
    a_ref2 = ReferenceNumberService.allocate(db_session, company_a.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert a_ref2 == "MZ-PO-2026-27-00002"

    # Allocate again for Company B
    b_ref2 = ReferenceNumberService.allocate(db_session, company_b.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert b_ref2 == "WW-PO-2026-27-00002"


def test_transaction_rollback_behaviour(db_session: Session):
    """
    Verify database transaction rollback behavior:
    If a transaction increments the counter but rolls back before commit,
    PostgreSQL transaction rollback reverts the counter increment.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # Allocate reference 1 and commit
    ref1 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref1 == "MZ-PO-2026-27-00001"

    # Start a transaction that attempts to allocate reference 2 but fails/rolls back
    try:
        ref2_candidate = ReferenceNumberService.allocate(
            db_session, company.id, "purchase_order", business_date=date(2026, 11, 1)
        )
        assert ref2_candidate == "MZ-PO-2026-27-00002"
        # Simulate unhandled exception or business failure
        raise RuntimeError("Simulated failure before transaction commit")
    except RuntimeError:
        db_session.rollback()

    # Next transaction should see the uncommitted transaction rolled back
    ref2_reissued = ReferenceNumberService.allocate(
        db_session, company.id, "purchase_order", business_date=date(2026, 11, 1)
    )
    db_session.commit()
    assert ref2_reissued == "MZ-PO-2026-27-00002"


def test_cancellation_and_non_reuse_leaves_gap(db_session: Session):
    """
    Verify cancellation non-reuse rule:
    Once a reference is committed to a record and cancelled, that reference
    is permanently consumed. The sequence advances without reuse, accepting gaps.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # Issue PO 1
    ref1 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref1 == "MZ-PO-2026-27-00001"

    # Issue PO 2
    ref2 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref2 == "MZ-PO-2026-27-00002"

    # Business event: PO 2 is cancelled due to supplier discontinuation.
    # The reference is NEVER re-allocated or decremented.

    # Issue PO 3
    ref3 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref3 == "MZ-PO-2026-27-00003"
    assert ref3 != ref2  # Reference 2 was permanently consumed; a gap exists.


def test_prefix_immutability_standard_update(db_session: Session):
    """
    Verify prefix immutability:
    1. Before any references are issued (current_value == 0), standard prefix edit is allowed.
    2. Once references are issued (current_value > 0), standard prefix edit is strictly blocked.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    seq = ReferenceNumberService.ensure_sequence_exists(
        db_session, company.id, "purchase_order", "2026-27"
    )
    db_session.commit()

    # When current_value == 0, updating prefix via standard method is allowed
    assert seq.current_value == 0
    updated_seq = ReferenceNumberService.update_sequence_standard(
        db_session, seq.id, new_prefix="MZ-ORD"
    )
    db_session.commit()
    assert updated_seq.prefix == "MZ-ORD"

    # Allocate a reference so current_value > 0
    ref = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref == "MZ-ORD-2026-27-00001"

    # Now attempt to change prefix via standard method: MUST RAISE PrefixImmutabilityError
    with pytest.raises(PrefixImmutabilityError) as exc_info:
        ReferenceNumberService.update_sequence_standard(
            db_session, seq.id, new_prefix="MZ-PO-NEW"
        )
    assert "immutable" in str(exc_info.value).lower()


def test_controlled_prefix_audit_procedure(db_session: Session):
    """
    Verify controlled support procedure for exceptional prefix changes:
    1. Mandatory audit fields (reason, ticket_reference, operator user ID).
    2. Missing audit fields raise ValueError.
    3. Successful update creates ReferenceSequenceAudit record.
    4. Subsequent allocations use the new prefix with the next consecutive counter.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # Issue first reference
    ref1 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref1 == "MZ-PO-2026-27-00001"

    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "purchase_order",
            ReferenceSequence.fiscal_year == "2026-27",
        )
    )

    # Find or create a support staff user for the audit record
    user = db_session.scalar(select(User))
    if not user:
        user = User(id=uuid4(), email="support-admin@mindzen.internal")
        db_session.add(user)
        db_session.commit()

    # 1. Validation checks: missing reason or ticket must fail
    with pytest.raises(ValueError) as exc:
        ReferenceNumberService.update_prefix_controlled(
            db_session,
            sequence_id=seq.id,
            new_prefix="MZ-PURCHASE",
            reason="",
            performed_by_id=user.id,
            ticket_reference="SUP-1001",
        )
    assert "reason" in str(exc.value).lower()

    with pytest.raises(ValueError) as exc:
        ReferenceNumberService.update_prefix_controlled(
            db_session,
            sequence_id=seq.id,
            new_prefix="MZ-PURCHASE",
            reason="Corporate rebrand",
            performed_by_id=user.id,
            ticket_reference="",
        )
    assert "ticket reference" in str(exc.value).lower()

    # 2. Execute valid controlled prefix change
    updated_seq = ReferenceNumberService.update_prefix_controlled(
        db_session,
        sequence_id=seq.id,
        new_prefix="MZ-PURCHASE",
        reason="Corporate rebrand requested by CFO",
        performed_by_id=user.id,
        ticket_reference="SUP-TICKET-8492",
    )
    db_session.commit()
    assert updated_seq.prefix == "MZ-PURCHASE"

    # 3. Verify audit record in database
    audit = db_session.scalar(
        select(ReferenceSequenceAudit).where(ReferenceSequenceAudit.sequence_id == seq.id)
    )
    assert audit is not None
    assert audit.old_prefix == "MZ-PO"
    assert audit.new_prefix == "MZ-PURCHASE"
    assert audit.reason == "Corporate rebrand requested by CFO"
    assert audit.ticket_reference == "SUP-TICKET-8492"
    assert audit.performed_by_id == user.id

    # 4. Verify subsequent allocation uses new prefix with consecutive counter (00002)
    ref2 = ReferenceNumberService.allocate(db_session, company.id, "purchase_order", business_date=date(2026, 11, 1))
    db_session.commit()
    assert ref2 == "MZ-PURCHASE-2026-27-00002"


def test_concurrent_allocations_stress(db_session: Session):
    """
    Multi-threaded concurrency stress test:
    Simulates 20 simultaneous threads allocating Purchase Order references for the same tenant.
    Verifies:
    1. Zero duplicate references (all 20 are unique).
    2. Monotonically consecutive numbering (1 to 20).
    3. Final sequence current_value equals 20.
    """
    bind = db_session.bind
    if bind.dialect.name != "postgresql":
        pytest.skip("Concurrency locking test requires PostgreSQL")

    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    ThreadSession = sessionmaker(bind=bind, autocommit=False, autoflush=False)
    num_threads = 20
    results: list[str] = []
    errors: list[Exception] = []

    def worker_allocate():
        session = ThreadSession()
        try:
            allocated = ReferenceNumberService.allocate(
                session,
                company.id,
                "purchase_order",
                business_date=date(2026, 11, 1),
            )
            session.commit()
            return allocated
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_allocate) for _ in range(num_threads)]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                errors.append(e)

    assert len(errors) == 0, f"Encountered concurrency errors: {errors}"
    assert len(results) == num_threads

    # Verify all references are unique (no race condition collision)
    unique_refs = set(results)
    assert len(unique_refs) == num_threads, f"Duplicates detected in concurrent allocation: {results}"

    # Verify all references follow format MZ-PO-2026-27-00001 through MZ-PO-2026-27-00020
    expected_suffixes = {f"{i:05d}" for i in range(1, num_threads + 1)}
    actual_suffixes = {r.split("-")[-1] for r in results}
    assert actual_suffixes == expected_suffixes

    # Verify final database current_value is exactly 20
    db_session.expire_all()
    final_seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "purchase_order",
            ReferenceSequence.fiscal_year == "2026-27",
        )
    )
    assert final_seq.current_value == num_threads


# ====================================================================
# Review Corrections Tests (IMP-1, IMP-2, IMP-3, MIN-2, MIN-3)
# ====================================================================

def test_unprovisioned_company_allocation_fails(db_session: Session):
    """
    IMP-1: Verify that allocating a reference for an unprovisioned company
    raises SequenceNotFoundError and does NOT silently auto-derive prefixes.
    """
    unprovisioned_company = create_test_company(
        db_session, code="UNPROVISIONED-CO", name="Unprovisioned Corp", provision=False
    )

    with pytest.raises(SequenceNotFoundError) as exc_info:
        ReferenceNumberService.allocate(
            db_session,
            unprovisioned_company.id,
            "purchase_order",
            business_date=date(2026, 11, 2),
        )

    err_msg = str(exc_info.value)
    assert "not been provisioned" in err_msg
    assert "purchase_order" in err_msg


def test_provision_company_sequences_explicit(db_session: Session):
    """
    MIN-2: Verify explicit company provisioning creates all entity sequences
    with the specified prefix base and correct padding.
    """
    company = create_test_company(
        db_session, code="ACME-CORP", name="Acme Corporation", provision=False
    )

    sequences = ReferenceNumberService.provision_company_sequences(
        db_session, company.id, prefix_base="ACME"
    )
    db_session.commit()

    assert len(sequences) == 9
    seq_map = {s.entity_type: s for s in sequences}

    assert seq_map["asset"].prefix == "ACME-AST"
    assert seq_map["asset"].padding == 6
    assert seq_map["asset"].fiscal_year == "PERMANENT"

    assert seq_map["purchase_order"].prefix == "ACME-PO"
    assert seq_map["purchase_order"].padding == 5
    assert seq_map["purchase_order"].fiscal_year == ReferenceNumberService.get_fiscal_year()

    assert seq_map["goods_return"].prefix == "ACME-GRR"
    assert seq_map["goods_return"].padding == 5
    assert seq_map["goods_return"].fiscal_year == ReferenceNumberService.get_fiscal_year()

    # Verify allocations work immediately after explicit provisioning
    asset_ref = ReferenceNumberService.allocate(db_session, company.id, "asset")
    po_ref = ReferenceNumberService.allocate(db_session, company.id, "purchase_order")
    db_session.commit()

    assert asset_ref == "ACME-AST-000001"
    assert po_ref.startswith("ACME-PO-")
    assert po_ref.endswith("-00001")


def test_independent_company_entity_configurations(db_session: Session):
    """
    MIN-2: Verify that independent companies maintain completely isolated
    numbering sequences, prefixes, and counters across multiple entities.
    """
    company_1 = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)
    company_2 = create_test_company(db_session, code="WEWIN-DEMO", provision=True)

    # Permanent asset allocations
    ast_1 = ReferenceNumberService.allocate(db_session, company_1.id, "asset")
    ast_2 = ReferenceNumberService.allocate(db_session, company_2.id, "asset")
    assert ast_1 == "MZ-AST-000001"
    assert ast_2 == "WW-AST-000001"

    # Transactional Goods Receipt allocations
    grn_1 = ReferenceNumberService.allocate(db_session, company_1.id, "goods_receipt", business_date=date(2026, 11, 2))
    grn_2 = ReferenceNumberService.allocate(db_session, company_2.id, "goods_receipt", business_date=date(2026, 11, 2))
    assert grn_1 == "MZ-GRN-2026-27-00001"
    assert grn_2 == "WW-GRN-2026-27-00001"

    # Multiple increments for company 1 do not touch company 2
    ReferenceNumberService.allocate(db_session, company_1.id, "goods_receipt", business_date=date(2026, 11, 2))
    grn_1_third = ReferenceNumberService.allocate(db_session, company_1.id, "goods_receipt", business_date=date(2026, 11, 2))
    assert grn_1_third == "MZ-GRN-2026-27-00003"

    grn_2_second = ReferenceNumberService.allocate(db_session, company_2.id, "goods_receipt", business_date=date(2026, 11, 2))
    assert grn_2_second == "WW-GRN-2026-27-00002"


def test_inactive_sequence_rejection(db_session: Session):
    """
    MIN-3: Verify that an inactive sequence raises SequenceInactiveError
    and is not silently reactivated or incremented.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "purchase_order",
            ReferenceSequence.fiscal_year == "2026-27",
        )
    )
    # Deactivate sequence
    seq.is_active = False
    seq.current_value = 5
    db_session.commit()

    # Allocation attempt must raise SequenceInactiveError
    with pytest.raises(SequenceInactiveError) as exc_info:
        ReferenceNumberService.allocate(
            db_session, company.id, "purchase_order", business_date=date(2026, 11, 2)
        )

    assert "is inactive" in str(exc_info.value).lower()

    # Verify sequence state has not been mutated
    db_session.expire_all()
    seq_refetched = db_session.get(ReferenceSequence, seq.id)
    assert seq_refetched.is_active is False
    assert seq_refetched.current_value == 5


def test_prefix_collision_rejected_in_controlled_procedure(db_session: Session):
    """
    IMP-2: Verify that update_prefix_controlled() checks for collisions
    against existing references in the target business table (assets) and rejects
    the change before any mutation or audit log is committed.
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    # 1. Create a dummy asset with asset_number 'COLLIDE-AST-000100'
    cat = AssetCategory(
        id=uuid4(),
        company_id=company.id,
        code="IT-COLLIDE",
        name="Collision Category",
    )
    db_session.add(cat)
    db_session.flush()

    existing_asset = Asset(
        id=uuid4(),
        company_id=company.id,
        category_id=cat.id,
        asset_number="COLLIDE-AST-000100",
        status="in_use",
    )
    db_session.add(existing_asset)
    db_session.commit()

    # Find the company's asset sequence
    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "asset",
        )
    )
    user = db_session.scalar(select(User))
    if not user:
        user = User(id=uuid4(), email="support@mindzen.internal")
        db_session.add(user)
        db_session.commit()

    orig_prefix = seq.prefix
    orig_val = seq.current_value

    # Attempt to change prefix to 'COLLIDE-AST' -> MUST BE REJECTED
    with pytest.raises(ValueError) as exc_info:
        ReferenceNumberService.update_prefix_controlled(
            db_session,
            sequence_id=seq.id,
            new_prefix="COLLIDE-AST",
            reason="Attempting colliding prefix",
            performed_by_id=user.id,
            ticket_reference="TICKET-COLLIDE",
        )

    assert "already exist in assets" in str(exc_info.value)

    # Verify sequence was not altered and current_value was preserved
    db_session.expire_all()
    seq_refetched = db_session.get(ReferenceSequence, seq.id)
    assert seq_refetched.prefix == orig_prefix
    assert seq_refetched.current_value == orig_val

    # Verify no audit record was inserted
    audits = db_session.scalars(
        select(ReferenceSequenceAudit).where(ReferenceSequenceAudit.ticket_reference == "TICKET-COLLIDE")
    ).all()
    assert len(audits) == 0


def test_prefix_collision_unsafe_schema_rejected(db_session: Session):
    """
    IMP-2: Verify that update_prefix_controlled() rejects prefix change
    if collision checks cannot be performed safely (e.g. column not yet migrated).
    """
    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)

    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "service_request",
        )
    )
    user = db_session.scalar(select(User))
    if not user:
        user = User(id=uuid4(), email="support@mindzen.internal")
        db_session.add(user)
        db_session.commit()

    # Column request_number has not been added to maintenance_requests yet
    with pytest.raises(ValueError) as exc_info:
        ReferenceNumberService.update_prefix_controlled(
            db_session,
            sequence_id=seq.id,
            new_prefix="MZ-SR-V2",
            reason="Service request prefix update",
            performed_by_id=user.id,
            ticket_reference="TICKET-SR-01",
        )

    assert "cannot verify prefix collisions safely" in str(exc_info.value).lower()


def test_audit_table_append_only_triggers(db_session: Session):
    """
    IMP-3: Verify that PostgreSQL BEFORE UPDATE and BEFORE DELETE triggers
    on reference_sequence_audits reject any mutations with an append-only error.
    """
    bind = db_session.get_bind()
    if bind.dialect.name != "postgresql":
        pytest.skip("Append-only triggers require PostgreSQL")

    # Ensure triggers from migration 20261102_ref_seq_audit_guard exist in test database
    db_session.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION reject_reference_sequence_audit_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'reference_sequence_audits records are append-only and cannot be modified or deleted';
            END;
            $$;

            DROP TRIGGER IF EXISTS reference_sequence_audits_no_update ON reference_sequence_audits;
            CREATE TRIGGER reference_sequence_audits_no_update
            BEFORE UPDATE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();

            DROP TRIGGER IF EXISTS reference_sequence_audits_no_delete ON reference_sequence_audits;
            CREATE TRIGGER reference_sequence_audits_no_delete
            BEFORE DELETE ON reference_sequence_audits
            FOR EACH ROW EXECUTE FUNCTION reject_reference_sequence_audit_mutation();
            """
        )
    )
    db_session.commit()

    company = create_test_company(db_session, code="MINDZEN-DEMO", provision=True)
    user = db_session.scalar(select(User))
    if not user:
        user = User(id=uuid4(), email="admin@mindzen.internal")
        db_session.add(user)
        db_session.commit()

    seq = db_session.scalar(
        select(ReferenceSequence).where(
            ReferenceSequence.company_id == company.id,
            ReferenceSequence.entity_type == "purchase_order",
        )
    )

    audit = ReferenceSequenceAudit(
        id=uuid4(),
        sequence_id=seq.id,
        company_id=company.id,
        entity_type="purchase_order",
        fiscal_year="2026-27",
        old_prefix="MZ-PO",
        new_prefix="MZ-ORD",
        old_padding=5,
        new_padding=5,
        reason="Testing append-only triggers",
        performed_by_id=user.id,
        ticket_reference="TEST-TRIG-001",
    )
    db_session.add(audit)
    db_session.commit()

    # 1. Attempt UPDATE -> must be rejected by trigger
    with pytest.raises(Exception) as exc_update:
        db_session.execute(
            update(ReferenceSequenceAudit)
            .where(ReferenceSequenceAudit.id == audit.id)
            .values(reason="Tampered reason")
        )
        db_session.flush()
    assert "append-only" in str(exc_update.value).lower()
    db_session.rollback()

    # 2. Attempt DELETE -> must be rejected by trigger
    with pytest.raises(Exception) as exc_delete:
        db_session.execute(
            delete(ReferenceSequenceAudit).where(ReferenceSequenceAudit.id == audit.id)
        )
        db_session.flush()
    assert "append-only" in str(exc_delete.value).lower()
    db_session.rollback()
