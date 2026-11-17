"""Goods return to vendor (GRR) service and lifecycle operations - Milestone 2E.3"""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.security import CurrentActor
from app.services import record_history
from app.models import (
    Asset,
    Company,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptReversal,
    GoodsReceiptReversalAsset,
    GoodsReceiptReversalLine,
    GoodsReturn,
    GoodsReturnAssetReservation,
    GoodsReturnLine,
    GoodsReturnWarehouseReceipt,
    AssetAssignment,
    AssetHistory,
    GoodsReturnWarehouseReceiptCorrection,
    GoodsReturnWarehouseReceiptLine,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.reference_service import ReferenceNumberService
from app.schemas import (
    GoodsReturnCancel,
    GoodsReturnCreate,
    GoodsReturnDispatch,
    GoodsReturnLineRead,
    GoodsReturnRead,
    GoodsReturnUpdate,
    GoodsReturnWarehouseReceiptCreate,
    GoodsReturnWarehouseReceiptLineRead,
    GoodsReturnWarehouseReceiptRead,
    ReturnEligibleAssetItem,
    WarehouseReceiptCorrectionCreate,
)


def get_return_eligible_assets(
    db: Session,
    company_id: UUID,
    reversal_id: UUID,
) -> list[ReturnEligibleAssetItem]:
    """Pre-flight diagnostic: lists reversible assets and active reservation status."""
    reversal = db.scalar(
        select(GoodsReceiptReversal).where(
            GoodsReceiptReversal.company_id == company_id,
            GoodsReceiptReversal.id == reversal_id,
        )
    )
    if reversal is None:
        raise HTTPException(status_code=404, detail="Goods receipt reversal not found")

    rev_assets = db.scalars(
        select(GoodsReceiptReversalAsset)
        .where(
            GoodsReceiptReversalAsset.company_id == company_id,
            GoodsReceiptReversalAsset.reversal_id == reversal.id,
        )
        .order_by(GoodsReceiptReversalAsset.asset_number)
    ).all()

    rev_lines = {
        rl.id: rl
        for rl in db.scalars(
            select(GoodsReceiptReversalLine).where(
                GoodsReceiptReversalLine.company_id == company_id,
                GoodsReceiptReversalLine.reversal_id == reversal.id,
            )
        ).all()
    }

    grn_lines = {
        gl.id: gl
        for gl in db.scalars(
            select(GoodsReceiptLine).where(
                GoodsReceiptLine.company_id == company_id,
                GoodsReceiptLine.goods_receipt_id == reversal.goods_receipt_id,
            )
        ).all()
    }

    # Query active reservations for these assets
    asset_ids = [ra.asset_id for ra in rev_assets]
    active_reservations = {
        res.asset_id: res
        for res in db.scalars(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.company_id == company_id,
                GoodsReturnAssetReservation.asset_id.in_(asset_ids),
                GoodsReturnAssetReservation.released_at.is_(None),
            )
        ).all()
    }

    # Query returns for reservation numbers
    return_ids = {res.goods_return_id for res in active_reservations.values()}
    return_numbers = {
        gr.id: gr.return_number
        for gr in db.scalars(
            select(GoodsReturn).where(
                GoodsReturn.company_id == company_id,
                GoodsReturn.id.in_(return_ids),
            )
        ).all()
    }

    # Query asset current statuses
    assets_by_id = {
        a.id: a
        for a in db.scalars(
            select(Asset).where(
                Asset.company_id == company_id,
                Asset.id.in_(asset_ids),
            )
        ).all()
    }

    results: list[ReturnEligibleAssetItem] = []
    for ra in rev_assets:
        asset = assets_by_id.get(ra.asset_id)
        active_res = active_reservations.get(ra.asset_id)
        is_reserved = active_res is not None

        # Lineage validations (Preserving & explicitly verifying 2E.2 application checks)
        rl = rev_lines.get(ra.reversal_line_id)
        gl = grn_lines.get(ra.goods_receipt_line_id) if rl else None

        is_eligible = True
        ineligibility_reason = None

        if not asset or asset.status != "reversed":
            is_eligible = False
            status_text = asset.status if asset else "missing"
            ineligibility_reason = f"Asset status is '{status_text}', expected 'reversed'"
        elif is_reserved:
            is_eligible = False
            ret_num = return_numbers.get(active_res.goods_return_id, "unknown")
            ineligibility_reason = f"Asset is actively reserved in Return {ret_num}"
        elif not rl or rl.goods_receipt_line_id != ra.goods_receipt_line_id:
            is_eligible = False
            ineligibility_reason = "Lineage error: Reversal line and reversal asset GRN line mismatch"
        elif not gl or rl.purchase_order_line_id != gl.purchase_order_line_id:
            is_eligible = False
            ineligibility_reason = "Lineage error: Reversal line PO line does not match GRN line"
        elif asset.goods_receipt_line_id != ra.goods_receipt_line_id:
            is_eligible = False
            ineligibility_reason = "Lineage error: Asset does not originate from reversal asset GRN line"

        results.append(
            ReturnEligibleAssetItem(
                goods_receipt_reversal_asset_id=ra.id,
                reversal_id=ra.reversal_id,
                reversal_line_id=ra.reversal_line_id,
                goods_receipt_line_id=ra.goods_receipt_line_id,
                asset_id=ra.asset_id,
                asset_number=ra.asset_number,
                serial_number=ra.serial_number,
                is_actively_reserved=is_reserved,
                active_reservation_return_id=active_res.goods_return_id if active_res else None,
                active_reservation_return_number=return_numbers.get(active_res.goods_return_id) if active_res else None,
                is_eligible=is_eligible,
                ineligibility_reason=ineligibility_reason,
            )
        )

    return results


def create_goods_return(
    db: Session,
    company_id: UUID,
    payload: GoodsReturnCreate,
    actor: CurrentActor,
) -> GoodsReturn:
    """Create draft GRR with allocated sequence number and active asset reservations."""
    # SAVEPOINT session hygiene: explicit runtime validation
    if bool(db.new or db.dirty or db.deleted):
        raise HTTPException(
            status_code=500,
            detail="Internal transaction state error: uncommitted session modifications exist prior to SAVEPOINT boundary.",
        )

    reversal = db.scalar(
        select(GoodsReceiptReversal).where(
            GoodsReceiptReversal.company_id == company_id,
            GoodsReceiptReversal.id == payload.goods_receipt_reversal_id,
        )
    )
    if reversal is None:
        raise HTTPException(status_code=404, detail="Goods receipt reversal not found")

    if not payload.lines:
        raise HTTPException(status_code=422, detail="At least one return line must be specified")

    requested_rev_asset_ids = [l.goods_receipt_reversal_asset_id for l in payload.lines]
    if len(requested_rev_asset_ids) != len(set(requested_rev_asset_ids)):
        raise HTTPException(status_code=422, detail="Duplicate reversal asset IDs in return request")

    rev_assets = db.scalars(
        select(GoodsReceiptReversalAsset).where(
            GoodsReceiptReversalAsset.company_id == company_id,
            GoodsReceiptReversalAsset.reversal_id == reversal.id,
            GoodsReceiptReversalAsset.id.in_(requested_rev_asset_ids),
        )
    ).all()
    rev_assets_by_id = {ra.id: ra for ra in rev_assets}

    if len(rev_assets_by_id) != len(requested_rev_asset_ids):
        missing = set(requested_rev_asset_ids) - set(rev_assets_by_id.keys())
        raise HTTPException(status_code=404, detail=f"Reversal asset(s) not found in this reversal: {missing}")

    rev_lines = {
        rl.id: rl
        for rl in db.scalars(
            select(GoodsReceiptReversalLine).where(
                GoodsReceiptReversalLine.company_id == company_id,
                GoodsReceiptReversalLine.reversal_id == reversal.id,
            )
        ).all()
    }

    grn_lines = {
        gl.id: gl
        for gl in db.scalars(
            select(GoodsReceiptLine).where(
                GoodsReceiptLine.company_id == company_id,
                GoodsReceiptLine.goods_receipt_id == reversal.goods_receipt_id,
            )
        ).all()
    }

    asset_ids = [ra.asset_id for ra in rev_assets]
    assets_by_id = {
        a.id: a
        for a in db.scalars(
            select(Asset).where(
                Asset.company_id == company_id,
                Asset.id.in_(asset_ids),
            )
        ).all()
    }

    # Validate asset status and 2E.2 lineage checks
    for ra in rev_assets:
        asset = assets_by_id.get(ra.asset_id)
        if not asset or asset.status != "reversed":
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{ra.asset_number}' has status '{asset.status if asset else 'missing'}', expected 'reversed'",
            )
        rl = rev_lines.get(ra.reversal_line_id)
        if not rl or rl.goods_receipt_line_id != ra.goods_receipt_line_id:
            raise HTTPException(status_code=422, detail="Lineage error: reversal line GRN line mismatch")
        gl = grn_lines.get(ra.goods_receipt_line_id)
        if not gl or rl.purchase_order_line_id != gl.purchase_order_line_id:
            raise HTTPException(status_code=422, detail="Lineage error: reversal line PO line mismatch")
        if asset.goods_receipt_line_id != ra.goods_receipt_line_id:
            raise HTTPException(status_code=422, detail="Lineage error: asset does not originate from reversal GRN line")

    # Fetch PO for supplier
    po = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.id == reversal.purchase_order_id,
        )
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    try:
        with db.begin_nested():
            # 1. Allocate sequence inside savepoint
            return_number = ReferenceNumberService.allocate(
                db,
                company_id=company_id,
                entity_type="goods_return",
                business_date=payload.return_date,
            )

            grr = GoodsReturn(
                id=uuid4(),
                company_id=company_id,
                return_number=return_number,
                supplier_id=po.supplier_id,
                purchase_order_id=po.id,
                original_goods_receipt_id=reversal.goods_receipt_id,
                goods_receipt_reversal_id=reversal.id,
                return_date=payload.return_date,
                status="draft",
                return_reason=payload.return_reason,
                vendor_reference=payload.vendor_reference,
                dispatch_reference=payload.dispatch_reference,
                transport_details=payload.transport_details,
                notes=payload.notes,
                policy_strict_approval_applied=None,  # Snapshot strictly at approval
                created_by_id=actor.user.id,
            )
            db.add(grr)
            db.flush()

            for line_item in payload.lines:
                ra = rev_assets_by_id[line_item.goods_receipt_reversal_asset_id]
                grr_line = GoodsReturnLine(
                    id=uuid4(),
                    company_id=company_id,
                    goods_return_id=grr.id,
                    goods_receipt_reversal_id=reversal.id,
                    goods_receipt_reversal_asset_id=ra.id,
                    goods_receipt_reversal_line_id=ra.reversal_line_id,
                    goods_receipt_line_id=ra.goods_receipt_line_id,
                    asset_id=ra.asset_id,
                    return_condition=line_item.return_condition,
                    notes=line_item.notes,
                )
                db.add(grr_line)

                reservation = GoodsReturnAssetReservation(
                    id=uuid4(),
                    company_id=company_id,
                    goods_return_id=grr.id,
                    asset_id=ra.asset_id,
                )
                db.add(reservation)

            # Pre-exit flush to force partial unique constraint check
            db.flush()
    except IntegrityError as exc:
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)
        diag = getattr(orig, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None) if diag else None

        is_reservation_conflict = (
            (sqlstate == "23505" and constraint_name == "uq_gr_asset_active_reservation")
            or ("uq_gr_asset_active_reservation" in str(exc))
            or ("goods_return_asset_reservations" in str(exc) and "asset_id" in str(exc))
        )
        if is_reservation_conflict:
            raise HTTPException(
                status_code=409,
                detail="One or more selected assets are already actively reserved in another Goods Return.",
            ) from exc
        raise

    record_security_event(
        db,
        action="goods_return.created",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "return_number": grr.return_number,
            "reversal_id": str(reversal.id),
            "line_count": len(payload.lines),
        },
    )

    return grr


def approve_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    actor: CurrentActor,
) -> GoodsReturn:
    """Approve draft GRR under Tier 0 Company row lock enforcing segregation of duties."""
    # Tier 0 lock: serialize with concurrent company settings modifications
    company = db.scalar(
        select(Company).where(Company.id == company_id).with_for_update()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # Tier 6 lock
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status != "draft":
        raise HTTPException(status_code=409, detail=f"Goods return in status '{grr.status}' cannot be approved")

    strict_approval = company.settings.get("procurement_different_person_return_approval", True)
    is_creator = grr.created_by_id == actor.user.id

    if strict_approval and is_creator:
        raise HTTPException(
            status_code=403,
            detail="Segregation of duties violation: Return approver must be different from the creator.",
        )

    grr.status = "approved"
    grr.approved_by_id = actor.user.id
    grr.approved_at = func.now()
    grr.policy_strict_approval_applied = strict_approval

    record_security_event(
        db,
        action="goods_return.approved",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "created_by_id": str(grr.created_by_id),
            "approved_by_id": str(actor.user.id),
            "self_approved": is_creator,
            "policy_override": (not strict_approval and is_creator),
            "strict_policy_enabled": strict_approval,
        },
    )

    return grr


def dispatch_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnDispatch,
    actor: CurrentActor,
) -> GoodsReturn:
    """Record carrier dispatch; transition assets reversed -> return_pending."""
    # Tier 6 lock
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status != "approved":
        raise HTTPException(status_code=409, detail=f"Goods return in status '{grr.status}' cannot be dispatched")

    lines = db.scalars(
        select(GoodsReturnLine).where(
            GoodsReturnLine.company_id == company_id,
            GoodsReturnLine.goods_return_id == grr.id,
        )
    ).all()
    asset_ids = sorted([line.asset_id for line in lines])

    # Tier 7 lock (monotonically by ID ASC)
    assets = db.scalars(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id.in_(asset_ids))
        .order_by(Asset.id)
        .with_for_update()
    ).all()

    for asset in assets:
        if asset.status != "reversed":
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset.asset_number}' has status '{asset.status}', expected 'reversed'",
            )
        asset.status = "return_pending"
        record_history(db, asset, "return_dispatched", "status", "reversed", "return_pending")

    grr.status = "dispatched"
    grr.dispatch_reference = payload.dispatch_reference
    if payload.transport_details:
        grr.transport_details = payload.transport_details
    if payload.notes:
        grr.notes = (grr.notes or "") + f"\n[Dispatch]: {payload.notes}"
    grr.dispatched_by_id = actor.user.id
    grr.dispatched_at = func.now()

    record_security_event(
        db,
        action="goods_return.dispatched",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "dispatch_reference": grr.dispatch_reference,
            "asset_count": len(assets),
        },
    )

    return grr


def create_warehouse_receipt(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnWarehouseReceiptCreate,
    actor: CurrentActor,
) -> GoodsReturnWarehouseReceipt:
    """Record physical warehouse receipt event; transition returned assets return_pending -> reversed."""
    # Tier 6 lock
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status not in ("dispatched", "partially_returned_to_warehouse"):
        raise HTTPException(
            status_code=409,
            detail=f"Goods return in status '{grr.status}' cannot receive physical warehouse returns",
        )

    all_grr_lines = {
        l.id: l
        for l in db.scalars(
            select(GoodsReturnLine).where(
                GoodsReturnLine.company_id == company_id,
                GoodsReturnLine.goods_return_id == grr.id,
            )
        ).all()
    }

    req_line_ids = [l.goods_return_line_id for l in payload.lines]
    if len(req_line_ids) != len(set(req_line_ids)):
        raise HTTPException(status_code=422, detail="Duplicate goods return lines in receipt payload")

    for lid in req_line_ids:
        if lid not in all_grr_lines:
            raise HTTPException(status_code=404, detail=f"Goods return line {lid} not found in this return")

    # Check for lines already received and not corrected
    already_received = db.scalars(
        select(GoodsReturnWarehouseReceiptLine).where(
            GoodsReturnWarehouseReceiptLine.company_id == company_id,
            GoodsReturnWarehouseReceiptLine.goods_return_line_id.in_(req_line_ids),
            GoodsReturnWarehouseReceiptLine.is_corrected.is_(False),
        )
    ).all()
    if already_received:
        raise HTTPException(
            status_code=409,
            detail=f"Line(s) {[str(r.goods_return_line_id) for r in already_received]} have already been received into the warehouse",
        )

    target_asset_ids = sorted([all_grr_lines[lid].asset_id for lid in req_line_ids])

    # Tier 7 lock (monotonically by ID ASC)
    assets = db.scalars(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id.in_(target_asset_ids))
        .order_by(Asset.id)
        .with_for_update()
    ).all()

    # Allocate receipt number (format: WR-{return_number}-{seq})
    receipt_count = (
        db.scalar(
            select(func.count(GoodsReturnWarehouseReceipt.id)).where(
                GoodsReturnWarehouseReceipt.company_id == company_id,
                GoodsReturnWarehouseReceipt.goods_return_id == grr.id,
            )
        )
        or 0
    )
    receipt_number = f"WR-{grr.return_number}-{receipt_count + 1:02d}"

    receipt = GoodsReturnWarehouseReceipt(
        id=uuid4(),
        company_id=company_id,
        goods_return_id=grr.id,
        receipt_number=receipt_number,
        receipt_date=payload.receipt_date,
        received_by_id=actor.user.id,
        warehouse_location_id=payload.warehouse_location_id,
        dispatch_reference=payload.dispatch_reference or grr.dispatch_reference,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(receipt)
    db.flush()

    assets_by_id = {a.id: a for a in assets}
    for item in payload.lines:
        grr_line = all_grr_lines[item.goods_return_line_id]
        asset = assets_by_id[grr_line.asset_id]

        if asset.status != "return_pending":
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset.asset_number}' has status '{asset.status}', expected 'return_pending'",
            )

        rcpt_line = GoodsReturnWarehouseReceiptLine(
            id=uuid4(),
            company_id=company_id,
            warehouse_receipt_id=receipt.id,
            goods_return_id=grr.id,
            goods_return_line_id=grr_line.id,
            asset_id=asset.id,
            condition_on_return=item.condition_on_return,
            notes=item.notes,
        )
        db.add(rcpt_line)

        # Transition asset return_pending -> reversed
        asset.status = "reversed"
        record_history(db, asset, "returned_to_warehouse", "status", "return_pending", "reversed")

        # Release reservation
        res = db.scalar(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.company_id == company_id,
                GoodsReturnAssetReservation.goods_return_id == grr.id,
                GoodsReturnAssetReservation.asset_id == asset.id,
                GoodsReturnAssetReservation.released_at.is_(None),
            )
        )
        if res:
            res.released_at = func.now()
            res.release_reason = "returned_to_warehouse"
            res.released_by_id = actor.user.id

    db.flush()

    # Recalculate document status
    uncorrected_received_count = (
        db.scalar(
            select(func.count(GoodsReturnWarehouseReceiptLine.id)).where(
                GoodsReturnWarehouseReceiptLine.company_id == company_id,
                GoodsReturnWarehouseReceiptLine.goods_return_id == grr.id,
                GoodsReturnWarehouseReceiptLine.is_corrected.is_(False),
            )
        )
        or 0
    )

    if uncorrected_received_count >= len(all_grr_lines):
        grr.status = "returned_to_warehouse"
    else:
        grr.status = "partially_returned_to_warehouse"

    record_security_event(
        db,
        action="goods_return.warehouse_receipt_created",
        entity_type="GoodsReturnWarehouseReceipt",
        entity_id=str(receipt.id),
        company_id=company_id,
        actor_id=actor.user.id,
        changes={
            "goods_return_id": str(grr.id),
            "receipt_number": receipt.receipt_number,
            "received_lines": len(payload.lines),
            "new_grr_status": grr.status,
        },
    )

    return receipt


def correct_warehouse_receipt_line(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    receipt_id: UUID,
    line_id: UUID,
    payload: WarehouseReceiptCorrectionCreate,
    actor: CurrentActor,
) -> GoodsReturnWarehouseReceiptLine:
    """Correct an erroneously recorded warehouse receipt line using an append-only ledger and reservation event."""
    # Tier 6 lock on GoodsReturn
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot correct warehouse receipt for goods return in '{grr.status}' status",
        )

    receipt_line = db.scalar(
        select(GoodsReturnWarehouseReceiptLine).where(
            GoodsReturnWarehouseReceiptLine.company_id == company_id,
            GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == receipt_id,
            GoodsReturnWarehouseReceiptLine.id == line_id,
        )
    )
    if receipt_line is None:
        raise HTTPException(status_code=404, detail="Warehouse receipt line not found")

    if receipt_line.is_corrected:
        raise HTTPException(status_code=409, detail="Warehouse receipt line has already been corrected")

    # Tier 7 lock on asset
    asset = db.scalar(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id == receipt_line.asset_id)
        .with_for_update(key_share=True)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    # 1. Asset status check: must currently be reversed
    if asset.status != "reversed":
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' has status '{asset.status}' and cannot be corrected; expected 'reversed' status",
        )

    # 2. Check no subsequent assignments exist or are active
    subsequent_assignment = db.scalar(
        select(AssetAssignment).where(
            AssetAssignment.company_id == company_id,
            AssetAssignment.asset_id == asset.id,
            or_(
                AssetAssignment.status == "active",
                AssetAssignment.created_at >= receipt_line.created_at,
            ),
        )
    )
    if subsequent_assignment is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' has subsequent assignment activity; warehouse receipt correction is rejected.",
        )

    # 3. Check no open or subsequent maintenance requests exist
    subsequent_maintenance = db.scalar(
        select(MaintenanceRequest).where(
            MaintenanceRequest.company_id == company_id,
            MaintenanceRequest.asset_id == asset.id,
            or_(
                MaintenanceRequest.status.in_(["open", "in_progress"]),
                MaintenanceRequest.created_at >= receipt_line.created_at,
            ),
        )
    )
    if subsequent_maintenance is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' has subsequent maintenance activity ({subsequent_maintenance.title}); warehouse receipt correction is rejected.",
        )

    # 4. Check that no competing active GRR reservation exists for this asset
    competing_reservation = db.scalar(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.company_id == company_id,
            GoodsReturnAssetReservation.asset_id == asset.id,
            GoodsReturnAssetReservation.released_at.is_(None),
        )
    )
    if competing_reservation is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' is actively reserved by Goods Return {competing_reservation.goods_return_id}; warehouse receipt correction is rejected.",
        )

    # 5. Check that no other active Goods Return lines reference this asset
    other_active_grr_line = db.scalar(
        select(GoodsReturnLine)
        .join(GoodsReturn, GoodsReturn.id == GoodsReturnLine.goods_return_id)
        .where(
            GoodsReturnLine.company_id == company_id,
            GoodsReturnLine.asset_id == asset.id,
            GoodsReturnLine.goods_return_id != grr.id,
            GoodsReturn.status.in_(["draft", "approved", "dispatched", "partially_returned_to_warehouse"]),
        )
    )
    if other_active_grr_line is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' is referenced by active Goods Return {other_active_grr_line.goods_return_id}; correction is rejected.",
        )

    # 6. Check that no subsequent non-receipt asset history exists
    subsequent_history = db.scalar(
        select(AssetHistory).where(
            AssetHistory.company_id == company_id,
            AssetHistory.asset_id == asset.id,
            AssetHistory.occurred_at > receipt_line.created_at,
            AssetHistory.event_type != "returned_to_warehouse",
        )
    )
    if subsequent_history is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset.asset_number}' has subsequent historical activity ('{subsequent_history.event_type}') after warehouse receipt; correction is rejected.",
        )

    try:
        with db.begin_nested():
            # Append-only reservation: NEVER mutate historical reservation rows. Create a NEW active reservation.
            new_reservation = GoodsReturnAssetReservation(
                id=uuid4(),
                company_id=company_id,
                goods_return_id=grr.id,
                asset_id=asset.id,
                reserved_at=func.now(),
                released_at=None,
                release_reason=None,
                released_by_id=None,
            )
            db.add(new_reservation)

            # Transition asset status reversed -> return_pending
            asset.status = "return_pending"
            record_history(db, asset, "warehouse_receipt_corrected", "status", "reversed", "return_pending")

            # Mark receipt line metadata as corrected (allowed by PostgreSQL trigger)
            receipt_line.is_corrected = True
            receipt_line.correction_reason = payload.correction_reason
            receipt_line.corrected_at = func.now()
            receipt_line.corrected_by_id = actor.user.id
            if payload.notes:
                receipt_line.notes = (receipt_line.notes or "") + f"\n[Correction]: {payload.notes}"

            # Create immutable correction ledger entry
            correction = GoodsReturnWarehouseReceiptCorrection(
                id=uuid4(),
                company_id=company_id,
                goods_return_id=grr.id,
                warehouse_receipt_id=receipt_id,
                warehouse_receipt_line_id=receipt_line.id,
                asset_id=asset.id,
                correction_reason=payload.correction_reason,
                notes=payload.notes,
                corrected_by_id=actor.user.id,
                corrected_at=func.now(),
                previous_asset_status="reversed",
                resulting_asset_status="return_pending",
                previous_reservation_state="released:returned_to_warehouse",
                reservation_outcome="reactivated:new_reservation",
                new_reservation_id=new_reservation.id,
            )
            db.add(correction)
            db.flush()
    except IntegrityError as exc:
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)
        constraint_name = None
        if hasattr(orig, "diag") and orig.diag:
            constraint_name = getattr(orig.diag, "constraint_name", None)
        is_reservation_conflict = (
            (sqlstate == "23505" and constraint_name == "uq_gr_asset_active_reservation")
            or ("uq_gr_asset_active_reservation" in str(exc))
            or ("goods_return_asset_reservations" in str(exc) and "asset_id" in str(exc))
        )
        if is_reservation_conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset.asset_number}' is actively reserved by another return process.",
            ) from exc
        raise

    # Recalculate document status
    all_grr_lines_count = (
        db.scalar(
            select(func.count(GoodsReturnLine.id)).where(
                GoodsReturnLine.company_id == company_id,
                GoodsReturnLine.goods_return_id == grr.id,
            )
        )
        or 0
    )
    uncorrected_received_count = (
        db.scalar(
            select(func.count(GoodsReturnWarehouseReceiptLine.id)).where(
                GoodsReturnWarehouseReceiptLine.company_id == company_id,
                GoodsReturnWarehouseReceiptLine.goods_return_id == grr.id,
                GoodsReturnWarehouseReceiptLine.is_corrected.is_(False),
            )
        )
        or 0
    )

    if uncorrected_received_count == 0:
        grr.status = "dispatched"
    elif uncorrected_received_count >= all_grr_lines_count:
        grr.status = "returned_to_warehouse"
    else:
        grr.status = "partially_returned_to_warehouse"

    record_security_event(
        db,
        action="goods_return.warehouse_receipt_corrected",
        entity_type="GoodsReturnWarehouseReceiptLine",
        entity_id=str(receipt_line.id),
        company_id=company_id,
        actor_id=actor.user.id,
        changes={
            "warehouse_receipt_id": str(receipt_id),
            "receipt_line_id": str(receipt_line.id),
            "goods_return_id": str(grr.id),
            "asset_id": str(asset.id),
            "correction_id": str(correction.id),
            "correction_reason": payload.correction_reason,
            "actor_user_id": str(actor.user.id),
            "previous_asset_status": "reversed",
            "resulting_asset_status": "return_pending",
            "previous_reservation_state": "released:returned_to_warehouse",
            "resulting_reservation_outcome": "reactivated:new_reservation",
            "new_reservation_id": str(new_reservation.id),
            "new_grr_status": grr.status,
        },
    )

    return receipt_line


def complete_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    actor: CurrentActor,
) -> GoodsReturn:
    """Acknowledge vendor receipt of remaining in-transit items; transition assets return_pending -> returned_to_vendor."""
    # Tier 6 lock
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status not in ("dispatched", "partially_returned_to_warehouse"):
        raise HTTPException(
            status_code=409,
            detail=f"Goods return in status '{grr.status}' cannot be completed",
        )

    # Locate return lines that have NOT been physically returned to warehouse
    all_lines = db.scalars(
        select(GoodsReturnLine).where(
            GoodsReturnLine.company_id == company_id,
            GoodsReturnLine.goods_return_id == grr.id,
        )
    ).all()

    returned_line_ids = set(
        db.scalars(
            select(GoodsReturnWarehouseReceiptLine.goods_return_line_id).where(
                GoodsReturnWarehouseReceiptLine.company_id == company_id,
                GoodsReturnWarehouseReceiptLine.goods_return_id == grr.id,
                GoodsReturnWarehouseReceiptLine.is_corrected.is_(False),
            )
        ).all()
    )

    remaining_lines = [l for l in all_lines if l.id not in returned_line_ids]
    if not remaining_lines:
        raise HTTPException(
            status_code=409,
            detail="All items in this return have already been received into the warehouse; cannot complete as vendor-accepted.",
        )

    remaining_asset_ids = sorted([l.asset_id for l in remaining_lines])

    # Tier 7 lock (monotonically by ID ASC)
    assets = db.scalars(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id.in_(remaining_asset_ids))
        .order_by(Asset.id)
        .with_for_update()
    ).all()

    for asset in assets:
        if asset.status != "return_pending":
            raise HTTPException(
                status_code=409,
                detail=f"Asset '{asset.asset_number}' has status '{asset.status}', expected 'return_pending'",
            )
        asset.status = "returned_to_vendor"
        record_history(db, asset, "returned_to_vendor", "status", "return_pending", "returned_to_vendor")

        res = db.scalar(
            select(GoodsReturnAssetReservation).where(
                GoodsReturnAssetReservation.company_id == company_id,
                GoodsReturnAssetReservation.goods_return_id == grr.id,
                GoodsReturnAssetReservation.asset_id == asset.id,
                GoodsReturnAssetReservation.released_at.is_(None),
            )
        )
        if res:
            res.released_at = func.now()
            res.release_reason = "fulfilled"
            res.released_by_id = actor.user.id

    grr.status = "completed"
    grr.completed_by_id = actor.user.id
    grr.completed_at = func.now()

    record_security_event(
        db,
        action="goods_return.completed",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "completed_lines": len(remaining_lines),
            "total_lines": len(all_lines),
        },
    )

    return grr


def cancel_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnCancel,
    actor: CurrentActor,
) -> GoodsReturn:
    """Cancel draft or approved GRR and release active reservations."""
    # Tier 6 lock
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")

    if grr.status not in ("draft", "approved"):
        raise HTTPException(
            status_code=409,
            detail=f"Goods return in status '{grr.status}' cannot be cancelled. Dispatched returns must be received via warehouse receipt.",
        )

    lines = db.scalars(
        select(GoodsReturnLine).where(
            GoodsReturnLine.company_id == company_id,
            GoodsReturnLine.goods_return_id == grr.id,
        )
    ).all()
    asset_ids = sorted([line.asset_id for line in lines])

    # Tier 7 lock
    assets = db.scalars(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id.in_(asset_ids))
        .order_by(Asset.id)
        .with_for_update()
    ).all()

    # Release reservations
    reservations = db.scalars(
        select(GoodsReturnAssetReservation).where(
            GoodsReturnAssetReservation.company_id == company_id,
            GoodsReturnAssetReservation.goods_return_id == grr.id,
            GoodsReturnAssetReservation.released_at.is_(None),
        )
    ).all()

    for res in reservations:
        res.released_at = func.now()
        res.release_reason = "cancelled"
        res.released_by_id = actor.user.id

    grr.status = "cancelled"
    grr.cancelled_by_id = actor.user.id
    grr.cancelled_at = func.now()
    grr.cancellation_reason = payload.cancellation_reason

    record_security_event(
        db,
        action="goods_return.cancelled",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "cancellation_reason": payload.cancellation_reason,
            "released_reservations": len(reservations),
        },
    )

    return grr


def goods_return_read(db: Session, grr: GoodsReturn) -> GoodsReturnRead:
    """Build GoodsReturnRead schema with populated lines."""
    lines = db.scalars(
        select(GoodsReturnLine)
        .where(
            GoodsReturnLine.company_id == grr.company_id,
            GoodsReturnLine.goods_return_id == grr.id,
        )
        .order_by(GoodsReturnLine.created_at)
    ).all()

    asset_ids = [line.asset_id for line in lines]
    assets_by_id = {}
    if asset_ids:
        assets = db.scalars(
            select(Asset).where(
                Asset.company_id == grr.company_id,
                Asset.id.in_(asset_ids),
            )
        ).all()
        assets_by_id = {a.id: a for a in assets}

    read_lines = []
    for line in lines:
        asset = assets_by_id.get(line.asset_id)
        read_lines.append(
            GoodsReturnLineRead(
                id=line.id,
                company_id=line.company_id,
                goods_return_id=line.goods_return_id,
                goods_receipt_reversal_id=line.goods_receipt_reversal_id,
                goods_receipt_reversal_asset_id=line.goods_receipt_reversal_asset_id,
                goods_receipt_reversal_line_id=line.goods_receipt_reversal_line_id,
                goods_receipt_line_id=line.goods_receipt_line_id,
                asset_id=line.asset_id,
                asset_number=asset.asset_number if asset else None,
                serial_number=asset.serial_number if asset else None,
                return_condition=line.return_condition,
                notes=line.notes,
                created_at=line.created_at,
            )
        )

    return GoodsReturnRead(
        id=grr.id,
        company_id=grr.company_id,
        return_number=grr.return_number,
        supplier_id=grr.supplier_id,
        purchase_order_id=grr.purchase_order_id,
        original_goods_receipt_id=grr.original_goods_receipt_id,
        goods_receipt_reversal_id=grr.goods_receipt_reversal_id,
        return_date=grr.return_date,
        status=grr.status,
        return_reason=grr.return_reason,
        vendor_reference=grr.vendor_reference,
        dispatch_reference=grr.dispatch_reference,
        transport_details=grr.transport_details,
        notes=grr.notes,
        policy_strict_approval_applied=grr.policy_strict_approval_applied,
        created_by_id=grr.created_by_id,
        created_at=grr.created_at,
        approved_by_id=grr.approved_by_id,
        approved_at=grr.approved_at,
        dispatched_by_id=grr.dispatched_by_id,
        dispatched_at=grr.dispatched_at,
        completed_by_id=grr.completed_by_id,
        completed_at=grr.completed_at,
        cancelled_by_id=grr.cancelled_by_id,
        cancelled_at=grr.cancelled_at,
        cancellation_reason=grr.cancellation_reason,
        lines=read_lines,
    )


def warehouse_receipt_read(db: Session, wr: GoodsReturnWarehouseReceipt) -> GoodsReturnWarehouseReceiptRead:
    """Build GoodsReturnWarehouseReceiptRead schema with populated lines."""
    lines = db.scalars(
        select(GoodsReturnWarehouseReceiptLine)
        .where(
            GoodsReturnWarehouseReceiptLine.company_id == wr.company_id,
            GoodsReturnWarehouseReceiptLine.warehouse_receipt_id == wr.id,
        )
        .order_by(GoodsReturnWarehouseReceiptLine.created_at)
    ).all()

    read_lines = [
        GoodsReturnWarehouseReceiptLineRead(
            id=line.id,
            company_id=line.company_id,
            warehouse_receipt_id=line.warehouse_receipt_id,
            goods_return_id=line.goods_return_id,
            goods_return_line_id=line.goods_return_line_id,
            asset_id=line.asset_id,
            condition_on_return=line.condition_on_return,
            notes=line.notes,
            is_corrected=line.is_corrected,
            correction_reason=line.correction_reason,
            corrected_at=line.corrected_at,
            corrected_by_id=line.corrected_by_id,
            created_at=line.created_at,
        )
        for line in lines
    ]

    return GoodsReturnWarehouseReceiptRead(
        id=wr.id,
        company_id=wr.company_id,
        goods_return_id=wr.goods_return_id,
        receipt_number=wr.receipt_number,
        receipt_date=wr.receipt_date,
        received_at=wr.received_at,
        received_by_id=wr.received_by_id,
        warehouse_location_id=wr.warehouse_location_id,
        dispatch_reference=wr.dispatch_reference,
        reason=wr.reason,
        notes=wr.notes,
        created_at=wr.created_at,
        lines=read_lines,
    )


def get_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
) -> GoodsReturn:
    """Retrieve goods return by ID."""
    grr = db.scalar(
        select(GoodsReturn).where(
            GoodsReturn.company_id == company_id,
            GoodsReturn.id == return_id,
        )
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")
    return grr


def list_goods_returns(
    db: Session,
    company_id: UUID,
    status: str | None = None,
    reversal_id: UUID | None = None,
    supplier_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[GoodsReturn]:
    """List goods returns for a company with filters."""
    stmt = select(GoodsReturn).where(GoodsReturn.company_id == company_id)
    if status:
        stmt = stmt.where(GoodsReturn.status == status)
    if reversal_id:
        stmt = stmt.where(GoodsReturn.goods_receipt_reversal_id == reversal_id)
    if supplier_id:
        stmt = stmt.where(GoodsReturn.supplier_id == supplier_id)
    stmt = stmt.order_by(GoodsReturn.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(stmt).all()


def list_warehouse_receipts(
    db: Session,
    company_id: UUID,
    return_id: UUID,
) -> list[GoodsReturnWarehouseReceipt]:
    """List all warehouse receipts for a return."""
    return db.scalars(
        select(GoodsReturnWarehouseReceipt)
        .where(
            GoodsReturnWarehouseReceipt.company_id == company_id,
            GoodsReturnWarehouseReceipt.goods_return_id == return_id,
        )
        .order_by(GoodsReturnWarehouseReceipt.received_at.asc())
    ).all()


def list_active_reservations(
    db: Session,
    company_id: UUID,
    return_id: UUID,
) -> list[GoodsReturnAssetReservation]:
    """List active reservations for a return."""
    return db.scalars(
        select(GoodsReturnAssetReservation)
        .where(
            GoodsReturnAssetReservation.company_id == company_id,
            GoodsReturnAssetReservation.goods_return_id == return_id,
            GoodsReturnAssetReservation.released_at.is_(None),
        )
    ).all()


def deselect_return_line(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    line_id: UUID,
    actor: CurrentActor,
) -> GoodsReturn:
    """Deselect line from draft return and release reservation ('deselected')."""
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")
    if grr.status != "draft":
        raise HTTPException(status_code=409, detail=f"Cannot remove line from return in status '{grr.status}'")

    line = db.scalar(
        select(GoodsReturnLine)
        .where(
            GoodsReturnLine.company_id == company_id,
            GoodsReturnLine.goods_return_id == grr.id,
            GoodsReturnLine.id == line_id,
        )
        .with_for_update()
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Return line not found")

    res = db.scalar(
        select(GoodsReturnAssetReservation)
        .where(
            GoodsReturnAssetReservation.company_id == company_id,
            GoodsReturnAssetReservation.goods_return_id == grr.id,
            GoodsReturnAssetReservation.asset_id == line.asset_id,
            GoodsReturnAssetReservation.released_at.is_(None),
        )
        .with_for_update()
    )
    if res:
        res.released_at = func.now()
        res.release_reason = "deselected"
        res.released_by_id = actor.user.id

    db.delete(line)
    db.flush()

    record_security_event(
        db,
        action="goods_return.line_deselected",
        entity_type="GoodsReturn",
        entity_id=str(grr.id),
        actor_id=actor.user.id,
        changes={
            "line_id": str(line.id),
            "asset_id": str(line.asset_id),
        },
    )
    return grr


def update_goods_return(
    db: Session,
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnUpdate,
    actor: CurrentActor,
) -> GoodsReturn:
    """Update draft goods return header fields."""
    grr = db.scalar(
        select(GoodsReturn)
        .where(GoodsReturn.company_id == company_id, GoodsReturn.id == return_id)
        .with_for_update()
    )
    if grr is None:
        raise HTTPException(status_code=404, detail="Goods return not found")
    if grr.status != "draft":
        raise HTTPException(status_code=409, detail=f"Cannot edit return in status '{grr.status}'")

    if payload.return_date is not None:
        grr.return_date = payload.return_date
    if payload.return_reason is not None:
        grr.return_reason = payload.return_reason
    if payload.vendor_reference is not None:
        grr.vendor_reference = payload.vendor_reference
    if payload.dispatch_reference is not None:
        grr.dispatch_reference = payload.dispatch_reference
    if payload.transport_details is not None:
        grr.transport_details = payload.transport_details
    if payload.notes is not None:
        grr.notes = payload.notes

    db.flush()
    return grr