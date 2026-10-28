from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.audit import record_security_event
from app.database import get_db
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetDepartmentUsage,
    AssetHistory,
    CompanyMembership,
    Department,
    Location,
    User,
)
from app.schemas import (
    AssetCreate,
    AssetImportConfirmRequest,
    AssetImportConfirmResponse,
    AssetImportPreviewResponse,
    AssetRead,
    AssetUpdate,
    AssignmentCreate,
    AssignmentRead,
    AssignmentRecipientRead,
    HandoverCreate,
    HistoryRead,
    Page,
    ReturnCreate,
    TransferCreate,
    UsageCreate,
    UsageRead,
)
from app.services import create_asset, get_company, get_page, get_scoped, record_history, update_asset
from app.security import CurrentActor, current_actor, require_permission
from app.asset_import_service import confirm_import, generate_template, parse_and_validate_file

router = APIRouter(
    prefix='/companies/{company_id}/assets',
    tags=['assets'],
    dependencies=[Depends(current_actor)],
)


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The change conflicts with existing company data') from exc


def lock_asset(db: Session, company_id: UUID, asset_id: UUID) -> Asset:
    asset = db.scalar(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id == asset_id)
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found')
    return asset


def active_assignment(db: Session, asset_id: UUID) -> AssetAssignment | None:
    return db.scalar(
        select(AssetAssignment).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.status == 'active',
        )
    )


def validate_recipient(db: Session, company_id: UUID, recipient_id: UUID) -> User:
    recipient = db.scalar(
        select(User)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.user_id == recipient_id,
            CompanyMembership.status == 'active',
            User.is_active.is_(True),
        )
    )
    if recipient is None:
        raise HTTPException(status_code=422, detail='Recipient must be an active user in this company')
    return recipient


def validate_assignment_destination(
    db: Session,
    company_id: UUID,
    department_id: UUID | None,
    location_id: UUID | None,
) -> Location | None:
    if department_id is not None:
        department = get_scoped(db, Department, company_id, department_id, 'Department')
        if not department.is_active:
            raise HTTPException(status_code=422, detail='Responsible department is inactive')
    location = None
    if location_id is not None:
        location = get_scoped(db, Location, company_id, location_id, 'Location')
        if not location.is_active:
            raise HTTPException(status_code=422, detail='Physical location is inactive')
    return location


def save_assignment_change(db: Session, assignment: AssetAssignment) -> AssignmentRead:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The asset already has an active assignment or the destination conflicts with company data') from exc
    db.refresh(assignment)
    assignment.recipient = db.get(User, assignment.recipient_id)
    return AssignmentRead.model_validate(assignment)


@router.get('', response_model=Page[AssetRead], dependencies=[Depends(require_permission('asset.read'))])
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


@router.post('', response_model=AssetRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission('asset.create'))])
def register_asset(company_id: UUID, payload: AssetCreate, db: Session = Depends(get_db)):
    try:
        return create_asset(db, company_id, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Asset number or related company data conflicts with an existing record') from exc


@router.get(
    '/assignment-recipients',
    response_model=list[AssignmentRecipientRead],
    dependencies=[Depends(require_permission('asset.assignment.manage'))],
)
def list_assignment_recipients(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    recipients = db.execute(
        select(User.id, User.email)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == 'active',
            User.is_active.is_(True),
        )
        .order_by(User.email)
    ).all()
    return [{'id': recipient.id, 'email': recipient.email} for recipient in recipients]


@router.get('/import/template', dependencies=[Depends(require_permission('asset.create'))])
def download_asset_import_template(
    company_id: UUID,
    format: Literal['csv', 'xlsx'] = Query(default='csv'),
    db: Session = Depends(get_db),
):
    content, media_type, filename = generate_template(db, company_id, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.post(
    '/import/preview',
    response_model=AssetImportPreviewResponse,
)
def preview_bulk_asset_import(
    company_id: UUID,
    file: UploadFile = File(...),
    actor: CurrentActor = Depends(require_permission('asset.create')),
    db: Session = Depends(get_db),
):
    from app.asset_import_service import MAX_FILE_SIZE_BYTES
    file_bytes = file.file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f'File size exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB',
        )
    return parse_and_validate_file(
        db=db,
        company_id=company_id,
        actor_id=actor.user.id,
        file_bytes=file_bytes,
        filename=file.filename or 'upload.csv',
    )


@router.post(
    '/import/confirm',
    response_model=AssetImportConfirmResponse,
)
def confirm_bulk_asset_import(
    company_id: UUID,
    payload: AssetImportConfirmRequest,
    actor: CurrentActor = Depends(require_permission('asset.create')),
    db: Session = Depends(get_db),
):
    return confirm_import(
        db=db,
        company_id=company_id,
        actor_id=actor.user.id,
        preview_token=payload.preview_token,
    )


@router.get(
    '/lookup',
    response_model=AssetRead,
    dependencies=[Depends(require_permission('asset.read'))],
)
def lookup_asset(
    company_id: UUID,
    code: str = Query(..., min_length=1, max_length=120, description='Exact asset number or serial number to look up'),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)

    stripped_code = code.strip()
    if not stripped_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Lookup code cannot be empty or blank',
        )

    if any(ord(c) < 32 and c not in '\t\n\r' for c in code) or '\x00' in code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Lookup code contains invalid control characters',
        )

    # 1. Exact match on asset_number takes precedence
    asset = db.scalar(
        select(Asset).where(
            Asset.company_id == company_id,
            Asset.asset_number == stripped_code,
        )
    )

    # 2. If no asset_number match, fallback to exact match on serial_number
    if asset is None:
        asset = db.scalars(
            select(Asset).where(
                Asset.company_id == company_id,
                Asset.serial_number == stripped_code,
            ).order_by(Asset.created_at.desc(), Asset.id)
        ).first()

    # 3. If neither matches, return 404 without leaking cross-company data
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Asset not found in this company',
        )

    return asset


@router.get('/{asset_id}', response_model=AssetRead, dependencies=[Depends(require_permission('asset.read'))])
def read_asset(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    return get_scoped(db, Asset, company_id, asset_id, 'Asset')


@router.patch('/{asset_id}', response_model=AssetRead, dependencies=[Depends(require_permission('asset.update'))])
def edit_asset(company_id: UUID, asset_id: UUID, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = lock_asset(db, company_id, asset_id)
    changes = payload.model_dump(exclude_unset=True)
    current_assignment = active_assignment(db, asset.id)
    if current_assignment is not None:
        if 'custodian_name' in changes and changes['custodian_name'] != asset.custodian_name:
            raise HTTPException(status_code=409, detail='Change the custodian through the assignment transfer workflow')
        if 'status' in changes and changes['status'] != 'assigned':
            raise HTTPException(status_code=409, detail='Return or transfer the active assignment before changing asset status')
    elif changes.get('status') == 'assigned':
        raise HTTPException(status_code=422, detail='Use the assignment workflow to assign an asset')
    try:
        return update_asset(db, company_id, asset_id, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='Asset change conflicts with company data') from exc


@router.get(
    '/{asset_id}/assignments',
    response_model=list[AssignmentRead],
    dependencies=[Depends(require_permission('asset.read'))],
)
def list_asset_assignments(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    return db.scalars(
        select(AssetAssignment)
        .options(joinedload(AssetAssignment.recipient))
        .where(
            AssetAssignment.company_id == company_id,
            AssetAssignment.asset_id == asset_id,
        )
        .order_by(AssetAssignment.effective_date.desc(), AssetAssignment.created_at.desc())
    ).all()


@router.post(
    '/{asset_id}/assignments',
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_asset_assignment(
    company_id: UUID,
    asset_id: UUID,
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('asset.assignment.manage')),
):
    asset = lock_asset(db, company_id, asset_id)
    if asset.status != 'in_stock':
        raise HTTPException(status_code=409, detail='Only in-stock assets can be assigned')
    if active_assignment(db, asset.id) is not None:
        raise HTTPException(status_code=409, detail='The asset already has an active assignment')

    recipient = validate_recipient(db, company_id, payload.recipient_id)
    location = validate_assignment_destination(
        db, company_id, payload.responsible_department_id, payload.location_id
    )
    assignment = AssetAssignment(
        id=uuid4(),
        company_id=company_id,
        asset_id=asset.id,
        recipient_id=recipient.id,
        responsible_department_id=payload.responsible_department_id,
        location_id=payload.location_id,
        effective_date=payload.effective_date,
        notes=payload.notes,
        reference=payload.reference,
        recipient=recipient,
    )
    db.add(assignment)
    asset.status = 'assigned'
    asset.custodian_name = recipient.email
    if payload.responsible_department_id is not None:
        asset.responsible_department_id = payload.responsible_department_id
    if location is not None:
        asset.site_id = location.site_id
        asset.location_id = location.id
    record_history(db, asset, 'assignment_created', 'recipient_id', None, str(recipient.id))
    record_security_event(
        db,
        action='asset.assignment.created',
        entity_type='AssetAssignment',
        entity_id=str(assignment.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={'asset_id': str(asset.id), 'recipient_id': str(recipient.id)},
    )
    return save_assignment_change(db, assignment)


@router.post(
    '/{asset_id}/assignments/{assignment_id}/handover',
    response_model=AssignmentRead,
)
def record_asset_handover(
    company_id: UUID,
    asset_id: UUID,
    assignment_id: UUID,
    payload: HandoverCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('asset.assignment.manage')),
):
    asset = lock_asset(db, company_id, asset_id)
    assignment = db.scalar(
        select(AssetAssignment).where(
            AssetAssignment.company_id == company_id,
            AssetAssignment.asset_id == asset.id,
            AssetAssignment.id == assignment_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail='Assignment not found')
    if assignment.status != 'active':
        raise HTTPException(status_code=409, detail='Only active assignments can be handed over')
    if assignment.handover_date is not None:
        raise HTTPException(status_code=409, detail='Handover has already been recorded')
    if payload.handover_date < assignment.effective_date:
        raise HTTPException(status_code=422, detail='Handover date cannot be before the assignment effective date')

    assignment.handover_date = payload.handover_date
    assignment.handover_condition = payload.condition
    assignment.included_items = payload.included_items
    assignment.acknowledgement = payload.acknowledgement
    assignment.handover_notes = payload.notes
    record_history(db, asset, 'assignment_handover', 'recipient_id', None, str(assignment.recipient_id))
    record_security_event(
        db,
        action='asset.assignment.handover',
        entity_type='AssetAssignment',
        entity_id=str(assignment.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={'handover_date': payload.handover_date.isoformat()},
    )
    return save_assignment_change(db, assignment)


@router.post(
    '/{asset_id}/assignments/{assignment_id}/return',
    response_model=AssignmentRead,
)
def return_asset_assignment(
    company_id: UUID,
    asset_id: UUID,
    assignment_id: UUID,
    payload: ReturnCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('asset.assignment.manage')),
):
    asset = lock_asset(db, company_id, asset_id)
    assignment = db.scalar(
        select(AssetAssignment).where(
            AssetAssignment.company_id == company_id,
            AssetAssignment.asset_id == asset.id,
            AssetAssignment.id == assignment_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail='Assignment not found')
    if assignment.status != 'active':
        raise HTTPException(status_code=409, detail='Only active assignments can be returned')
    if payload.return_date < assignment.effective_date:
        raise HTTPException(status_code=422, detail='Return date cannot be before the assignment effective date')
    if assignment.handover_date is not None and payload.return_date < assignment.handover_date:
        raise HTTPException(status_code=422, detail='Return date cannot be before the handover date')

    assignment.status = 'returned'
    assignment.ended_at = datetime.now(timezone.utc)
    assignment.return_date = payload.return_date
    assignment.return_condition = payload.condition
    assignment.return_notes = payload.notes
    assignment.issue_details = payload.issue_details
    assignment.next_asset_status = payload.next_asset_status
    asset.status = payload.next_asset_status
    asset.custodian_name = None
    record_history(db, asset, 'assignment_returned', 'recipient_id', str(assignment.recipient_id), None)
    record_security_event(
        db,
        action='asset.assignment.returned',
        entity_type='AssetAssignment',
        entity_id=str(assignment.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={'return_date': payload.return_date.isoformat(), 'next_asset_status': payload.next_asset_status},
    )
    return save_assignment_change(db, assignment)


@router.post(
    '/{asset_id}/assignments/{assignment_id}/transfer',
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def transfer_asset_assignment(
    company_id: UUID,
    asset_id: UUID,
    assignment_id: UUID,
    payload: TransferCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('asset.assignment.manage')),
):
    asset = lock_asset(db, company_id, asset_id)
    previous = db.scalar(
        select(AssetAssignment).where(
            AssetAssignment.company_id == company_id,
            AssetAssignment.asset_id == asset.id,
            AssetAssignment.id == assignment_id,
        )
    )
    if previous is None:
        raise HTTPException(status_code=404, detail='Assignment not found')
    if previous.status != 'active':
        raise HTTPException(status_code=409, detail='Only active assignments can be transferred')
    if payload.effective_date < previous.effective_date:
        raise HTTPException(status_code=422, detail='Transfer date cannot be before the current assignment effective date')
    if previous.handover_date is not None and payload.effective_date < previous.handover_date:
        raise HTTPException(status_code=422, detail='Transfer date cannot be before the handover date')

    recipient = validate_recipient(db, company_id, payload.recipient_id)
    department_id = (
        payload.responsible_department_id
        if 'responsible_department_id' in payload.model_fields_set
        else previous.responsible_department_id
    )
    location_id = payload.location_id or previous.location_id
    location = validate_assignment_destination(db, company_id, department_id, location_id)
    now = datetime.now(timezone.utc)
    previous.status = 'transferred'
    previous.ended_at = now
    previous.transfer_reason = payload.reason
    next_assignment = AssetAssignment(
        id=uuid4(),
        company_id=company_id,
        asset_id=asset.id,
        recipient_id=recipient.id,
        responsible_department_id=department_id,
        location_id=location_id,
        effective_date=payload.effective_date,
        status='active',
        reference=payload.reference,
        handover_date=payload.effective_date,
        handover_condition=payload.condition,
        included_items=payload.included_items,
        acknowledgement=payload.acknowledgement,
        handover_notes=payload.notes,
        previous_assignment_id=previous.id,
        recipient=recipient,
    )
    db.add(next_assignment)
    asset.custodian_name = recipient.email
    if department_id is not None:
        asset.responsible_department_id = department_id
    if location is not None:
        asset.site_id = location.site_id
        asset.location_id = location.id
    record_history(
        db,
        asset,
        'assignment_transferred',
        'recipient_id',
        str(previous.recipient_id),
        str(recipient.id),
    )
    record_security_event(
        db,
        action='asset.assignment.transferred',
        entity_type='AssetAssignment',
        entity_id=str(next_assignment.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'asset_id': str(asset.id),
            'previous_assignment_id': str(previous.id),
            'previous_recipient_id': str(previous.recipient_id),
            'recipient_id': str(recipient.id),
            'effective_date': payload.effective_date.isoformat(),
            'reason': payload.reason,
        },
    )
    return save_assignment_change(db, next_assignment)


@router.get('/{asset_id}/usages', response_model=list[UsageRead], dependencies=[Depends(require_permission('asset.read'))])
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


@router.post('/{asset_id}/usages', response_model=UsageRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission('asset.usage.manage'))])
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


@router.post('/{asset_id}/usages/{usage_id}/end', response_model=UsageRead, dependencies=[Depends(require_permission('asset.usage.manage'))])
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


@router.get('/{asset_id}/history', response_model=list[HistoryRead], dependencies=[Depends(require_permission('asset.history.read'))])
def list_asset_history(company_id: UUID, asset_id: UUID, db: Session = Depends(get_db)):
    get_scoped(db, Asset, company_id, asset_id, 'Asset')
    return db.scalars(
        select(AssetHistory)
        .where(AssetHistory.company_id == company_id, AssetHistory.asset_id == asset_id)
        .order_by(AssetHistory.occurred_at.desc())
    ).all()
