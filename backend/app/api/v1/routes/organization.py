from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AssetCategory, AssetNumberRule, Company, CompanyMembership, CostCenter, Department, Location, Role, Site
from app.audit import record_security_event
from app.schemas import (
    CompanySettingsUpdate,
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
    AssetNumberingRead,
    SiteCreate,
    SiteRead,
    SiteUpdate,
)
from app.services import create_company, get_company, get_scoped
from app.reference_service import (
    ALLOWED_NUMBER_SEPARATORS,
    PrefixImmutabilityError,
    ReferenceNumberService,
    SequenceNotFoundError,
)
from app.security import CurrentActor, actor_has_permission, current_actor, require_permission

router = APIRouter(tags=['organisation'], dependencies=[Depends(current_actor)])


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The record conflicts with existing company data') from exc


@router.get('/companies', response_model=list[CompanyRead])
def list_companies(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    if actor_has_permission(db, actor.user.id, None, 'company.read'):
        return db.scalars(select(Company).order_by(Company.name)).all()
    return db.scalars(
        select(Company)
        .join(CompanyMembership, CompanyMembership.company_id == Company.id)
        .where(
            CompanyMembership.user_id == actor.user.id,
            CompanyMembership.status == 'active',
            Company.is_active.is_(True),
        )
        .order_by(Company.name)
    ).all()


@router.post(
    '/companies',
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('system.companies.manage'))],
)
def add_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    try:
        return create_company(db, payload)
    except IntegrityError as exc:
        db.rollback()
        err_msg = str(exc).lower()
        if 'reference_number' in err_msg:
            raise HTTPException(status_code=409, detail='Company reference number already exists') from exc
        raise HTTPException(status_code=409, detail='Company code already exists') from exc


@router.get('/companies/{company_id}', response_model=CompanyRead, dependencies=[Depends(require_permission('company.read'))])
def read_company(company_id: UUID, db: Session = Depends(get_db)):
    return get_company(db, company_id)


@router.patch('/companies/{company_id}', response_model=CompanyRead, dependencies=[Depends(require_permission('company.update'))])
def edit_company(company_id: UUID, payload: CompanyUpdate, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    update_data = payload.model_dump(exclude_unset=True)
    if 'reference_number' in update_data and update_data['reference_number'] != company.reference_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Company reference number is system-generated and immutable.',
        )
    if 'code' in update_data and update_data['code'] != company.code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Company code is locked during normal company editing.',
        )
    for key, value in update_data.items():
        if key not in ('reference_number', 'code'):
            setattr(company, key, value)
    commit(db)
    db.refresh(company)
    return company


@router.get('/companies/{company_id}/settings', response_model=dict, dependencies=[Depends(require_permission('company.read'))])
def get_company_settings(company_id: UUID, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    return company.settings or {}


@router.put('/companies/{company_id}/settings', response_model=dict, dependencies=[Depends(require_permission('company.update'))])
def update_company_settings(
    company_id: UUID,
    payload: CompanySettingsUpdate,
    actor: CurrentActor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    # Tier 0 lock: serialize with concurrent return approvals
    company = db.scalar(
        select(Company)
        .where(Company.id == company_id)
        .with_for_update()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    settings_dict = dict(company.settings or {})
    prev_value = settings_dict.get('procurement_different_person_return_approval', True)
    new_value = payload.procurement_different_person_return_approval

    if new_value is not None:
        settings_dict['procurement_different_person_return_approval'] = new_value
        company.settings = settings_dict
        db.add(company)

        record_security_event(
            db,
            action="company.setting_changed",
            entity_type="Company",
            entity_id=str(company.id),
            actor_id=actor.user.id,
            company_id=company.id,
            changes={
                "setting_key": "procurement_different_person_return_approval",
                "previous_value": prev_value,
                "new_value": new_value,
                "reason": payload.reason,
            },
        )
        commit(db)
        db.refresh(company)

    return company.settings


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


@router.get('/companies/{company_id}/departments', response_model=list[DepartmentRead], dependencies=[Depends(require_permission('organization.read'))])
def list_departments(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, Department, company_id)


@router.post('/companies/{company_id}/departments', response_model=DepartmentRead, status_code=201, dependencies=[Depends(require_permission('organization.manage'))])
def add_department(company_id: UUID, payload: DepartmentCreate, db: Session = Depends(get_db)):
    return create_scoped(db, Department, company_id, payload)


@router.patch('/companies/{company_id}/departments/{department_id}', response_model=DepartmentRead, dependencies=[Depends(require_permission('organization.manage'))])
def edit_department(company_id: UUID, department_id: UUID, payload: DepartmentUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, Department, company_id, department_id, payload, 'Department')


@router.delete('/companies/{company_id}/departments/{department_id}', response_model=DepartmentRead, dependencies=[Depends(require_permission('organization.manage'))])
def deactivate_department(company_id: UUID, department_id: UUID, db: Session = Depends(get_db)):
    department = get_scoped(db, Department, company_id, department_id, 'Department')
    department.is_active = False
    commit(db)
    db.refresh(department)
    return department


@router.get('/companies/{company_id}/sites', response_model=list[SiteRead], dependencies=[Depends(require_permission('organization.read'))])
def list_sites(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, Site, company_id)


@router.post('/companies/{company_id}/sites', response_model=SiteRead, status_code=201, dependencies=[Depends(require_permission('organization.manage'))])
def add_site(company_id: UUID, payload: SiteCreate, db: Session = Depends(get_db)):
    return create_scoped(db, Site, company_id, payload, {'address': payload.address})


@router.patch('/companies/{company_id}/sites/{site_id}', response_model=SiteRead, dependencies=[Depends(require_permission('organization.manage'))])
def edit_site(company_id: UUID, site_id: UUID, payload: SiteUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, Site, company_id, site_id, payload, 'Site')


@router.get('/companies/{company_id}/sites/{site_id}/locations', response_model=list[LocationRead], dependencies=[Depends(require_permission('organization.read'))])
def list_locations(company_id: UUID, site_id: UUID, db: Session = Depends(get_db)):
    get_scoped(db, Site, company_id, site_id, 'Site')
    return db.scalars(select(Location).where(Location.company_id == company_id, Location.site_id == site_id).order_by(Location.name)).all()


@router.post('/companies/{company_id}/sites/{site_id}/locations', response_model=LocationRead, status_code=201, dependencies=[Depends(require_permission('organization.manage'))])
def add_location(company_id: UUID, site_id: UUID, payload: LocationCreate, db: Session = Depends(get_db)):
    get_company(db, company_id, active=True)
    get_scoped(db, Site, company_id, site_id, 'Site')
    record = Location(company_id=company_id, site_id=site_id, **payload.model_dump())
    db.add(record)
    commit(db)
    db.refresh(record)
    return record


@router.patch('/companies/{company_id}/sites/{site_id}/locations/{location_id}', response_model=LocationRead, dependencies=[Depends(require_permission('organization.manage'))])
def edit_location(company_id: UUID, site_id: UUID, location_id: UUID, payload: LocationUpdate, db: Session = Depends(get_db)):
    location = get_scoped(db, Location, company_id, location_id, 'Location')
    if location.site_id != site_id:
        raise HTTPException(status_code=404, detail='Location not found in this site')
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, key, value)
    commit(db)
    db.refresh(location)
    return location


@router.get('/companies/{company_id}/cost-centers', response_model=list[CostCenterRead], dependencies=[Depends(require_permission('organization.read'))])
def list_cost_centers(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, CostCenter, company_id)


@router.post('/companies/{company_id}/cost-centers', response_model=CostCenterRead, status_code=201, dependencies=[Depends(require_permission('organization.manage'))])
def add_cost_center(company_id: UUID, payload: CostCenterCreate, db: Session = Depends(get_db)):
    return create_scoped(db, CostCenter, company_id, payload)


@router.patch('/companies/{company_id}/cost-centers/{cost_center_id}', response_model=CostCenterRead, dependencies=[Depends(require_permission('organization.manage'))])
def edit_cost_center(company_id: UUID, cost_center_id: UUID, payload: CostCenterUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, CostCenter, company_id, cost_center_id, payload, 'Cost centre')


@router.get('/companies/{company_id}/categories', response_model=list[CategoryRead], dependencies=[Depends(require_permission('organization.read'))])
def list_categories(company_id: UUID, db: Session = Depends(get_db)):
    return list_scoped(db, AssetCategory, company_id)


@router.post('/companies/{company_id}/categories', response_model=CategoryRead, status_code=201, dependencies=[Depends(require_permission('organization.manage'))])
def add_category(company_id: UUID, payload: CategoryCreate, db: Session = Depends(get_db)):
    return create_scoped(db, AssetCategory, company_id, payload, {'description': payload.description})


@router.patch('/companies/{company_id}/categories/{category_id}', response_model=CategoryRead, dependencies=[Depends(require_permission('organization.manage'))])
def edit_category(company_id: UUID, category_id: UUID, payload: CategoryUpdate, db: Session = Depends(get_db)):
    return update_scoped(db, AssetCategory, company_id, category_id, payload, 'Asset category')


RETIRED_NUMBER_RULE_DETAIL = (
    'Legacy numbering rules are retired and cannot be created, modified, or deleted. '
    'Asset reference numbers are now centrally managed by ReferenceNumberService.'
)


def _asset_numbering_read(seq) -> AssetNumberingRead:
    nxt = seq.current_value + 1
    return AssetNumberingRead(
        prefix=seq.prefix,
        separator=seq.separator,
        padding=seq.padding,
        next_number=nxt,
        next_reference_preview=f'{seq.prefix}{seq.separator}{nxt:0{seq.padding}d}',
        issued_count=seq.current_value,
        is_locked=seq.current_value > 0,
        allowed_separators=list(ALLOWED_NUMBER_SEPARATORS),
        lock_note=(
            'References have been issued; prefix, separator and padding are locked. '
            'Changes require the controlled support procedure with an audit ticket.'
            if seq.current_value > 0 else None
        ),
    )


@router.get('/companies/{company_id}/asset-numbering', response_model=AssetNumberingRead, dependencies=[Depends(require_permission('organization.read'))])
def get_asset_numbering(company_id: UUID, db: Session = Depends(get_db)):
    """Read-only access to the authoritative persisted asset numbering configuration."""
    get_company(db, company_id)
    try:
        return _asset_numbering_read(ReferenceNumberService.get_asset_sequence(db, company_id))
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/companies/{company_id}/asset-numbering/align', response_model=AssetNumberingRead, dependencies=[Depends(require_permission('organization.manage'))])
def align_company_numbering(
    company_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    """Explicitly aligns unissued legacy default sequences (current_value == 0) of an active company
    to the company-code convention, recording one per-sequence AuditEvent per sequence changed.
    """
    get_company(db, company_id)
    try:
        ReferenceNumberService.align_unissued_company_sequences(
            db,
            company_id,
            performed_by_id=actor.user.id,
            allow_inactive_company=False,
            commit=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _asset_numbering_read(ReferenceNumberService.get_asset_sequence(db, company_id))


@router.post('/companies/{company_id}/asset-numbering/admin-align', response_model=AssetNumberingRead)
def admin_align_company_numbering(
    company_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    """System Administrator procedure to align unissued legacy default sequences for any company
    (including an inactive company while preserving its inactive status).
    """
    if not (
        actor_has_permission(db, actor.user.id, None, 'system.companies.manage')
        and actor_has_permission(db, actor.user.id, None, 'organization.manage')
    ):
        record_security_event(
            db,
            action='authz.denied',
            entity_type='API',
            entity_id=request.url.path,
            actor_id=actor.user.id,
            company_id=company_id,
            outcome='denied',
            changes={'permission': 'system.companies.manage'},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='System Administrator permission required')

    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Company not found')

    try:
        ReferenceNumberService.align_unissued_company_sequences(
            db,
            company_id,
            performed_by_id=actor.user.id,
            allow_inactive_company=True,
            commit=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _asset_numbering_read(ReferenceNumberService.get_asset_sequence(db, company_id))


@router.put('/companies/{company_id}/asset-numbering', response_model=AssetNumberingRead, dependencies=[Depends(require_permission('organization.manage'))])
def put_asset_numbering(company_id: UUID, payload: NumberRuleWrite, db: Session = Depends(get_db)):
    """Configure asset numbering before the first reference is issued; locked afterwards."""
    get_company(db, company_id)
    try:
        seq, before = ReferenceNumberService.configure_asset_sequence(
            db, company_id, payload.prefix, payload.separator, payload.padding
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PrefixImmutabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_security_event(
        db,
        action='updated',
        entity_type='AssetNumbering',
        entity_id=str(seq.id),
        company_id=company_id,
        changes={'before': before, 'after': {'prefix': seq.prefix, 'separator': seq.separator, 'padding': seq.padding}},
    )
    db.commit()
    db.refresh(seq)
    return _asset_numbering_read(seq)


@router.get('/companies/{company_id}/numbering-rules', response_model=list[NumberRuleRead], dependencies=[Depends(require_permission('organization.read'))])
def list_number_rules(company_id: UUID, db: Session = Depends(get_db)):
    """
    Read-only access to legacy AssetNumberRule records for backward compatibility.
    Configuration is non-authoritative; ReferenceNumberService is the active reference allocator.
    """
    get_company(db, company_id)
    return db.scalars(
        select(AssetNumberRule).where(AssetNumberRule.company_id == company_id).order_by(AssetNumberRule.category_id)
    ).all()


@router.post('/companies/{company_id}/numbering-rules', status_code=status.HTTP_409_CONFLICT, dependencies=[Depends(require_permission('organization.manage'))])
def create_number_rule(
    company_id: UUID,
    payload: NumberRuleWrite | None = None,
    category_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=RETIRED_NUMBER_RULE_DETAIL,
    )


@router.put('/companies/{company_id}/numbering-rules', status_code=status.HTTP_409_CONFLICT, dependencies=[Depends(require_permission('organization.manage'))])
def put_number_rule(
    company_id: UUID,
    payload: NumberRuleWrite | None = None,
    category_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=RETIRED_NUMBER_RULE_DETAIL,
    )


@router.delete('/companies/{company_id}/numbering-rules', status_code=status.HTTP_409_CONFLICT, dependencies=[Depends(require_permission('organization.manage'))])
def delete_number_rule(
    company_id: UUID,
    category_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=RETIRED_NUMBER_RULE_DETAIL,
    )


@router.delete('/companies/{company_id}/numbering-rules/{rule_id}', status_code=status.HTTP_409_CONFLICT, dependencies=[Depends(require_permission('organization.manage'))])
def delete_number_rule_by_id(
    company_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=RETIRED_NUMBER_RULE_DETAIL,
    )
