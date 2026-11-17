"""API endpoints for Goods Return to Vendor (GRR) - Milestone 2E.3"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.goods_return_service import (
    approve_goods_return,
    cancel_goods_return,
    complete_goods_return,
    correct_warehouse_receipt_line,
    create_goods_return,
    create_warehouse_receipt,
    deselect_return_line,
    get_goods_return,
    get_return_eligible_assets,
    goods_return_read,
    list_goods_returns,
    list_warehouse_receipts,
    update_goods_return,
    warehouse_receipt_read,
)
from app.schemas import (
    GoodsReturnCancel,
    GoodsReturnCreate,
    GoodsReturnDispatch,
    GoodsReturnRead,
    GoodsReturnUpdate,
    GoodsReturnWarehouseReceiptCreate,
    GoodsReturnWarehouseReceiptRead,
    ReturnEligibleAssetItem,
    WarehouseReceiptCorrectionCreate,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company

router = APIRouter(tags=["goods-returns"], dependencies=[Depends(current_actor)])


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        orig = getattr(exc, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)
        constraint_name = None
        if hasattr(orig, "diag") and orig.diag:
            constraint_name = getattr(orig.diag, "constraint_name", None)
        if sqlstate == "23505" and constraint_name in (
            "uq_gr_asset_active_reservation",
            "uq_goods_return_lines_company_asset",
            "uq_gr_wr_lines_return_line",
            "uq_goods_returns_company_number",
            "uq_gr_wr_company_number",
        ):
            raise HTTPException(
                status_code=409,
                detail=f"A database integrity conflict occurred: {constraint_name}",
            ) from exc
        raise


@router.get(
    "/companies/{company_id}/goods-receipt-reversals/{reversal_id}/return-eligible-assets",
    response_model=list[ReturnEligibleAssetItem],
    dependencies=[Depends(require_permission("procurement.read"))],
)
def api_get_return_eligible_assets(
    company_id: UUID,
    reversal_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return get_return_eligible_assets(db, company_id=company_id, reversal_id=reversal_id)


@router.get(
    "/companies/{company_id}/goods-receipt-reversals/{reversal_id}/returns",
    response_model=list[GoodsReturnRead],
    dependencies=[Depends(require_permission("procurement.read"))],
)
def api_get_reversal_returns(
    company_id: UUID,
    reversal_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    returns = list_goods_returns(db, company_id=company_id, reversal_id=reversal_id)
    return [goods_return_read(db, grr) for grr in returns]


@router.post(
    "/companies/{company_id}/goods-returns",
    response_model=GoodsReturnRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_create_goods_return(
    company_id: UUID,
    payload: GoodsReturnCreate,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = create_goods_return(db, company_id=company_id, payload=payload, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.get(
    "/companies/{company_id}/goods-returns",
    response_model=list[GoodsReturnRead],
    dependencies=[Depends(require_permission("procurement.read"))],
)
def api_list_goods_returns(
    company_id: UUID,
    status: str | None = Query(None),
    reversal_id: UUID | None = Query(None),
    supplier_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    returns = list_goods_returns(
        db,
        company_id=company_id,
        status=status,
        reversal_id=reversal_id,
        supplier_id=supplier_id,
        limit=limit,
        offset=offset,
    )
    return [goods_return_read(db, grr) for grr in returns]


@router.get(
    "/companies/{company_id}/goods-returns/{return_id}",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.read"))],
)
def api_get_goods_return(
    company_id: UUID,
    return_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = get_goods_return(db, company_id=company_id, return_id=return_id)
    return goods_return_read(db, grr)


@router.patch(
    "/companies/{company_id}/goods-returns/{return_id}",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_update_goods_return(
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnUpdate,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = update_goods_return(db, company_id=company_id, return_id=return_id, payload=payload, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.delete(
    "/companies/{company_id}/goods-returns/{return_id}/lines/{line_id}",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_deselect_return_line(
    company_id: UUID,
    return_id: UUID,
    line_id: UUID,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = deselect_return_line(db, company_id=company_id, return_id=return_id, line_id=line_id, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/approve",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_approve_goods_return(
    company_id: UUID,
    return_id: UUID,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = approve_goods_return(db, company_id=company_id, return_id=return_id, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/dispatch",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_dispatch_goods_return(
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnDispatch,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    from app.goods_return_service import dispatch_goods_return
    get_company(db, company_id)
    grr = dispatch_goods_return(db, company_id=company_id, return_id=return_id, payload=payload, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/warehouse-receipts",
    response_model=GoodsReturnWarehouseReceiptRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_create_warehouse_receipt(
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnWarehouseReceiptCreate,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    wr = create_warehouse_receipt(db, company_id=company_id, return_id=return_id, payload=payload, actor=actor)
    commit(db)
    db.refresh(wr)
    return warehouse_receipt_read(db, wr)


@router.get(
    "/companies/{company_id}/goods-returns/{return_id}/warehouse-receipts",
    response_model=list[GoodsReturnWarehouseReceiptRead],
    dependencies=[Depends(require_permission("procurement.read"))],
)
def api_list_warehouse_receipts(
    company_id: UUID,
    return_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    receipts = list_warehouse_receipts(db, company_id=company_id, return_id=return_id)
    return [warehouse_receipt_read(db, wr) for wr in receipts]


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/warehouse-receipts/{receipt_id}/lines/{line_id}/correct",
    response_model=GoodsReturnWarehouseReceiptRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_correct_warehouse_receipt_line(
    company_id: UUID,
    return_id: UUID,
    receipt_id: UUID,
    line_id: UUID,
    payload: WarehouseReceiptCorrectionCreate,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select
    from app.models import GoodsReturnWarehouseReceipt

    get_company(db, company_id)
    correct_warehouse_receipt_line(
        db,
        company_id=company_id,
        return_id=return_id,
        receipt_id=receipt_id,
        line_id=line_id,
        payload=payload,
        actor=actor,
    )
    commit(db)
    wr = db.scalar(
        select(GoodsReturnWarehouseReceipt).where(
            GoodsReturnWarehouseReceipt.company_id == company_id,
            GoodsReturnWarehouseReceipt.id == receipt_id,
        )
    )
    return warehouse_receipt_read(db, wr)


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/complete",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_complete_goods_return(
    company_id: UUID,
    return_id: UUID,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = complete_goods_return(db, company_id=company_id, return_id=return_id, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)


@router.post(
    "/companies/{company_id}/goods-returns/{return_id}/cancel",
    response_model=GoodsReturnRead,
    dependencies=[Depends(require_permission("procurement.manage"))],
)
def api_cancel_goods_return(
    company_id: UUID,
    return_id: UUID,
    payload: GoodsReturnCancel,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    grr = cancel_goods_return(db, company_id=company_id, return_id=return_id, payload=payload, actor=actor)
    commit(db)
    db.refresh(grr)
    return goods_return_read(db, grr)
