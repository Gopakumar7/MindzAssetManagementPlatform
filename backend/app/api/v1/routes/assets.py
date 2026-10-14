from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, AssetCategory, AssetDepartmentUsage, AssetHistory, Department
from app.schemas import AssetCreate, AssetRead, AssetUpdate, HistoryRead, Page, UsageCreate, UsageRead
from app.services import create_asset, get_company, get_page, get_scoped, record_history, update_asset

router = APIRouter(prefix='/companies/{company_id}/assets', tags=['assets'])


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The change conflicts with existing company data') from exc


@router.get('', response_model=Page[AssetRead])
def list_assets(
    company_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = None,
    category_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias='status'),
    site_id: UUID | None = None,
    location_id: UUID | None = None,
    department_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = select(Asset).where(Asset.company_id == company_id)
    if search:
        term = f'%{search.strip()}%'
        query = query.where(or_(Asset.asset_number.ilike(term), Asset.serial_number.ilike(term)))
    if category_id is not None:
        query = query.where(Asset.category_id == category_id)
    if status_filter:
        query = query.where(Asset.status == status_filter)
    if site_id is not None:
        query = query.where(Asset.site_id == site_id)
    if location_id is not None:
        query = query.where(Asset.location_id == location_id)
    if department_id is not None:
        query = query.where(
            or_(
                Asset.responsible_department_id == department_id,
                Asset.id.in_(
                    select(AssetDepartmentUsage.asset_id).where(
                        AssetDepartmentUsage.company_id == company_id,
                        AssetDepartmentUsage.department_id == department_id,
                        AssetDepartmentUsage.ended_at.is_(None),
                    )
                ),
            )
        )
    query = query.order_by(Asset.created_at.desc(), Asset.id)
    return get_page(db, query, page, page_size)


@router.post('', response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def register_asset(company_id: UUID, payload: AssetCreate, db: Session = Depends(get_db)):
    try:
        return create_asset(db, company_id, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Asset number or related company data conflicts with an existing record') from exc


@router.get('/{asset_id}', response_model=AssetRead)
def read_asset(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    return get_scoped(db, Asset, company_id, asset_id, 'Asset')


@router.patch('/{asset_id}', response_model=AssetRead)
def edit_asset(company_id: UUID, asset_id: UUID, payload: AssetUpdate, db: Session = Depends(get_db)):
    try:
        return update_asset(db, company_id, asset_id, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Asset change conflicts with company data') from exc


@router.get('/{asset_id}/usages', response_model=list[UsageRead])
def list_asset_usages(
    company_id: UUID,
    asset_id: UUID,
    include_ended: bool = False,
    db: Session = Depends(get_db),
):
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    query = select(AssetDepartmentUsage).where(
        AssetDepartmentUsage.company_id == company_id,
        AssetDepartmentUsage.asset_id == asset_id,
    )
    if not include_ended:
        query = query.where(AssetDepartmentUsage.ended_at.is_(None))
    return db.scalars(query.order_by(AssetDepartmentUsage.started_at.desc())).all()


@router.post('/{asset_id}/usages', response_model=UsageRead, status_code=status.HTTP_201_CREATED)
def start_asset_usage(company_id: UUID, asset_id: UUID, payload: UsageCreate, db: Session = Depends(get_db)):
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    department = get_scoped(db, Department, company_id, payload.department_id, 'Department')
    if not department.is_active:
        raise HTTPException(status_code=422, detail='Department is inactive')
    existing = db.scalar(
        select(AssetDepartmentUsage.id).where(
            AssetDepartmentUsage.asset_id == asset_id,
            AssetDepartmentUsage.department_id == payload.department_id,
            AssetDepartmentUsage.ended_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail='This department already has an active usage relationship for the asset')
    usage = AssetDepartmentUsage(
        company_id=company_id,
        asset_id=asset.id,
        department_id=department.id,
        purpose=payload.purpose,
    )
    db.add(usage)
    record_history(db, asset, 'department_usage_started', 'department_id', None, str(department.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='An active usage relationship already exists') from exc
    db.refresh(usage)
    return usage


@router.post('/{asset_id}/usages/{usage_id}/end', response_model=UsageRead)
def end_asset_usage(company_id: UUID, asset_id: UUID, usage_id: UUID, db: Session = Depends(get_db)):
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    usage = db.scalar(
        select(AssetDepartmentUsage).where(
            AssetDepartmentUsage.company_id == company_id,
            AssetDepartmentUsage.asset_id == asset_id,
            AssetDepartmentUsage.id == usage_id,
        )
    )
    if usage is None:
        raise HTTPException(status_code=404, detail='Usage relationship not found')
    if usage.ended_at is not None:
        raise HTTPException(status_code=409, detail='Usage relationship has already ended')
    usage.ended_at = datetime.now(timezone.utc)
    record_history(db, asset, 'department_usage_ended', 'department_id', str(usage.department_id), None)
    commit(db)
    db.refresh(usage)
    return usage


@router.get('/{asset_id}/history', response_model=list[HistoryRead])
def list_asset_history(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    return db.scalars(
        select(AssetHistory)
        .where(AssetHistory.company_id == company_id, AssetHistory.asset_id == asset_id)
        .order_by(AssetHistory.occurred_at.desc())
    ).all()
