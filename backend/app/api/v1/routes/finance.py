from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.finance_service import (
    adjust_financial_profile,
    calculate_depreciation_schedule,
    dispose_asset,
    get_or_create_financial,
    post_batch_depreciation,
    post_single_depreciation,
    update_financial_profile,
)
from app.models import Asset, AssetDepreciationEntry, AssetDisposal, AssetFinancial
from app.schemas import (
    AssetDepreciationEntryRead,
    AssetDisposalCreate,
    AssetDisposalRead,
    AssetFinancialAdjust,
    AssetFinancialCreate,
    AssetFinancialRead,
    AssetFinancialUpdate,
    BatchDepreciationRequest,
    BatchDepreciationResult,
    DepreciationPostRequest,
    DepreciationScheduleItem,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company, get_scoped

router = APIRouter(
    prefix='/companies/{company_id}',
    tags=['finance'],
    dependencies=[Depends(current_actor)],
)


@router.get(
    '/assets/{asset_id}/financial',
    response_model=AssetFinancialRead,
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_asset_financial(
    company_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    return get_or_create_financial(db, company_id, asset)


@router.put(
    '/assets/{asset_id}/financial',
    response_model=AssetFinancialRead,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def configure_asset_financial(
    company_id: UUID,
    asset_id: UUID,
    payload: AssetFinancialCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    existing = db.scalar(
        select(AssetFinancial).where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.asset_id == asset_id,
        )
    )
    if existing is None:
        financial = get_or_create_financial(db, company_id, asset, defaults=payload)
        db.commit()
        db.refresh(financial)
        return financial
    else:
        update_payload = AssetFinancialUpdate(**payload.model_dump())
        return update_financial_profile(db, company_id, asset_id, update_payload, actor.user.id)


@router.patch(
    '/assets/{asset_id}/financial',
    response_model=AssetFinancialRead,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def edit_asset_financial(
    company_id: UUID,
    asset_id: UUID,
    payload: AssetFinancialUpdate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    return update_financial_profile(db, company_id, asset_id, payload, actor.user.id)


@router.post(
    '/assets/{asset_id}/financial/adjust',
    response_model=AssetFinancialRead,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def adjust_financial(
    company_id: UUID,
    asset_id: UUID,
    payload: AssetFinancialAdjust,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    return adjust_financial_profile(db, company_id, asset_id, payload, actor.user.id)


@router.get(
    '/assets/{asset_id}/depreciation-schedule',
    response_model=list[DepreciationScheduleItem],
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_depreciation_schedule(
    company_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    return calculate_depreciation_schedule(db, company_id, asset_id)


@router.post(
    '/assets/{asset_id}/depreciation-entries',
    response_model=AssetDepreciationEntryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def post_depreciation(
    company_id: UUID,
    asset_id: UUID,
    payload: DepreciationPostRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    return post_single_depreciation(
        db,
        company_id=company_id,
        asset_id=asset_id,
        period=payload.period,
        user_id=actor.user.id,
        notes=payload.notes,
    )


@router.get(
    '/assets/{asset_id}/depreciation-entries',
    response_model=list[AssetDepreciationEntryRead],
    dependencies=[Depends(require_permission('finance.read'))],
)
def list_depreciation_entries(
    company_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    return db.scalars(
        select(AssetDepreciationEntry)
        .where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
        )
        .order_by(AssetDepreciationEntry.period.desc())
    ).all()


@router.post(
    '/depreciation-entries/batch',
    response_model=BatchDepreciationResult,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def batch_post_depreciation(
    company_id: UUID,
    payload: BatchDepreciationRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    return post_batch_depreciation(
        db,
        company_id=company_id,
        period=payload.period,
        user_id=actor.user.id,
        notes=payload.notes,
    )


@router.post(
    '/assets/{asset_id}/dispose',
    response_model=AssetDisposalRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('finance.manage'))],
)
def dispose(
    company_id: UUID,
    asset_id: UUID,
    payload: AssetDisposalCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('finance.manage')),
):
    get_company(db, company_id, active=True)
    return dispose_asset(
        db,
        company_id=company_id,
        asset_id=asset_id,
        payload=payload,
        user_id=actor.user.id,
    )


@router.get(
    '/assets/{asset_id}/disposal',
    response_model=AssetDisposalRead,
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_asset_disposal(
    company_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    disposal = db.scalar(
        select(AssetDisposal).where(
            AssetDisposal.company_id == company_id,
            AssetDisposal.asset_id == asset_id,
        )
    )
    if disposal is None:
        raise HTTPException(status_code=404, detail='Disposal record not found for this asset')
    return disposal

