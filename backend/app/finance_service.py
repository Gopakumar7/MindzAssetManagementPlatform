import calendar
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.audit import record_security_event
from app.models import (
    Asset,
    AssetAssignment,
    AssetDepreciationEntry,
    AssetDisposal,
    AssetFinancial,
    User,
)
from app.schemas import (
    AssetDisposalCreate,
    AssetFinancialAdjust,
    AssetFinancialCreate,
    AssetFinancialUpdate,
    BatchDepreciationResult,
    DepreciationScheduleItem,
)
from app.services import get_scoped, record_history


def calculate_monthly_depreciation(
    capitalised_cost: Decimal,
    residual_value: Decimal,
    useful_life_months: int,
) -> Decimal:
    """Calculates straight-line monthly depreciation with decimal safety and ROUND_HALF_UP."""
    if useful_life_months <= 0:
        return Decimal('0.00')
    basis = capitalised_cost - residual_value
    if basis <= Decimal('0.00'):
        return Decimal('0.00')
    monthly = basis / Decimal(useful_life_months)
    return monthly.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_or_create_financial(
    db: Session,
    company_id: UUID,
    asset: Asset,
    defaults: AssetFinancialCreate | None = None,
) -> AssetFinancial:
    """Retrieves existing financial profile or creates a default one derived from asset / procurement data."""
    financial = db.scalar(
        select(AssetFinancial).where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.asset_id == asset.id,
        )
    )
    if financial is not None:
        return financial

    if defaults is not None:
        cost = defaults.capitalised_cost
        currency = defaults.currency
        method = defaults.depreciation_method
        useful_life = defaults.useful_life_months
        residual = defaults.residual_value
        start_date = defaults.depreciation_start_date
    else:
        cost = Decimal(str(asset.acquisition_cost)) if asset.acquisition_cost is not None else Decimal('0.00')
        currency = 'INR'
        method = 'straight_line'
        useful_life = 36  # Default 36 months (3 years)
        residual = Decimal('0.00')
        start_date = asset.acquisition_date or date.today()

    financial_status = 'disposed' if asset.status == 'disposed' else ('fully_depreciated' if cost <= residual else 'active')

    financial = AssetFinancial(
        company_id=company_id,
        asset_id=asset.id,
        capitalised_cost=cost,
        currency=currency,
        depreciation_method=method,
        useful_life_months=useful_life,
        residual_value=residual,
        depreciation_start_date=start_date,
        accumulated_depreciation=Decimal('0.00'),
        current_book_value=cost,
        financial_status=financial_status,
    )
    db.add(financial)
    db.flush()
    return financial


def calculate_depreciation_schedule(
    db: Session,
    company_id: UUID,
    asset_id: UUID,
) -> list[DepreciationScheduleItem]:
    """Generates the straight-line monthly depreciation schedule (posted and projected entries)."""
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    financial = get_or_create_financial(db, company_id, asset)

    posted_entries = {
        entry.period: entry
        for entry in db.scalars(
            select(AssetDepreciationEntry)
            .where(
                AssetDepreciationEntry.company_id == company_id,
                AssetDepreciationEntry.asset_id == asset_id,
            )
            .order_by(AssetDepreciationEntry.period.asc())
        ).all()
    }

    schedule: list[DepreciationScheduleItem] = []
    depreciable_basis = financial.capitalised_cost - financial.residual_value
    monthly_rate = calculate_monthly_depreciation(
        financial.capitalised_cost,
        financial.residual_value,
        financial.useful_life_months,
    )

    start_date = financial.depreciation_start_date
    start_year = start_date.year
    start_month = start_date.month

    running_accumulated = Decimal('0.00')

    for month_index in range(financial.useful_life_months):
        year_offset = (start_month - 1 + month_index) // 12
        cur_month = ((start_month - 1 + month_index) % 12) + 1
        cur_year = start_year + year_offset
        period = f'{cur_year:04d}-{cur_month:02d}'
        days_in_month = calendar.monthrange(cur_year, cur_month)[1]
        period_start = date(cur_year, cur_month, 1)
        period_end = date(cur_year, cur_month, days_in_month)

        if period in posted_entries:
            entry = posted_entries[period]
            running_accumulated = entry.accumulated_depreciation_after
            schedule.append(
                DepreciationScheduleItem(
                    period=period,
                    period_start_date=entry.period_start_date,
                    period_end_date=entry.period_end_date,
                    depreciation_amount=entry.depreciation_amount,
                    accumulated_depreciation=entry.accumulated_depreciation_after,
                    book_value=entry.book_value_after,
                    status='posted',
                )
            )
        else:
            remaining_basis = depreciable_basis - running_accumulated
            if remaining_basis <= Decimal('0.00'):
                amount = Decimal('0.00')
            elif month_index == financial.useful_life_months - 1 or monthly_rate > remaining_basis:
                # Final month absorbs any rounding residuals
                amount = remaining_basis
            else:
                amount = monthly_rate

            running_accumulated += amount
            book_value = financial.capitalised_cost - running_accumulated
            schedule.append(
                DepreciationScheduleItem(
                    period=period,
                    period_start_date=period_start,
                    period_end_date=period_end,
                    depreciation_amount=amount,
                    accumulated_depreciation=running_accumulated,
                    book_value=book_value,
                    status='pending',
                )
            )

    return schedule


def _calculate_period_depreciation(
    financial: AssetFinancial,
    posted_count: int,
) -> tuple[Decimal, Decimal, Decimal]:
    """Helper calculating (period_amount, accumulated_after, book_value_after)."""
    depreciable_basis = financial.capitalised_cost - financial.residual_value
    remaining_basis = depreciable_basis - financial.accumulated_depreciation
    if remaining_basis <= Decimal('0.00'):
        return Decimal('0.00'), financial.accumulated_depreciation, financial.current_book_value

    monthly = calculate_monthly_depreciation(
        financial.capitalised_cost,
        financial.residual_value,
        financial.useful_life_months,
    )
    is_final_period = (posted_count + 1 >= financial.useful_life_months) or (monthly > remaining_basis)
    period_amount = remaining_basis if is_final_period else monthly

    accumulated_after = financial.accumulated_depreciation + period_amount
    book_value_after = financial.capitalised_cost - accumulated_after
    return period_amount, accumulated_after, book_value_after


def post_single_depreciation(
    db: Session,
    company_id: UUID,
    asset_id: UUID,
    period: str,
    user_id: UUID,
    notes: str | None = None,
) -> AssetDepreciationEntry:
    """Authoritative service for posting depreciation on a single asset."""
    # Parse and validate period format
    try:
        parts = period.split('-')
        year = int(parts[0])
        month = int(parts[1])
        if not (1 <= month <= 12):
            raise ValueError()
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail='Period must be formatted as YYYY-MM')

    days_in_month = calendar.monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end = date(year, month, days_in_month)

    # Row lock asset and financial
    asset = db.scalar(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id == asset_id)
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found')

    financial = db.scalar(
        select(AssetFinancial)
        .where(AssetFinancial.company_id == company_id, AssetFinancial.asset_id == asset_id)
        .with_for_update()
    )
    if financial is None:
        financial = get_or_create_financial(db, company_id, asset)
        db.flush()

    # Boundary check 1: Period cannot be earlier than start date
    start_period = financial.depreciation_start_date.strftime('%Y-%m')
    if period < start_period:
        raise HTTPException(
            status_code=422,
            detail=f'Cannot post depreciation for period {period} prior to depreciation start date {financial.depreciation_start_date}',
        )

    # Boundary check 2: Disposal cutoff
    disposal = db.scalar(
        select(AssetDisposal).where(
            AssetDisposal.company_id == company_id,
            AssetDisposal.asset_id == asset_id,
        )
    )
    if disposal is not None:
        disposal_period = disposal.disposal_date.strftime('%Y-%m')
        if period > disposal_period:
            raise HTTPException(
                status_code=422,
                detail=f'Cannot post depreciation for period {period} because the asset was disposed on {disposal.disposal_date}',
            )

    # Boundary check 3: Duplicate posting prevention
    existing = db.scalar(
        select(AssetDepreciationEntry.id).where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
            AssetDepreciationEntry.period == period,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f'Depreciation for period {period} has already been posted for this asset',
        )

    # Boundary check 4: Fully depreciated or zero basis
    depreciable_basis = financial.capitalised_cost - financial.residual_value
    if depreciable_basis <= Decimal('0.00'):
        raise HTTPException(
            status_code=422,
            detail='Asset depreciable basis is zero (capitalised cost equals residual value)',
        )
    if financial.accumulated_depreciation >= depreciable_basis:
        raise HTTPException(
            status_code=422,
            detail='Asset is already fully depreciated',
        )

    posted_count = db.scalar(
        select(func.count(AssetDepreciationEntry.id)).where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
        )
    ) or 0
    if posted_count >= financial.useful_life_months:
        raise HTTPException(
            status_code=422,
            detail=f'Asset has reached the end of its useful life ({financial.useful_life_months} months)',
        )

    period_amount, accum_after, book_val_after = _calculate_period_depreciation(financial, posted_count)

    entry = AssetDepreciationEntry(
        company_id=company_id,
        asset_id=asset_id,
        period=period,
        period_start_date=period_start,
        period_end_date=period_end,
        depreciation_amount=period_amount,
        accumulated_depreciation_after=accum_after,
        book_value_after=book_val_after,
        method=financial.depreciation_method,
        posted_by_id=user_id,
        notes=notes,
    )
    db.add(entry)

    financial.accumulated_depreciation = accum_after
    financial.current_book_value = book_val_after
    if accum_after >= depreciable_basis:
        financial.financial_status = 'fully_depreciated'

    record_security_event(
        db,
        action='asset_depreciation_posted',
        entity_type='AssetDepreciationEntry',
        entity_id=str(entry.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'asset_id': str(asset_id),
            'asset_number': asset.asset_number,
            'period': period,
            'amount': str(period_amount),
            'accumulated_after': str(accum_after),
            'book_value_after': str(book_val_after),
        },
    )

    try:
        db.commit()
        db.refresh(entry)
    except (IntegrityError, StaleDataError, InvalidRequestError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f'Depreciation for period {period} has already been posted for this asset',
        ) from exc
    return entry


def post_batch_depreciation(
    db: Session,
    company_id: UUID,
    period: str,
    user_id: UUID,
    notes: str | None = None,
) -> BatchDepreciationResult:
    """Authoritative service for posting batch monthly depreciation with transaction atomicity."""
    try:
        parts = period.split('-')
        year = int(parts[0])
        month = int(parts[1])
        if not (1 <= month <= 12):
            raise ValueError()
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail='Period must be formatted as YYYY-MM')

    days_in_month = calendar.monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end = date(year, month, days_in_month)

    # Candidate active financial profiles in this company, ordered by id to prevent deadlocks
    candidates = db.scalars(
        select(AssetFinancial)
        .where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.financial_status == 'active',
        )
        .order_by(AssetFinancial.id.asc())
        .with_for_update()
    ).all()

    processed_count = 0
    posted_count = 0
    skipped_count = 0
    total_posted = Decimal('0.00')
    posted_asset_ids: list[UUID] = []
    skipped_summary: list[dict] = []

    for fin in candidates:
        processed_count += 1
        asset = db.get(Asset, fin.asset_id)
        if asset is None:
            continue

        # Check start date
        if period < fin.depreciation_start_date.strftime('%Y-%m'):
            skipped_count += 1
            skipped_summary.append({
                'asset_id': str(fin.asset_id),
                'asset_number': asset.asset_number,
                'reason': 'period_before_start_date',
            })
            continue

        # Check disposal cutoff
        disposal = db.scalar(
            select(AssetDisposal).where(
                AssetDisposal.company_id == company_id,
                AssetDisposal.asset_id == fin.asset_id,
            )
        )
        if disposal is not None and period > disposal.disposal_date.strftime('%Y-%m'):
            skipped_count += 1
            skipped_summary.append({
                'asset_id': str(fin.asset_id),
                'asset_number': asset.asset_number,
                'reason': 'disposed_prior_to_period',
            })
            continue

        # Check if already posted
        already_posted = db.scalar(
            select(AssetDepreciationEntry.id).where(
                AssetDepreciationEntry.company_id == company_id,
                AssetDepreciationEntry.asset_id == fin.asset_id,
                AssetDepreciationEntry.period == period,
            )
        )
        if already_posted is not None:
            skipped_count += 1
            skipped_summary.append({
                'asset_id': str(fin.asset_id),
                'asset_number': asset.asset_number,
                'reason': 'already_posted',
            })
            continue

        depreciable_basis = fin.capitalised_cost - fin.residual_value
        if depreciable_basis <= Decimal('0.00') or fin.accumulated_depreciation >= depreciable_basis:
            skipped_count += 1
            skipped_summary.append({
                'asset_id': str(fin.asset_id),
                'asset_number': asset.asset_number,
                'reason': 'fully_depreciated_or_zero_basis',
            })
            continue

        posted_entries_count = db.scalar(
            select(func.count(AssetDepreciationEntry.id)).where(
                AssetDepreciationEntry.company_id == company_id,
                AssetDepreciationEntry.asset_id == fin.asset_id,
            )
        ) or 0
        if posted_entries_count >= fin.useful_life_months:
            skipped_count += 1
            skipped_summary.append({
                'asset_id': str(fin.asset_id),
                'asset_number': asset.asset_number,
                'reason': 'useful_life_exhausted',
            })
            continue

        period_amount, accum_after, book_val_after = _calculate_period_depreciation(fin, posted_entries_count)

        entry = AssetDepreciationEntry(
            company_id=company_id,
            asset_id=fin.asset_id,
            period=period,
            period_start_date=period_start,
            period_end_date=period_end,
            depreciation_amount=period_amount,
            accumulated_depreciation_after=accum_after,
            book_value_after=book_val_after,
            method=fin.depreciation_method,
            posted_by_id=user_id,
            notes=notes,
        )
        db.add(entry)

        fin.accumulated_depreciation = accum_after
        fin.current_book_value = book_val_after
        if accum_after >= depreciable_basis:
            fin.financial_status = 'fully_depreciated'

        posted_count += 1
        total_posted += period_amount
        posted_asset_ids.append(fin.asset_id)

    db.commit()

    record_security_event(
        db,
        action='batch_depreciation_posted',
        entity_type='AssetDepreciationEntry',
        entity_id=period,
        actor_id=user_id,
        company_id=company_id,
        changes={
            'period': period,
            'posted_count': posted_count,
            'skipped_count': skipped_count,
            'total_posted': str(total_posted),
        },
    )

    return BatchDepreciationResult(
        period=period,
        processed_count=processed_count,
        posted_count=posted_count,
        skipped_count=skipped_count,
        total_depreciation_posted=total_posted,
        posted_asset_ids=posted_asset_ids,
        skipped=skipped_summary,
    )


def dispose_asset(
    db: Session,
    company_id: UUID,
    asset_id: UUID,
    payload: AssetDisposalCreate,
    user_id: UUID,
) -> AssetDisposal:
    """Authoritative asset retirement/disposal workflow with cutoff enforcement and gain/loss calculation."""
    asset = db.scalar(
        select(Asset)
        .where(Asset.company_id == company_id, Asset.id == asset_id)
        .with_for_update()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail='Asset not found')
    if asset.status == 'disposed':
        raise HTTPException(status_code=409, detail='Asset is already disposed')

    # Guard: Active assignment must be returned before disposal
    active_assignment = db.scalar(
        select(AssetAssignment.id).where(
            AssetAssignment.asset_id == asset_id,
            AssetAssignment.status == 'active',
        )
    )
    if active_assignment is not None:
        raise HTTPException(
            status_code=409,
            detail='The asset has an active assignment. Return the asset before disposing.',
        )

    financial = db.scalar(
        select(AssetFinancial)
        .where(AssetFinancial.company_id == company_id, AssetFinancial.asset_id == asset_id)
        .with_for_update()
    )
    if financial is None:
        financial = get_or_create_financial(db, company_id, asset)
        db.flush()

    # Disposal cutoff validation:
    disposal_cutoff_period = payload.disposal_date.strftime('%Y-%m')
    future_posted = db.scalar(
        select(AssetDepreciationEntry.period).where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
            AssetDepreciationEntry.period > disposal_cutoff_period,
        )
    )
    if future_posted is not None:
        raise HTTPException(
            status_code=422,
            detail=f'Cannot dispose asset on {payload.disposal_date} because depreciation has already been posted for later period {future_posted}',
        )

    nbv_at_disposal = financial.current_book_value
    gain_loss = payload.sale_proceeds - nbv_at_disposal

    disposal = AssetDisposal(
        company_id=company_id,
        asset_id=asset_id,
        disposal_date=payload.disposal_date,
        disposal_reason=payload.disposal_reason,
        disposal_method=payload.disposal_method,
        sale_proceeds=payload.sale_proceeds,
        net_book_value_at_disposal=nbv_at_disposal,
        gain_loss=gain_loss,
        notes=payload.notes,
        disposed_by_id=user_id,
    )
    db.add(disposal)

    old_status = asset.status
    asset.status = 'disposed'
    financial.financial_status = 'disposed'

    record_history(db, asset, 'disposed', 'status', old_status, 'disposed')

    record_security_event(
        db,
        action='asset_disposed',
        entity_type='AssetDisposal',
        entity_id=str(disposal.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'asset_id': str(asset_id),
            'asset_number': asset.asset_number,
            'disposal_date': payload.disposal_date.isoformat(),
            'disposal_reason': payload.disposal_reason,
            'disposal_method': payload.disposal_method,
            'sale_proceeds': str(payload.sale_proceeds),
            'net_book_value_at_disposal': str(nbv_at_disposal),
            'gain_loss': str(gain_loss),
        },
    )

    db.commit()
    db.refresh(disposal)
    return disposal


def update_financial_profile(
    db: Session,
    company_id: UUID,
    asset_id: UUID,
    payload: AssetFinancialUpdate,
    user_id: UUID,
) -> AssetFinancial:
    """Updates financial profile, enforcing historical integrity if depreciation was already posted."""
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    financial = db.scalar(
        select(AssetFinancial)
        .where(AssetFinancial.company_id == company_id, AssetFinancial.asset_id == asset_id)
        .with_for_update()
    )
    if financial is None:
        financial = get_or_create_financial(db, company_id, asset)
        db.flush()

    posted_count = db.scalar(
        select(func.count(AssetDepreciationEntry.id)).where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
        )
    ) or 0

    updates = payload.model_dump(exclude_unset=True)

    if posted_count > 0:
        # Cannot modify core calculation parameters directly once depreciation has been posted
        disallowed_fields = {'capitalised_cost', 'useful_life_months', 'residual_value', 'depreciation_start_date'}
        attempted = [k for k in updates if k in disallowed_fields and updates[k] != getattr(financial, k)]
        if attempted:
            raise HTTPException(
                status_code=409,
                detail=f'Cannot modify {", ".join(attempted)} directly because {posted_count} posted depreciation entries exist. Use prospective adjustment instead.',
            )

    cost = updates.get('capitalised_cost', financial.capitalised_cost)
    residual = updates.get('residual_value', financial.residual_value)
    if residual > cost:
        raise HTTPException(status_code=422, detail='Residual value cannot exceed capitalised cost')

    for field, val in updates.items():
        if val is not None:
            setattr(financial, field, val)

    financial.current_book_value = financial.capitalised_cost - financial.accumulated_depreciation
    if financial.financial_status != 'disposed':
        if financial.current_book_value <= financial.residual_value:
            financial.financial_status = 'fully_depreciated'
        else:
            financial.financial_status = 'active'

    db.commit()
    db.refresh(financial)
    return financial


def adjust_financial_profile(
    db: Session,
    company_id: UUID,
    asset_id: UUID,
    payload: AssetFinancialAdjust,
    user_id: UUID,
) -> AssetFinancial:
    """Prospective adjustment of useful life or residual value without rewriting historical posted entries."""
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    financial = db.scalar(
        select(AssetFinancial)
        .where(AssetFinancial.company_id == company_id, AssetFinancial.asset_id == asset_id)
        .with_for_update()
    )
    if financial is None:
        raise HTTPException(status_code=404, detail='Asset financial profile not found')
    if financial.financial_status == 'disposed':
        raise HTTPException(status_code=409, detail='Cannot adjust financial profile of a disposed asset')

    posted_count = db.scalar(
        select(func.count(AssetDepreciationEntry.id)).where(
            AssetDepreciationEntry.company_id == company_id,
            AssetDepreciationEntry.asset_id == asset_id,
        )
    ) or 0

    changes = {}
    if payload.useful_life_months is not None:
        if payload.useful_life_months < posted_count:
            raise HTTPException(
                status_code=422,
                detail=f'Useful life ({payload.useful_life_months} months) cannot be less than already posted periods ({posted_count})',
            )
        changes['useful_life_months'] = {'old': financial.useful_life_months, 'new': payload.useful_life_months}
        financial.useful_life_months = payload.useful_life_months

    if payload.residual_value is not None:
        if payload.residual_value > financial.current_book_value:
            raise HTTPException(
                status_code=422,
                detail=f'Revised residual value ({payload.residual_value}) cannot exceed current net book value ({financial.current_book_value})',
            )
        changes['residual_value'] = {'old': str(financial.residual_value), 'new': str(payload.residual_value)}
        financial.residual_value = payload.residual_value

    record_security_event(
        db,
        action='asset_financial_adjusted',
        entity_type='AssetFinancial',
        entity_id=str(financial.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'asset_id': str(asset_id),
            'notes': payload.notes,
            **changes,
        },
    )

    db.commit()
    db.refresh(financial)
    return financial

