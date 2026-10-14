from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AssetCategory, AssetNumberRule, Company, CostCenter, Department, Location, Site
from app.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    CompanyCreate,
    CompanyRead,
    CompanyUpdate,
    CostCenterCreate,
    CostCenterRead,
    CostCenterUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    LocationCreate,
    LocationRead,
    LocationUpdate,
    MasterCreate,
    NumberRuleRead,
    NumberRuleWrite,
    SiteCreate,
    SiteRead,
    SiteUpdate,
)
from app.services import create_company, get_company, get_scoped

router = APIRouter(tags=['organisation'])


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The record conflicts with existing company data') from exc


@router.get('/companies', response_model=list[CompanyRead])
def list_companies(db: Session = Depends(get_db)):
    return db.scalars(select(Company).order_by(Company.name)).all()


@router.post('/companies', response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def add_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    try:
        return create_company(db, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Company code already exists') from exc


@router.get('/companies/{company_id}', response_model=CompanyRead)
def read_company(company_id: UUID, db: Session = Depends(get_db)):
    return get_company(db, company_id)


@router.patch('/companies/{company_id}', response_model=CompanyRead)
def edit_company(company_id: UUID, payload: CompanyUpdate, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, key, value)
    commit(db)
    db.refresh(company)
    return company


def list_scoped(db: Session, model, company_id: UUID):
    get_company(db, company_id)
    return db.scalars(select(model).where(model.company_id == company_id).order_by(model.name)).all()


def create_scoped(db: Session, model, company_id: UUID, payload: MasterCreate, extra: dict | None = None):
    get_company(db, company_id, active=True)
    excluded = set(extra or {})
    record = model(company_id=company_id, **payload.model_dump(exclude=excluded), **(extra or {}))
    db.add(record)
    commit(db)
    db.refresh(record)
    return record


def update_scoped(db: Session, model, company_id: UUID, item_id: UUID, payload, label: str):
    record = get_scoped(db, model, company_id, item_id, label)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    commit(db)
    db.refresh(record)
    return record


@router.get('/companies/{company_id}/departments', response_model=list[DepartmentRead])
def list_departments(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, Department, company_id)


@router.post('/companies/{company_id}/departments', response_model=DepartmentRead, status_code=201)
def add_department(company_id: UUID, payload: DepartmentCreate, db: Session = Depends(get_db)):
    return create_scoped(db, Department, company_id, payload)


@router.patch('/companies/{company_id}/departments/{department_id}', response_model=DepartmentRead)
def edit_department(company_id: UUID, department_id: UUID, payload: DepartmentUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, Department, company_id, department_id, payload, 'Department')


@router.delete('/companies/{company_id}/departments/{department_id}', response_model=DepartmentRead)
def deactivate_department(company_id: UUID, department_id: UUID, db: Session = Depends(get_db)):
    department = get_scoped(db, Department, company_id, department_id, 'Department')
    department.is_active = False
    commit(db)
    db.refresh(department)
    return department


@router.get('/companies/{company_id}/sites', response_model=list[SiteRead])
def list_sites(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, Site, company_id)


@router.post('/companies/{company_id}/sites', response_model=SiteRead, status_code=201)
def add_site(company_id: UUID, payload: SiteCreate, db: Session = Depends(get_db)):
    return create_scoped(db, Site, company_id, payload, {'address': payload.address})


@router.patch('/companies/{company_id}/sites/{site_id}', response_model=SiteRead)
def edit_site(company_id: UUID, site_id: UUID, payload: SiteUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, Site, company_id, site_id, payload, 'Site')


@router.get('/companies/{company_id}/sites/{site_id}/locations', response_model=list[LocationRead])
def list_locations(company_id: UUID, site_id: UUID, db: Session = Depends(get_db)):
    get_scoped(db, Site, company_id, site_id, 'Site')
    return db.scalars(select(Location).where(Location.company_id == company_id, Location.site_id == site_id).order_by(Location.name)).all()


@router.post('/companies/{company_id}/sites/{site_id}/locations', response_model=LocationRead, status_code=201)
def add_location(company_id: UUID, site_id: UUID, payload: LocationCreate, db: Session = Depends(get_db)):
    get_company(db, company_id, active=True)
    get_scoped(db, Site, company_id, site_id, 'Site')
    record = Location(company_id=company_id, site_id=site_id, **payload.model_dump())
    db.add(record)
    commit(db)
    db.refresh(record)
    return record


@router.patch('/companies/{company_id}/sites/{site_id}/locations/{location_id}', response_model=LocationRead)
def edit_location(company_id: UUID, site_id: UUID, location_id: UUID, payload: LocationUpdate, db: Session = Depends(get_db)):
    location = get_scoped(db, Location, company_id, location_id, 'Location')
    if location.site_id != site_id:
        raise HTTPException(status_code=404, detail='Location not found in this site')
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, key, value)
    commit(db)
    db.refresh(location)
    return location


@router.get('/companies/{company_id}/cost-centers', response_model=list[CostCenterRead])
def list_cost_centers(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, CostCenter, company_id)


@router.post('/companies/{company_id}/cost-centers', response_model=CostCenterRead, status_code=201)
def add_cost_center(company_id: UUID, payload: CostCenterCreate, db: Session = Depends(get_db)):
    return create_scoped(db, CostCenter, company_id, payload)


@router.patch('/companies/{company_id}/cost-centers/{cost_center_id}', response_model=CostCenterRead)
def edit_cost_center(company_id: UUID, cost_center_id: UUID, payload: CostCenterUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, CostCenter, company_id, cost_center_id, payload, 'Cost centre')


@router.get('/companies/{company_id}/categories', response_model=list[CategoryRead])
def list_categories(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, AssetCategory, company_id)


@router.post('/companies/{company_id}/categories', response_model=CategoryRead, status_code=201)
def add_category(company_id: UUID, payload: CategoryCreate, db: Session = Depends(get_db)):
    return create_scoped(db, AssetCategory, company_id, payload, {'description': payload.description})


@router.patch('/companies/{company_id}/categories/{category_id}', response_model=CategoryRead)
def edit_category(company_id: UUID, category_id: UUID, payload: CategoryUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, AssetCategory, company_id, category_id, payload, 'Asset category')


@router.get('/companies/{company_id}/numbering-rules', response_model=list[NumberRuleRead])
def list_number_rules(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    return db.scalars(
        select(AssetNumberRule).where(AssetNumberRule.company_id == company_id).order_by(AssetNumberRule.category_id)
    ).all()


@router.put('/companies/{company_id}/numbering-rules', response_model=NumberRuleRead)
def put_number_rule(
    company_id: UUID,
    payload: NumberRuleWrite,
    category_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id, active=True)
    if category_id is not None:
        get_scoped(db, AssetCategory, company_id, category_id, 'Asset category')
    rule = db.scalar(
        select(AssetNumberRule).where(
            AssetNumberRule.company_id == company_id,
            AssetNumberRule.category_id == category_id if category_id is not None else AssetNumberRule.category_id.is_(None),
        )
    )
    if rule is None:
        rule = AssetNumberRule(company_id=company_id, category_id=category_id, next_value=1, **payload.model_dump())
        db.add(rule)
    else:
        rule.prefix = payload.prefix
        rule.separator = payload.separator
        rule.padding = payload.padding
    commit(db)
    db.refresh(rule)
    return rule
