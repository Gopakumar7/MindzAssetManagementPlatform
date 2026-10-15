from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.database import get_db
from app.models import Asset, AssetServiceContract, CompanyMembership, MaintenanceRequest, Supplier, User
from app.schemas import (
    AssetServiceContractCreate,
    AssetServiceContractRead,
    AssignmentRecipientRead,
    MaintenanceRequestCreate,
    MaintenanceRequestRead,
    MaintenanceRequestUpdate,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company

router = APIRouter(
    prefix='/companies/{company_id}',
    tags=['maintenance'],
    dependencies=[Depends(current_actor)],
)


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The service record conflicts with existing company data') from exc


def flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The service record conflicts with existing company data') from exc


def contract_read(contract: AssetServiceContract) -> AssetServiceContractRead:
    today = date.today()
    if contract.status == 'cancelled':
        coverage_status = 'cancelled'
    elif contract.start_date > today:
        coverage_status = 'upcoming'
    elif contract.end_date < today:
        coverage_status = 'expired'
    elif (contract.end_date - today).days <= 30:
        coverage_status = 'expiring_soon'
    else:
        coverage_status = 'active'
    return AssetServiceContractRead(
        **{
            key: getattr(contract, key)
            for key in (
                'id', 'company_id', 'asset_id', 'supplier_id', 'contract_type',
                'provider_name', 'reference_number', 'start_date', 'end_date',
                'coverage_description', 'support_contact', 'notes', 'status',
                'created_at',
            )
        },
        coverage_status=coverage_status,
    )


def maintenance_read(
    db: Session,
    request: MaintenanceRequest,
    asset_number: str | None = None,
) -> MaintenanceRequestRead:
    if asset_number is None:
        asset_number = db.scalar(
            select(Asset.asset_number).where(
                Asset.company_id == request.company_id,
                Asset.id == request.asset_id,
            )
        )
    requester = db.get(User, request.requester_id)
    assignee = db.get(User, request.assignee_id) if request.assignee_id else None
    return MaintenanceRequestRead(
        **{
            key: getattr(request, key)
            for key in (
                'id', 'company_id', 'asset_id', 'requester_id', 'assignee_id',
                'title', 'issue_description', 'priority', 'status', 'reported_date',
                'diagnosis', 'work_performed', 'resolution_notes', 'completed_date',
                'cost', 'created_at', 'updated_at',
            )
        },
        asset_number=asset_number or '',
        requester_email=requester.email if requester else '',
        assignee_email=assignee.email if assignee else None,
    )


def validate_active_member(db: Session, company_id: UUID, user_id: UUID) -> User:
    member = db.scalar(
        select(User)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.user_id == user_id,
            CompanyMembership.status == 'active',
            User.is_active.is_(True),
        )
    )
    if member is None:
        raise HTTPException(status_code=422, detail='Support user must be an active member of this company')
    return member


@router.get(
    '/maintenance-users',
    response_model=list[AssignmentRecipientRead],
    dependencies=[Depends(require_permission('maintenance.read'))],
)
def list_maintenance_users(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    return db.execute(
        select(User.id, User.email)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == 'active',
            User.is_active.is_(True),
        )
        .order_by(User.email)
    ).all()


@router.get(
    '/assets/{asset_id}/service-contracts',
    response_model=list[AssetServiceContractRead],
    dependencies=[Depends(require_permission('maintenance.read'))],
)
def list_service_contracts(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    asset = db.scalar(select(Asset.id).where(Asset.company_id == company_id, Asset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found')
    contracts = db.scalars(
        select(AssetServiceContract)
        .where(
            AssetServiceContract.company_id == company_id,
            AssetServiceContract.asset_id == asset_id,
        )
        .order_by(AssetServiceContract.start_date.desc(), AssetServiceContract.created_at.desc())
    ).all()
    return [contract_read(contract) for contract in contracts]


@router.post(
    '/assets/{asset_id}/service-contracts',
    response_model=AssetServiceContractRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('maintenance.manage'))],
)
def create_service_contract(
    company_id: UUID,
    asset_id: UUID,
    payload: AssetServiceContractCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('maintenance.manage')),
):
    get_company(db, company_id, active=True)
    asset = db.scalar(select(Asset).where(Asset.company_id == company_id, Asset.id == asset_id))
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found')

    supplier = None
    if payload.supplier_id is not None:
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.company_id == company_id,
                Supplier.id == payload.supplier_id,
                Supplier.is_active.is_(True),
            )
        )
        if supplier is None:
            raise HTTPException(status_code=422, detail='Supplier must be active in this company')
    elif asset.vendor_reference:
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.company_id == company_id,
                Supplier.code == asset.vendor_reference,
                Supplier.is_active.is_(True),
            )
        )

    contract = AssetServiceContract(
        company_id=company_id,
        asset_id=asset_id,
        supplier_id=supplier.id if supplier else None,
        contract_type=payload.contract_type,
        provider_name=(payload.provider_name or (supplier.name if supplier else None)),
        reference_number=payload.reference_number,
        start_date=payload.start_date,
        end_date=payload.end_date,
        coverage_description=payload.coverage_description,
        support_contact=payload.support_contact,
        notes=payload.notes,
    )
    db.add(contract)
    flush(db)
    record_security_event(
        db,
        action='service_contract_created',
        entity_type='AssetServiceContract',
        entity_id=str(contract.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'asset_id': str(asset_id),
            'contract_type': contract.contract_type,
            'supplier_id': str(contract.supplier_id) if contract.supplier_id else None,
            'reference_number': contract.reference_number,
            'start_date': contract.start_date.isoformat(),
            'end_date': contract.end_date.isoformat(),
        },
    )
    commit(db)
    db.refresh(contract)
    return contract_read(contract)


@router.patch(
    '/service-contracts/{contract_id}/cancel',
    response_model=AssetServiceContractRead,
    dependencies=[Depends(require_permission('maintenance.manage'))],
)
def cancel_service_contract(
    company_id: UUID,
    contract_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('maintenance.manage')),
):
    get_company(db, company_id, active=True)
    contract = db.scalar(
        select(AssetServiceContract)
        .where(
            AssetServiceContract.company_id == company_id,
            AssetServiceContract.id == contract_id,
        )
        .with_for_update()
    )
    if contract is None:
        raise HTTPException(status_code=404, detail='Service contract not found')
    if contract.status == 'cancelled':
        raise HTTPException(status_code=409, detail='Service contract is already cancelled')
    contract.status = 'cancelled'
    record_security_event(
        db,
        action='service_contract_cancelled',
        entity_type='AssetServiceContract',
        entity_id=str(contract.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={'status': {'old': 'active', 'new': 'cancelled'}},
    )
    commit(db)
    db.refresh(contract)
    return contract_read(contract)


@router.get(
    '/maintenance-requests',
    response_model=list[MaintenanceRequestRead],
    dependencies=[Depends(require_permission('maintenance.read'))],
)
def list_maintenance_requests(
    company_id: UUID,
    asset_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias='status'),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(MaintenanceRequest, Asset.asset_number)
        .join(Asset, (Asset.company_id == MaintenanceRequest.company_id) & (Asset.id == MaintenanceRequest.asset_id))
        .where(MaintenanceRequest.company_id == company_id)
        .order_by(MaintenanceRequest.created_at.desc(), MaintenanceRequest.id)
    )
    if asset_id is not None:
        query = query.where(MaintenanceRequest.asset_id == asset_id)
    if status_filter:
        if status_filter not in {'open', 'in_progress', 'resolved', 'closed'}:
            raise HTTPException(status_code=422, detail='Unsupported maintenance request status filter')
        query = query.where(MaintenanceRequest.status == status_filter)
    rows = db.execute(query).all()
    return [maintenance_read(db, request, asset_number) for request, asset_number in rows]


@router.post(
    '/maintenance-requests',
    response_model=MaintenanceRequestRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('maintenance.manage'))],
)
def create_maintenance_request(
    company_id: UUID,
    payload: MaintenanceRequestCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('maintenance.manage')),
):
    get_company(db, company_id, active=True)
    asset = db.scalar(
        select(Asset).where(Asset.company_id == company_id, Asset.id == payload.asset_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found in this company')
    if payload.assignee_id is not None:
        validate_active_member(db, company_id, payload.assignee_id)
    request = MaintenanceRequest(
        company_id=company_id,
        asset_id=asset.id,
        requester_id=actor.user.id,
        assignee_id=payload.assignee_id,
        title=payload.title,
        issue_description=payload.issue_description,
        priority=payload.priority,
        reported_date=payload.reported_date,
    )
    db.add(request)
    flush(db)
    record_security_event(
        db,
        action='maintenance_request_created',
        entity_type='MaintenanceRequest',
        entity_id=str(request.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'asset_id': str(asset.id),
            'title': request.title,
            'priority': request.priority,
            'reported_date': request.reported_date.isoformat(),
            'assignee_id': str(request.assignee_id) if request.assignee_id else None,
        },
    )
    commit(db)
    db.refresh(request)
    return maintenance_read(db, request, asset.asset_number)


@router.patch(
    '/maintenance-requests/{request_id}',
    response_model=MaintenanceRequestRead,
    dependencies=[Depends(require_permission('maintenance.manage'))],
)
def update_maintenance_request(
    company_id: UUID,
    request_id: UUID,
    payload: MaintenanceRequestUpdate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('maintenance.manage')),
):
    get_company(db, company_id, active=True)
    request = db.scalar(
        select(MaintenanceRequest)
        .where(
            MaintenanceRequest.company_id == company_id,
            MaintenanceRequest.id == request_id,
        )
        .with_for_update()
    )
    if request is None:
        raise HTTPException(status_code=404, detail='Maintenance request not found')

    updates = payload.model_dump(exclude_unset=True)
    if request.status == 'closed' and updates:
        raise HTTPException(status_code=409, detail='Closed maintenance requests are immutable')
    target_status = updates.get('status', request.status)
    if target_status != request.status:
        transitions = {
            'open': 'in_progress',
            'in_progress': 'resolved',
            'resolved': 'closed',
        }
        if transitions.get(request.status) != target_status:
            raise HTTPException(
                status_code=422,
                detail=f'Invalid maintenance transition: {request.status} to {target_status}',
            )
        if target_status == 'resolved':
            completed_date = updates.get('completed_date')
            resolution_notes = updates.get('resolution_notes', request.resolution_notes)
            if completed_date is None or not (resolution_notes or '').strip():
                raise HTTPException(
                    status_code=422,
                    detail='Completion date and resolution notes are required to resolve a request',
                )
    if 'completed_date' in updates and updates['completed_date'] is not None:
        if updates['completed_date'] < request.reported_date:
            raise HTTPException(status_code=422, detail='Completion date cannot precede the reported date')
    if updates.get('assignee_id') is not None:
        validate_active_member(db, company_id, updates['assignee_id'])

    changes = {}
    for field, value in updates.items():
        old_value = getattr(request, field)
        if old_value != value:
            changes[field] = {'old': str(old_value) if old_value is not None else None,
                              'new': str(value) if value is not None else None}
            setattr(request, field, value)

    if changes:
        record_security_event(
            db,
            action='maintenance_request_updated',
            entity_type='MaintenanceRequest',
            entity_id=str(request.id),
            actor_id=actor.user.id,
            company_id=company_id,
            changes=changes,
        )
    asset_number = db.scalar(
        select(Asset.asset_number).where(
            Asset.company_id == company_id,
            Asset.id == request.asset_id,
        )
    )
    commit(db)
    db.refresh(request)
    return maintenance_read(db, request, asset_number)
