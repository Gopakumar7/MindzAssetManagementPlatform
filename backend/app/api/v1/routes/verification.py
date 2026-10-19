from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetHistory,
    Company,
    Department,
    Location,
    Site,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
    VerificationUnregisteredAsset,
)
from app.schemas import (
    VerificationCampaignCreate,
    VerificationCampaignRead,
    VerificationCampaignReportItem,
    VerificationCampaignStatusTransition,
    VerificationCampaignUpdate,
    VerificationDashboardSummary,
    VerificationDiscrepancyRead,
    VerificationDiscrepancyReportItem,
    VerificationDiscrepancyResolveRequest,
    VerificationExpectedAssetRead,
    VerificationObservationCreate,
    VerificationObservationRead,
    VerificationUnregisteredAssetCreate,
    VerificationUnregisteredAssetRead,
    VerificationUnregisteredAssetRegister,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company, next_asset_number, record_history

router = APIRouter(
    prefix='/companies/{company_id}',
    tags=['verification'],
    dependencies=[Depends(current_actor)],
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_campaign_metrics(db: Session, company_id: UUID, campaign_id: UUID) -> dict:
    total_expected = db.scalar(
        select(func.count(VerificationExpectedAsset.id)).where(
            VerificationExpectedAsset.company_id == company_id,
            VerificationExpectedAsset.campaign_id == campaign_id,
        )
    ) or 0

    total_verified = db.scalar(
        select(func.count(VerificationObservation.id)).where(
            VerificationObservation.company_id == company_id,
            VerificationObservation.campaign_id == campaign_id,
        )
    ) or 0

    total_missing = db.scalar(
        select(func.count(VerificationObservation.id)).where(
            VerificationObservation.company_id == company_id,
            VerificationObservation.campaign_id == campaign_id,
            VerificationObservation.is_found.is_(False),
        )
    ) or 0

    total_discrepancies = db.scalar(
        select(func.count(VerificationDiscrepancy.id)).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
        )
    ) or 0

    total_unregistered = db.scalar(
        select(func.count(VerificationUnregisteredAsset.id)).where(
            VerificationUnregisteredAsset.company_id == company_id,
            VerificationUnregisteredAsset.campaign_id == campaign_id,
        )
    ) or 0

    total_unverified = max(0, total_expected - total_verified)
    pct = round((total_verified / total_expected * 100.0), 1) if total_expected > 0 else 0.0

    return {
        'total_expected': total_expected,
        'total_verified': total_verified,
        'total_unverified': total_unverified,
        'total_missing': total_missing,
        'total_discrepancies': total_discrepancies,
        'total_unregistered': total_unregistered,
        'completion_percentage': pct,
    }


@router.get(
    '/verification-campaigns',
    response_model=list[VerificationCampaignRead],
    dependencies=[Depends(require_permission('verification.read'))],
)
def list_campaigns(
    company_id: UUID,
    status_filter: str | None = Query(None, alias='status'),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = select(VerificationCampaign).where(VerificationCampaign.company_id == company_id)
    if status_filter:
        query = query.where(VerificationCampaign.status == status_filter)
    if search:
        s = f'%{search.strip()}%'
        query = query.where(
            or_(
                VerificationCampaign.campaign_reference.ilike(s),
                VerificationCampaign.name.ilike(s),
            )
        )
    query = query.order_by(VerificationCampaign.created_at.desc())
    campaigns = db.scalars(query).all()

    items = []
    for c in campaigns:
        metrics = _compute_campaign_metrics(db, company_id, c.id)
        creator = db.get(User, c.created_by_id)
        items.append(
            VerificationCampaignRead(
                id=c.id,
                company_id=c.company_id,
                campaign_reference=c.campaign_reference,
                name=c.name,
                description=c.description,
                status=c.status,
                start_date=c.start_date,
                end_date=c.end_date,
                scope_category_ids=[UUID(x) if isinstance(x, str) else x for x in (c.scope_category_ids or [])] or None,
                scope_location_ids=[UUID(x) if isinstance(x, str) else x for x in (c.scope_location_ids or [])] or None,
                created_by_id=c.created_by_id,
                created_by_name=creator.email if creator else None,
                started_at=c.started_at,
                completed_at=c.completed_at,
                closed_by_id=c.closed_by_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
                **metrics,
            )
        )
    return items


@router.post(
    '/verification-campaigns',
    response_model=VerificationCampaignRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def create_campaign(
    company_id: UUID,
    payload: VerificationCampaignCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)

    if payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Campaign end date must be on or after the start date',
        )

    ref = payload.campaign_reference.strip()
    if not ref:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Campaign reference cannot be blank')

    existing = db.scalar(
        select(VerificationCampaign.id).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.campaign_reference == ref,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Campaign reference "{ref}" already exists in this company',
        )

    # Validate categories if supplied
    cat_ids = []
    if payload.scope_category_ids:
        for cid in payload.scope_category_ids:
            cat = db.scalar(select(AssetCategory.id).where(AssetCategory.company_id == company_id, AssetCategory.id == cid))
            if cat is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Invalid category ID: {cid}')
            cat_ids.append(str(cid))

    # Validate locations if supplied
    loc_ids = []
    if payload.scope_location_ids:
        for lid in payload.scope_location_ids:
            loc = db.scalar(select(Location.id).where(Location.company_id == company_id, Location.id == lid))
            if loc is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Invalid location ID: {lid}')
            loc_ids.append(str(lid))

    campaign = VerificationCampaign(
        company_id=company_id,
        campaign_reference=ref,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        status='draft',
        start_date=payload.start_date,
        end_date=payload.end_date,
        scope_category_ids=cat_ids or None,
        scope_location_ids=loc_ids or None,
        created_by_id=actor.user.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    metrics = _compute_campaign_metrics(db, company_id, campaign.id)
    return VerificationCampaignRead(
        id=campaign.id,
        company_id=campaign.company_id,
        campaign_reference=campaign.campaign_reference,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        scope_category_ids=[UUID(x) for x in (campaign.scope_category_ids or [])] or None,
        scope_location_ids=[UUID(x) for x in (campaign.scope_location_ids or [])] or None,
        created_by_id=campaign.created_by_id,
        created_by_name=actor.user.email,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        closed_by_id=campaign.closed_by_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        **metrics,
    )


@router.get(
    '/verification-campaigns/{campaign_id}',
    response_model=VerificationCampaignRead,
    dependencies=[Depends(require_permission('verification.read'))],
)
def get_campaign(
    company_id: UUID,
    campaign_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    metrics = _compute_campaign_metrics(db, company_id, campaign.id)
    creator = db.get(User, campaign.created_by_id)
    return VerificationCampaignRead(
        id=campaign.id,
        company_id=campaign.company_id,
        campaign_reference=campaign.campaign_reference,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        scope_category_ids=[UUID(x) for x in (campaign.scope_category_ids or [])] or None,
        scope_location_ids=[UUID(x) for x in (campaign.scope_location_ids or [])] or None,
        created_by_id=campaign.created_by_id,
        created_by_name=creator.email if creator else None,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        closed_by_id=campaign.closed_by_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        **metrics,
    )


@router.patch(
    '/verification-campaigns/{campaign_id}',
    response_model=VerificationCampaignRead,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def update_campaign(
    company_id: UUID,
    campaign_id: UUID,
    payload: VerificationCampaignUpdate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    if campaign.status != 'draft':
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Campaign scope and dates cannot be changed once verification has started',
        )

    if payload.name is not None:
        campaign.name = payload.name.strip()
    if payload.description is not None:
        campaign.description = payload.description.strip() or None

    new_start = payload.start_date if payload.start_date is not None else campaign.start_date
    new_end = payload.end_date if payload.end_date is not None else campaign.end_date
    if new_end < new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Campaign end date must be on or after the start date',
        )
    campaign.start_date = new_start
    campaign.end_date = new_end

    if payload.scope_category_ids is not None:
        cat_ids = []
        for cid in payload.scope_category_ids:
            cat = db.scalar(select(AssetCategory.id).where(AssetCategory.company_id == company_id, AssetCategory.id == cid))
            if cat is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Invalid category ID: {cid}')
            cat_ids.append(str(cid))
        campaign.scope_category_ids = cat_ids or None

    if payload.scope_location_ids is not None:
        loc_ids = []
        for lid in payload.scope_location_ids:
            loc = db.scalar(select(Location.id).where(Location.company_id == company_id, Location.id == lid))
            if loc is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f'Invalid location ID: {lid}')
            loc_ids.append(str(lid))
        campaign.scope_location_ids = loc_ids or None

    campaign.updated_at = _utc_now()
    db.commit()
    db.refresh(campaign)

    metrics = _compute_campaign_metrics(db, company_id, campaign.id)
    creator = db.get(User, campaign.created_by_id)
    return VerificationCampaignRead(
        id=campaign.id,
        company_id=campaign.company_id,
        campaign_reference=campaign.campaign_reference,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        scope_category_ids=[UUID(x) for x in (campaign.scope_category_ids or [])] or None,
        scope_location_ids=[UUID(x) for x in (campaign.scope_location_ids or [])] or None,
        created_by_id=campaign.created_by_id,
        created_by_name=creator.email if creator else None,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        closed_by_id=campaign.closed_by_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        **metrics,
    )


@router.post(
    '/verification-campaigns/{campaign_id}/status',
    response_model=VerificationCampaignRead,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def transition_campaign_status(
    company_id: UUID,
    campaign_id: UUID,
    payload: VerificationCampaignStatusTransition,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    target_status = payload.status
    current_status = campaign.status

    if current_status == target_status:
        # Idempotent no-op
        metrics = _compute_campaign_metrics(db, company_id, campaign.id)
        creator = db.get(User, campaign.created_by_id)
        return VerificationCampaignRead(
            id=campaign.id,
            company_id=campaign.company_id,
            campaign_reference=campaign.campaign_reference,
            name=campaign.name,
            description=campaign.description,
            status=campaign.status,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            scope_category_ids=[UUID(x) for x in (campaign.scope_category_ids or [])] or None,
            scope_location_ids=[UUID(x) for x in (campaign.scope_location_ids or [])] or None,
            created_by_id=campaign.created_by_id,
            created_by_name=creator.email if creator else None,
            started_at=campaign.started_at,
            completed_at=campaign.completed_at,
            closed_by_id=campaign.closed_by_id,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            **metrics,
        )

    # Valid lifecycle transitions:
    # draft -> in_progress, cancelled
    # in_progress -> under_review, cancelled
    # under_review -> completed, in_progress, cancelled
    # completed, cancelled are terminal
    if current_status in ('completed', 'cancelled'):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Cannot transition campaign from terminal status "{current_status}"',
        )

    if target_status == 'in_progress':
        if current_status not in ('draft', 'under_review'):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Invalid status transition from "{current_status}" to "{target_status}"',
            )
        if current_status == 'draft':
            # Create stable snapshot of expected assets
            asset_query = select(Asset).where(
                Asset.company_id == company_id,
                Asset.status != 'disposed',
            )
            if campaign.scope_category_ids:
                cat_uuids = [UUID(x) for x in campaign.scope_category_ids]
                asset_query = asset_query.where(Asset.category_id.in_(cat_uuids))
            if campaign.scope_location_ids:
                loc_uuids = [UUID(x) for x in campaign.scope_location_ids]
                asset_query = asset_query.where(Asset.location_id.in_(loc_uuids))

            assets = db.scalars(asset_query).all()
            for asset in assets:
                # Find active assignment recipient if any
                active_assignment = db.scalar(
                    select(AssetAssignment).where(
                        AssetAssignment.company_id == company_id,
                        AssetAssignment.asset_id == asset.id,
                        AssetAssignment.status == 'active',
                    )
                )
                custodian_id = active_assignment.recipient_id if active_assignment else None
                custodian_name = None
                if custodian_id:
                    u = db.get(User, custodian_id)
                    custodian_name = u.email if u else None
                elif asset.custodian_name:
                    custodian_name = asset.custodian_name

                expected = VerificationExpectedAsset(
                    company_id=company_id,
                    campaign_id=campaign.id,
                    asset_id=asset.id,
                    expected_site_id=asset.site_id,
                    expected_location_id=asset.location_id,
                    expected_department_id=asset.responsible_department_id,
                    expected_custodian_id=custodian_id,
                    expected_custodian_name=custodian_name,
                    expected_condition='good',
                    expected_status=asset.status,
                )
                db.add(expected)

            campaign.started_at = _utc_now()
        campaign.status = 'in_progress'

    elif target_status == 'under_review':
        if current_status != 'in_progress':
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Invalid status transition from "{current_status}" to "{target_status}"',
            )
        campaign.status = 'under_review'

    elif target_status == 'completed':
        if current_status != 'under_review':
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Campaign must be in "under_review" status before completing. Current: "{current_status}"',
            )
        campaign.status = 'completed'
        campaign.completed_at = _utc_now()
        campaign.closed_by_id = actor.user.id

    elif target_status == 'cancelled':
        campaign.status = 'cancelled'
        campaign.closed_by_id = actor.user.id
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Unsupported target status: "{target_status}"',
        )

    campaign.updated_at = _utc_now()
    db.commit()
    db.refresh(campaign)

    metrics = _compute_campaign_metrics(db, company_id, campaign.id)
    creator = db.get(User, campaign.created_by_id)
    return VerificationCampaignRead(
        id=campaign.id,
        company_id=campaign.company_id,
        campaign_reference=campaign.campaign_reference,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        scope_category_ids=[UUID(x) for x in (campaign.scope_category_ids or [])] or None,
        scope_location_ids=[UUID(x) for x in (campaign.scope_location_ids or [])] or None,
        created_by_id=campaign.created_by_id,
        created_by_name=creator.email if creator else None,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        closed_by_id=campaign.closed_by_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        **metrics,
    )


@router.get(
    '/verification-campaigns/{campaign_id}/expected-assets',
    response_model=list[VerificationExpectedAssetRead],
    dependencies=[Depends(require_permission('verification.read'))],
)
def list_expected_assets(
    company_id: UUID,
    campaign_id: UUID,
    search: str | None = Query(None),
    verified: bool | None = Query(None),
    category_id: UUID | None = Query(None),
    location_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign.id).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    query = (
        select(
            VerificationExpectedAsset,
            Asset.asset_number,
            Asset.category_id,
            AssetCategory.name.label('category_name'),
            Asset.serial_number,
            Asset.model,
            Asset.manufacturer,
            Site.name.label('site_name'),
            Location.name.label('location_name'),
            Department.name.label('department_name'),
            VerificationObservation.id.label('observation_id'),
            VerificationObservation.is_found.label('observation_found'),
        )
        .join(Asset, Asset.id == VerificationExpectedAsset.asset_id)
        .join(AssetCategory, AssetCategory.id == Asset.category_id)
        .outerjoin(Site, Site.id == VerificationExpectedAsset.expected_site_id)
        .outerjoin(Location, Location.id == VerificationExpectedAsset.expected_location_id)
        .outerjoin(Department, Department.id == VerificationExpectedAsset.expected_department_id)
        .outerjoin(
            VerificationObservation,
            (VerificationObservation.campaign_id == campaign_id)
            & (VerificationObservation.expected_asset_id == VerificationExpectedAsset.id),
        )
        .where(
            VerificationExpectedAsset.company_id == company_id,
            VerificationExpectedAsset.campaign_id == campaign_id,
        )
    )

    if category_id:
        query = query.where(Asset.category_id == category_id)
    if location_id:
        query = query.where(VerificationExpectedAsset.expected_location_id == location_id)
    if verified is not None:
        if verified:
            query = query.where(VerificationObservation.id.is_not(None))
        else:
            query = query.where(VerificationObservation.id.is_(None))
    if search:
        s = f'%{search.strip()}%'
        query = query.where(
            or_(
                Asset.asset_number.ilike(s),
                Asset.serial_number.ilike(s),
                Asset.model.ilike(s),
                Asset.manufacturer.ilike(s),
            )
        )

    query = query.order_by(Asset.asset_number.asc())
    rows = db.execute(query).all()

    # Pre-fetch discrepancy mapping for this campaign
    discrepancies = db.execute(
        select(
            VerificationDiscrepancy.expected_asset_id,
            VerificationDiscrepancy.discrepancy_type,
        ).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
            VerificationDiscrepancy.expected_asset_id.is_not(None),
        )
    ).all()
    disc_map: dict[UUID, list[str]] = {}
    for ea_id, dt in discrepancies:
        disc_map.setdefault(ea_id, []).append(dt)

    results = []
    for row in rows:
        ea = row.VerificationExpectedAsset
        obs_id = row.observation_id
        is_ver = obs_id is not None
        ea_discs = disc_map.get(ea.id, [])
        results.append(
            VerificationExpectedAssetRead(
                id=ea.id,
                company_id=ea.company_id,
                campaign_id=ea.campaign_id,
                asset_id=ea.asset_id,
                asset_number=row.asset_number,
                category_id=row.category_id,
                category_name=row.category_name,
                serial_number=row.serial_number,
                model=row.model,
                manufacturer=row.manufacturer,
                expected_site_id=ea.expected_site_id,
                site_name=row.site_name,
                expected_location_id=ea.expected_location_id,
                location_name=row.location_name,
                expected_department_id=ea.expected_department_id,
                department_name=row.department_name,
                expected_custodian_id=ea.expected_custodian_id,
                expected_custodian_name=ea.expected_custodian_name,
                expected_condition=ea.expected_condition,
                expected_status=ea.expected_status,
                is_verified=is_ver,
                observation_id=obs_id,
                observation_found=row.observation_found,
                has_discrepancy=len(ea_discs) > 0,
                discrepancy_types=ea_discs,
                created_at=ea.created_at,
            )
        )
    return results


@router.post(
    '/verification-campaigns/{campaign_id}/expected-assets/{expected_asset_id}/observations',
    response_model=VerificationObservationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def record_observation(
    company_id: UUID,
    campaign_id: UUID,
    expected_asset_id: UUID,
    payload: VerificationObservationCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    if campaign.status != 'in_progress':
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Observations can only be recorded when campaign is "in_progress". Current: "{campaign.status}"',
        )

    expected_asset = db.scalar(
        select(VerificationExpectedAsset).where(
            VerificationExpectedAsset.company_id == company_id,
            VerificationExpectedAsset.campaign_id == campaign_id,
            VerificationExpectedAsset.id == expected_asset_id,
        )
    )
    if expected_asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Expected asset not found in this campaign')

    # Prevent duplicate observations
    existing_obs = db.scalar(
        select(VerificationObservation.id).where(
            VerificationObservation.campaign_id == campaign_id,
            VerificationObservation.expected_asset_id == expected_asset_id,
        )
    )
    if existing_obs is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='An observation has already been recorded for this asset in this campaign',
        )

    # Validate location
    actual_site_id = None
    if payload.actual_location_id:
        loc = db.scalar(
            select(Location).where(
                Location.company_id == company_id,
                Location.id == payload.actual_location_id,
            )
        )
        if loc is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Actual location does not belong to this company')
        actual_site_id = loc.site_id

    # Validate custodian if provided
    actual_custodian_name = None
    if payload.actual_custodian_id:
        cust_user = db.get(User, payload.actual_custodian_id)
        if cust_user is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Actual custodian user not found')
        actual_custodian_name = cust_user.email

    v_date = payload.verification_date or date.today()

    obs = VerificationObservation(
        company_id=company_id,
        campaign_id=campaign_id,
        expected_asset_id=expected_asset_id,
        asset_id=expected_asset.asset_id,
        is_found=payload.is_found,
        actual_site_id=actual_site_id,
        actual_location_id=payload.actual_location_id,
        actual_department_id=expected_asset.expected_department_id,
        actual_custodian_id=payload.actual_custodian_id,
        observed_condition=payload.observed_condition.strip(),
        verification_date=v_date,
        verified_by_id=actor.user.id,
        remarks=payload.remarks.strip() if payload.remarks else None,
        reference_notes=payload.reference_notes.strip() if payload.reference_notes else None,
    )
    db.add(obs)
    db.flush()

    # Discrepancy checks:
    # 1. Missing
    if not payload.is_found:
        disc = VerificationDiscrepancy(
            company_id=company_id,
            campaign_id=campaign_id,
            observation_id=obs.id,
            expected_asset_id=expected_asset_id,
            asset_id=expected_asset.asset_id,
            discrepancy_type='missing',
            status='open',
            expected_data={'status': expected_asset.expected_status, 'location_id': str(expected_asset.expected_location_id) if expected_asset.expected_location_id else None},
            observed_data={'status': 'missing', 'remarks': obs.remarks},
            notes='Asset was not found during physical verification',
        )
        db.add(disc)
    else:
        # 2. Location mismatch
        if payload.actual_location_id and payload.actual_location_id != expected_asset.expected_location_id:
            disc = VerificationDiscrepancy(
                company_id=company_id,
                campaign_id=campaign_id,
                observation_id=obs.id,
                expected_asset_id=expected_asset_id,
                asset_id=expected_asset.asset_id,
                discrepancy_type='location_mismatch',
                status='open',
                expected_data={'location_id': str(expected_asset.expected_location_id) if expected_asset.expected_location_id else None, 'site_id': str(expected_asset.expected_site_id) if expected_asset.expected_site_id else None},
                observed_data={'location_id': str(payload.actual_location_id), 'site_id': str(actual_site_id) if actual_site_id else None},
                notes='Observed location differs from expected location',
            )
            db.add(disc)

        # 3. Custodian mismatch
        if payload.actual_custodian_id and payload.actual_custodian_id != expected_asset.expected_custodian_id:
            disc = VerificationDiscrepancy(
                company_id=company_id,
                campaign_id=campaign_id,
                observation_id=obs.id,
                expected_asset_id=expected_asset_id,
                asset_id=expected_asset.asset_id,
                discrepancy_type='custodian_mismatch',
                status='open',
                expected_data={'custodian_id': str(expected_asset.expected_custodian_id) if expected_asset.expected_custodian_id else None, 'custodian_name': expected_asset.expected_custodian_name},
                observed_data={'custodian_id': str(payload.actual_custodian_id), 'custodian_name': actual_custodian_name},
                notes='Observed custodian differs from expected custodian',
            )
            db.add(disc)

        # 4. Condition mismatch
        if expected_asset.expected_condition and payload.observed_condition.strip().casefold() != expected_asset.expected_condition.strip().casefold():
            disc = VerificationDiscrepancy(
                company_id=company_id,
                campaign_id=campaign_id,
                observation_id=obs.id,
                expected_asset_id=expected_asset_id,
                asset_id=expected_asset.asset_id,
                discrepancy_type='condition_mismatch',
                status='open',
                expected_data={'condition': expected_asset.expected_condition},
                observed_data={'condition': payload.observed_condition.strip()},
                notes='Observed condition differs from recorded condition',
            )
            db.add(disc)

    # Note: Asset master data is deliberately NOT altered here.
    db.commit()
    db.refresh(obs)

    asset_rec = db.get(Asset, expected_asset.asset_id)
    loc_rec = db.get(Location, obs.actual_location_id) if obs.actual_location_id else None
    site_rec = db.get(Site, obs.actual_site_id) if obs.actual_site_id else None

    return VerificationObservationRead(
        id=obs.id,
        company_id=obs.company_id,
        campaign_id=obs.campaign_id,
        expected_asset_id=obs.expected_asset_id,
        asset_id=obs.asset_id,
        asset_number=asset_rec.asset_number if asset_rec else None,
        is_found=obs.is_found,
        actual_site_id=obs.actual_site_id,
        actual_site_name=site_rec.name if site_rec else None,
        actual_location_id=obs.actual_location_id,
        actual_location_name=loc_rec.name if loc_rec else None,
        actual_department_id=obs.actual_department_id,
        actual_custodian_id=obs.actual_custodian_id,
        actual_custodian_name=actual_custodian_name,
        observed_condition=obs.observed_condition,
        verification_date=obs.verification_date,
        verified_by_id=obs.verified_by_id,
        verified_by_name=actor.user.email,
        remarks=obs.remarks,
        reference_notes=obs.reference_notes,
        created_at=obs.created_at,
    )


@router.post(
    '/verification-campaigns/{campaign_id}/unregistered-assets',
    response_model=VerificationUnregisteredAssetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def record_unregistered_asset(
    company_id: UUID,
    campaign_id: UUID,
    payload: VerificationUnregisteredAssetCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    if campaign.status != 'in_progress':
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Unregistered assets can only be recorded when campaign is "in_progress". Current: "{campaign.status}"',
        )

    # Validate category
    cat = db.scalar(
        select(AssetCategory).where(
            AssetCategory.company_id == company_id,
            AssetCategory.id == payload.category_id,
        )
    )
    if cat is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Category does not belong to this company')

    site_id = payload.site_id
    if payload.location_id:
        loc = db.scalar(select(Location).where(Location.company_id == company_id, Location.id == payload.location_id))
        if loc is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail='Location does not belong to this company')
        site_id = loc.site_id

    unreg = VerificationUnregisteredAsset(
        company_id=company_id,
        campaign_id=campaign_id,
        serial_number=payload.serial_number.strip() if payload.serial_number else None,
        description=payload.description.strip(),
        category_id=payload.category_id,
        site_id=site_id,
        location_id=payload.location_id,
        custodian_id=payload.custodian_id,
        observed_condition=payload.observed_condition.strip() if payload.observed_condition else 'good',
        remarks=payload.remarks.strip() if payload.remarks else None,
        status='pending',
    )
    db.add(unreg)
    db.flush()

    # Automatically create discrepancy for unregistered asset
    disc = VerificationDiscrepancy(
        company_id=company_id,
        campaign_id=campaign_id,
        discrepancy_type='unregistered_asset',
        status='open',
        observed_data={
            'description': unreg.description,
            'category_id': str(unreg.category_id),
            'serial_number': unreg.serial_number,
            'location_id': str(unreg.location_id) if unreg.location_id else None,
            'unregistered_asset_id': str(unreg.id),
        },
        notes=f'Unregistered asset found during verification: {unreg.description}',
    )
    db.add(disc)
    db.flush()
    unreg.discrepancy_id = disc.id

    db.commit()
    db.refresh(unreg)

    loc_name = db.scalar(select(Location.name).where(Location.id == unreg.location_id)) if unreg.location_id else None
    site_name = db.scalar(select(Site.name).where(Site.id == unreg.site_id)) if unreg.site_id else None
    cust_name = db.scalar(select(User.email).where(User.id == unreg.custodian_id)) if unreg.custodian_id else None

    return VerificationUnregisteredAssetRead(
        id=unreg.id,
        company_id=unreg.company_id,
        campaign_id=unreg.campaign_id,
        observation_id=unreg.observation_id,
        discrepancy_id=unreg.discrepancy_id,
        serial_number=unreg.serial_number,
        description=unreg.description,
        category_id=unreg.category_id,
        category_name=cat.name,
        site_id=unreg.site_id,
        site_name=site_name,
        location_id=unreg.location_id,
        location_name=loc_name,
        custodian_id=unreg.custodian_id,
        custodian_name=cust_name,
        observed_condition=unreg.observed_condition,
        remarks=unreg.remarks,
        status=unreg.status,
        registered_asset_id=unreg.registered_asset_id,
        registered_asset_number=None,
        created_at=unreg.created_at,
    )


@router.get(
    '/verification-campaigns/{campaign_id}/unregistered-assets',
    response_model=list[VerificationUnregisteredAssetRead],
    dependencies=[Depends(require_permission('verification.read'))],
)
def list_unregistered_assets(
    company_id: UUID,
    campaign_id: UUID,
    status_filter: str | None = Query(None, alias='status'),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            VerificationUnregisteredAsset,
            AssetCategory.name.label('category_name'),
            Site.name.label('site_name'),
            Location.name.label('location_name'),
            User.email.label('custodian_name'),
            Asset.asset_number.label('registered_asset_number'),
        )
        .join(AssetCategory, AssetCategory.id == VerificationUnregisteredAsset.category_id)
        .outerjoin(Site, Site.id == VerificationUnregisteredAsset.site_id)
        .outerjoin(Location, Location.id == VerificationUnregisteredAsset.location_id)
        .outerjoin(User, User.id == VerificationUnregisteredAsset.custodian_id)
        .outerjoin(Asset, Asset.id == VerificationUnregisteredAsset.registered_asset_id)
        .where(
            VerificationUnregisteredAsset.company_id == company_id,
            VerificationUnregisteredAsset.campaign_id == campaign_id,
        )
    )
    if status_filter:
        query = query.where(VerificationUnregisteredAsset.status == status_filter)
    query = query.order_by(VerificationUnregisteredAsset.created_at.desc())
    rows = db.execute(query).all()

    return [
        VerificationUnregisteredAssetRead(
            id=r.VerificationUnregisteredAsset.id,
            company_id=r.VerificationUnregisteredAsset.company_id,
            campaign_id=r.VerificationUnregisteredAsset.campaign_id,
            observation_id=r.VerificationUnregisteredAsset.observation_id,
            discrepancy_id=r.VerificationUnregisteredAsset.discrepancy_id,
            serial_number=r.VerificationUnregisteredAsset.serial_number,
            description=r.VerificationUnregisteredAsset.description,
            category_id=r.VerificationUnregisteredAsset.category_id,
            category_name=r.category_name,
            site_id=r.VerificationUnregisteredAsset.site_id,
            site_name=r.site_name,
            location_id=r.VerificationUnregisteredAsset.location_id,
            location_name=r.location_name,
            custodian_id=r.VerificationUnregisteredAsset.custodian_id,
            custodian_name=r.custodian_name,
            observed_condition=r.VerificationUnregisteredAsset.observed_condition,
            remarks=r.VerificationUnregisteredAsset.remarks,
            status=r.VerificationUnregisteredAsset.status,
            registered_asset_id=r.VerificationUnregisteredAsset.registered_asset_id,
            registered_asset_number=r.registered_asset_number,
            created_at=r.VerificationUnregisteredAsset.created_at,
        )
        for r in rows
    ]


@router.get(
    '/verification-campaigns/{campaign_id}/discrepancies',
    response_model=list[VerificationDiscrepancyRead],
    dependencies=[Depends(require_permission('verification.read'))],
)
def list_discrepancies(
    company_id: UUID,
    campaign_id: UUID,
    discrepancy_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias='status'),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            VerificationDiscrepancy,
            Asset.asset_number,
            User.email.label('resolved_by_name'),
            VerificationCampaign.campaign_reference,
        )
        .join(VerificationCampaign, VerificationCampaign.id == VerificationDiscrepancy.campaign_id)
        .outerjoin(Asset, Asset.id == VerificationDiscrepancy.asset_id)
        .outerjoin(User, User.id == VerificationDiscrepancy.resolved_by_id)
        .where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
        )
    )
    if discrepancy_type:
        query = query.where(VerificationDiscrepancy.discrepancy_type == discrepancy_type)
    if status_filter:
        query = query.where(VerificationDiscrepancy.status == status_filter)
    query = query.order_by(VerificationDiscrepancy.created_at.desc())
    rows = db.execute(query).all()

    return [
        VerificationDiscrepancyRead(
            id=r.VerificationDiscrepancy.id,
            company_id=r.VerificationDiscrepancy.company_id,
            campaign_id=r.VerificationDiscrepancy.campaign_id,
            campaign_reference=r.campaign_reference,
            observation_id=r.VerificationDiscrepancy.observation_id,
            expected_asset_id=r.VerificationDiscrepancy.expected_asset_id,
            asset_id=r.VerificationDiscrepancy.asset_id,
            asset_number=r.asset_number,
            discrepancy_type=r.VerificationDiscrepancy.discrepancy_type,
            status=r.VerificationDiscrepancy.status,
            expected_data=r.VerificationDiscrepancy.expected_data,
            observed_data=r.VerificationDiscrepancy.observed_data,
            notes=r.VerificationDiscrepancy.notes,
            resolution_action=r.VerificationDiscrepancy.resolution_action,
            resolution_notes=r.VerificationDiscrepancy.resolution_notes,
            resolved_by_id=r.VerificationDiscrepancy.resolved_by_id,
            resolved_by_name=r.resolved_by_name,
            resolved_at=r.VerificationDiscrepancy.resolved_at,
            created_at=r.VerificationDiscrepancy.created_at,
        )
        for r in rows
    ]


@router.post(
    '/verification-campaigns/{campaign_id}/discrepancies/{discrepancy_id}/resolve',
    response_model=VerificationDiscrepancyRead,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def resolve_discrepancy(
    company_id: UUID,
    campaign_id: UUID,
    discrepancy_id: UUID,
    payload: VerificationDiscrepancyResolveRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    disc = db.scalar(
        select(VerificationDiscrepancy).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
            VerificationDiscrepancy.id == discrepancy_id,
        )
    )
    if disc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Discrepancy not found')

    if disc.status in ('resolved', 'dismissed'):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Discrepancy is already resolved or dismissed')

    action = payload.resolution_action
    notes = payload.resolution_notes.strip()

    # If action is 'update_master', update the asset master record reusing existing mechanisms!
    if action == 'update_master':
        if disc.asset_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail='Cannot update master data for a discrepancy with no linked asset. Use registration for unregistered assets.',
            )
        asset = db.scalar(select(Asset).where(Asset.company_id == company_id, Asset.id == disc.asset_id))
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Asset not found')

        obs = db.get(VerificationObservation, disc.observation_id) if disc.observation_id else None

        if disc.discrepancy_type == 'location_mismatch':
            if obs and obs.actual_location_id:
                old_loc = asset.location_id
                asset.location_id = obs.actual_location_id
                asset.site_id = obs.actual_site_id
                record_history(
                    db,
                    asset,
                    'updated',
                    'location_id',
                    str(old_loc) if old_loc else None,
                    str(obs.actual_location_id),
                )
        elif disc.discrepancy_type == 'condition_mismatch':
            if obs and obs.observed_condition:
                old_notes = asset.notes
                new_notes = f'{old_notes or ""}\n[Verified condition: {obs.observed_condition}]'.strip()
                asset.notes = new_notes
                record_history(
                    db,
                    asset,
                    'updated',
                    'notes',
                    old_notes,
                    new_notes,
                )
        elif disc.discrepancy_type == 'missing':
            # Mark asset status to 'in_repair' or 'lost' in notes
            old_status = asset.status
            new_notes = f'{asset.notes or ""}\n[Flagged missing during verification campaign: {notes}]'.strip()
            asset.notes = new_notes
            record_history(db, asset, 'updated', 'notes', old_notes, new_notes)
        elif disc.discrepancy_type == 'custodian_mismatch':
            if obs and obs.actual_custodian_id:
                u = db.get(User, obs.actual_custodian_id)
                old_cust = asset.custodian_name
                asset.custodian_name = u.email if u else None
                record_history(db, asset, 'updated', 'custodian_name', old_cust, asset.custodian_name)

    disc.status = 'dismissed' if action in ('dismiss', 'no_change') else 'resolved'
    disc.resolution_action = action
    disc.resolution_notes = notes
    disc.resolved_by_id = actor.user.id
    disc.resolved_at = _utc_now()
    disc.updated_at = _utc_now()

    db.commit()
    db.refresh(disc)

    asset_num = db.scalar(select(Asset.asset_number).where(Asset.id == disc.asset_id)) if disc.asset_id else None
    camp_ref = db.scalar(select(VerificationCampaign.campaign_reference).where(VerificationCampaign.id == campaign_id))

    return VerificationDiscrepancyRead(
        id=disc.id,
        company_id=disc.company_id,
        campaign_id=disc.campaign_id,
        campaign_reference=camp_ref,
        observation_id=disc.observation_id,
        expected_asset_id=disc.expected_asset_id,
        asset_id=disc.asset_id,
        asset_number=asset_num,
        discrepancy_type=disc.discrepancy_type,
        status=disc.status,
        expected_data=disc.expected_data,
        observed_data=disc.observed_data,
        notes=disc.notes,
        resolution_action=disc.resolution_action,
        resolution_notes=disc.resolution_notes,
        resolved_by_id=disc.resolved_by_id,
        resolved_by_name=actor.user.email,
        resolved_at=disc.resolved_at,
        created_at=disc.created_at,
    )


@router.post(
    '/verification-campaigns/{campaign_id}/unregistered-assets/{unregistered_asset_id}/register',
    response_model=VerificationUnregisteredAssetRead,
    dependencies=[Depends(require_permission('verification.manage'))],
)
def register_unregistered_asset(
    company_id: UUID,
    campaign_id: UUID,
    unregistered_asset_id: UUID,
    payload: VerificationUnregisteredAssetRegister,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(current_actor),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    unreg = db.scalar(
        select(VerificationUnregisteredAsset).where(
            VerificationUnregisteredAsset.company_id == company_id,
            VerificationUnregisteredAsset.campaign_id == campaign_id,
            VerificationUnregisteredAsset.id == unregistered_asset_id,
        )
    )
    if unreg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Unregistered asset not found')

    if unreg.status == 'registered':
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'This unregistered asset has already been registered (Asset ID: {unreg.registered_asset_id})',
        )

    # Use numbering sequence logic
    category_id = unreg.category_id
    if payload.asset_number and payload.asset_number.strip():
        num = payload.asset_number.strip()
        # Ensure not duplicate
        dup = db.scalar(select(Asset.id).where(Asset.company_id == company_id, Asset.asset_number == num))
        if dup is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'Asset number "{num}" is already in use')
    else:
        num = next_asset_number(db, company_id, category_id)

    custodian_name = None
    if unreg.custodian_id:
        u = db.get(User, unreg.custodian_id)
        custodian_name = u.email if u else None

    # Create Asset
    new_asset = Asset(
        company_id=company_id,
        category_id=category_id,
        asset_number=num,
        serial_number=unreg.serial_number,
        model=unreg.description,
        acquisition_date=payload.acquisition_date or date.today(),
        acquisition_cost=payload.acquisition_cost,
        status='in_stock' if not unreg.custodian_id else 'assigned',
        site_id=unreg.site_id,
        location_id=unreg.location_id,
        responsible_department_id=payload.responsible_department_id,
        cost_center_id=payload.cost_center_id,
        custodian_name=custodian_name,
        notes=f'Registered from verification campaign {campaign.campaign_reference}. {payload.resolution_notes}',
    )
    db.add(new_asset)
    db.flush()

    record_history(db, new_asset, 'created')

    unreg.status = 'registered'
    unreg.registered_asset_id = new_asset.id
    unreg.updated_at = _utc_now()

    # Mark associated discrepancy resolved
    if unreg.discrepancy_id:
        disc = db.get(VerificationDiscrepancy, unreg.discrepancy_id)
        if disc:
            disc.status = 'resolved'
            disc.resolution_action = 'register_asset'
            disc.resolution_notes = payload.resolution_notes
            disc.resolved_by_id = actor.user.id
            disc.resolved_at = _utc_now()
            disc.asset_id = new_asset.id

    db.commit()
    db.refresh(unreg)

    cat = db.get(AssetCategory, unreg.category_id)
    site_name = db.scalar(select(Site.name).where(Site.id == unreg.site_id)) if unreg.site_id else None
    loc_name = db.scalar(select(Location.name).where(Location.id == unreg.location_id)) if unreg.location_id else None

    return VerificationUnregisteredAssetRead(
        id=unreg.id,
        company_id=unreg.company_id,
        campaign_id=unreg.campaign_id,
        observation_id=unreg.observation_id,
        discrepancy_id=unreg.discrepancy_id,
        serial_number=unreg.serial_number,
        description=unreg.description,
        category_id=unreg.category_id,
        category_name=cat.name if cat else None,
        site_id=unreg.site_id,
        site_name=site_name,
        location_id=unreg.location_id,
        location_name=loc_name,
        custodian_id=unreg.custodian_id,
        custodian_name=custodian_name,
        observed_condition=unreg.observed_condition,
        remarks=unreg.remarks,
        status=unreg.status,
        registered_asset_id=new_asset.id,
        registered_asset_number=new_asset.asset_number,
        created_at=unreg.created_at,
    )


@router.get(
    '/verification-campaigns/{campaign_id}/dashboard',
    response_model=VerificationDashboardSummary,
    dependencies=[Depends(require_permission('verification.read'))],
)
def get_campaign_dashboard(
    company_id: UUID,
    campaign_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    campaign = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.id == campaign_id,
        )
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Verification campaign not found')

    metrics = _compute_campaign_metrics(db, company_id, campaign.id)

    # Discrepancies by type breakdown
    rows = db.execute(
        select(
            VerificationDiscrepancy.discrepancy_type,
            func.count(VerificationDiscrepancy.id),
        )
        .where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
        )
        .group_by(VerificationDiscrepancy.discrepancy_type)
    ).all()
    disc_by_type = {
        'missing': 0,
        'location_mismatch': 0,
        'custodian_mismatch': 0,
        'condition_mismatch': 0,
        'unregistered_asset': 0,
    }
    for dt, cnt in rows:
        disc_by_type[dt] = cnt

    pending_res = db.scalar(
        select(func.count(VerificationDiscrepancy.id)).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
            VerificationDiscrepancy.status == 'open',
        )
    ) or 0

    resolved_res = db.scalar(
        select(func.count(VerificationDiscrepancy.id)).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.campaign_id == campaign_id,
            VerificationDiscrepancy.status.in_(['resolved', 'dismissed']),
        )
    ) or 0

    return VerificationDashboardSummary(
        campaign_id=campaign.id,
        campaign_reference=campaign.campaign_reference,
        campaign_name=campaign.name,
        status=campaign.status,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        total_expected=metrics['total_expected'],
        total_verified=metrics['total_verified'],
        total_unverified=metrics['total_unverified'],
        total_missing=metrics['total_missing'],
        completion_percentage=metrics['completion_percentage'],
        discrepancies_by_type=disc_by_type,
        unregistered_count=metrics['total_unregistered'],
        pending_resolutions=pending_res,
        resolved_resolutions=resolved_res,
    )

