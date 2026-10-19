from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.audit import record_security_event
from app.models import (
    Asset,
    AssetAlert,
    AssetDepreciationEntry,
    AssetFinancial,
    AssetServiceContract,
    CompanyMembership,
    MaintenanceRequest,
    PurchaseOrder,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
)
from app.schemas import (
    AlertAcknowledgeRequest,
    AlertAssignRequest,
    AlertDismissRequest,
    AlertResolveRequest,
    AlertSyncResponse,
    AssetAlertRead,
    AssetAlertSummary,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sync_company_alerts(
    db: Session,
    company_id: UUID,
    current_date: date | None = None,
) -> AlertSyncResponse:
    """Evaluates all 8 alert rules for a company, reconciles active alerts, and auto-resolves cleared alerts."""
    today = current_date or date.today()
    candidate_map: dict[tuple[str, str, UUID], dict[str, Any]] = {}

    # 1. Warranty Expiry & 2. AMC Expiry
    contracts = db.execute(
        select(AssetServiceContract, Asset.asset_number)
        .join(Asset, (Asset.company_id == AssetServiceContract.company_id) & (Asset.id == AssetServiceContract.asset_id))
        .where(
            AssetServiceContract.company_id == company_id,
            AssetServiceContract.status == 'active',
        )
    ).all()

    for contract, asset_number in contracts:
        days_until_expiry = (contract.end_date - today).days
        if days_until_expiry <= 30:
            is_expired = contract.end_date < today
            days_overdue = (today - contract.end_date).days
            rule_type = 'warranty_expiry' if contract.contract_type == 'warranty' else 'amc_expiry'
            label = 'Warranty' if contract.contract_type == 'warranty' else 'AMC'
            severity = 'critical' if is_expired else 'warning'
            ref = contract.reference_number or contract.provider_name or str(contract.id)[:8]
            title = f"{label} Expired: {asset_number}" if is_expired else f"{label} Expiring Soon: {asset_number}"
            desc = (
                f"{label} contract '{ref}' for asset {asset_number} expired on {contract.end_date.isoformat()} ({days_overdue} days ago)."
                if is_expired
                else f"{label} contract '{ref}' for asset {asset_number} expires on {contract.end_date.isoformat()} ({days_until_expiry} days remaining)."
            )
            key = (rule_type, 'service_contract', contract.id)
            candidate_map[key] = {
                'alert_type': rule_type,
                'severity': severity,
                'title': title,
                'description': desc,
                'entity_type': 'service_contract',
                'entity_id': contract.id,
                'entity_reference': ref,
                'asset_id': contract.asset_id,
                'due_date': contract.end_date,
                'days_overdue': days_overdue,
                'responsible_user_id': None,
                'target_route': 'assets',
            }

    # 3. Maintenance Overdue / SLA Approaching
    maint_sla_days = {'urgent': 2, 'high': 5, 'normal': 14, 'low': 30}
    maintenance_records = db.execute(
        select(MaintenanceRequest, Asset.asset_number)
        .join(Asset, (Asset.company_id == MaintenanceRequest.company_id) & (Asset.id == MaintenanceRequest.asset_id))
        .where(
            MaintenanceRequest.company_id == company_id,
            MaintenanceRequest.status.in_(['open', 'in_progress']),
        )
    ).all()

    for req, asset_number in maintenance_records:
        sla_days = maint_sla_days.get(req.priority, 14)
        due_date = req.reported_date + timedelta(days=sla_days)
        days_overdue = (today - due_date).days
        days_until_due = (due_date - today).days

        if days_overdue > 0 or days_until_due <= 2:
            is_overdue = days_overdue > 0
            severity = (
                'critical'
                if (is_overdue and (req.priority in ('urgent', 'high') or days_overdue > 3))
                else 'warning'
            )
            title = (
                f"Maintenance Overdue ({req.priority.capitalize()}): {req.title}"
                if is_overdue
                else f"Maintenance SLA Approaching: {req.title}"
            )
            desc = (
                f"Maintenance ticket '{req.title}' for asset {asset_number} was reported on {req.reported_date.isoformat()} and is overdue by {days_overdue} days."
                if is_overdue
                else f"Maintenance ticket '{req.title}' for asset {asset_number} was reported on {req.reported_date.isoformat()} and is due in {days_until_due} day(s)."
            )
            key = ('maintenance_overdue', 'maintenance_request', req.id)
            candidate_map[key] = {
                'alert_type': 'maintenance_overdue',
                'severity': severity,
                'title': title,
                'description': desc,
                'entity_type': 'maintenance_request',
                'entity_id': req.id,
                'entity_reference': req.title,
                'asset_id': req.asset_id,
                'due_date': due_date,
                'days_overdue': days_overdue,
                'responsible_user_id': req.assignee_id,
                'target_route': 'maintenance',
            }

    # 4. Physical Verification Discrepancies
    discrepancies = db.scalars(
        select(VerificationDiscrepancy).where(
            VerificationDiscrepancy.company_id == company_id,
            VerificationDiscrepancy.status == 'open',
        )
    ).all()

    for disc in discrepancies:
        created_date = disc.created_at.date() if disc.created_at else today
        age_days = (today - created_date).days
        target_resolution_date = created_date + timedelta(days=7)
        days_overdue = (today - target_resolution_date).days

        if disc.discrepancy_type in ('missing', 'unregistered_asset') or age_days >= 7:
            severity = (
                'critical'
                if (disc.discrepancy_type in ('missing', 'unregistered_asset') or age_days >= 14)
                else 'warning'
            )
            disc_label = disc.discrepancy_type.replace('_', ' ').title()
            title = f"Unresolved Discrepancy ({disc_label}): {disc.notes or 'Investigation needed'}"
            desc = f"Physical verification discrepancy '{disc_label}' has been open for {age_days} days without resolution."
            key = ('verification_discrepancy', 'verification_discrepancy', disc.id)
            candidate_map[key] = {
                'alert_type': 'verification_discrepancy',
                'severity': severity,
                'title': title,
                'description': desc,
                'entity_type': 'verification_discrepancy',
                'entity_id': disc.id,
                'entity_reference': disc_label,
                'asset_id': disc.asset_id,
                'due_date': target_resolution_date,
                'days_overdue': days_overdue,
                'responsible_user_id': None,
                'target_route': 'verification',
            }

    # 5. Verification Campaign Due
    campaigns = db.scalars(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company_id,
            VerificationCampaign.status.in_(['in_progress', 'under_review']),
        )
    ).all()

    for camp in campaigns:
        days_overdue = (today - camp.end_date).days
        days_until_end = (camp.end_date - today).days

        if camp.end_date < today or days_until_end <= 7:
            is_overdue = camp.end_date < today
            severity = 'critical' if is_overdue else 'warning'
            title = (
                f"Verification Campaign Overdue: {camp.name}"
                if is_overdue
                else f"Verification Campaign Ending Soon: {camp.name}"
            )
            desc = (
                f"Campaign '{camp.campaign_reference}' ({camp.name}) ended on {camp.end_date.isoformat()} and is overdue by {days_overdue} days."
                if is_overdue
                else f"Campaign '{camp.campaign_reference}' ({camp.name}) ends on {camp.end_date.isoformat()} ({days_until_end} days remaining)."
            )
            key = ('verification_campaign_due', 'verification_campaign', camp.id)
            candidate_map[key] = {
                'alert_type': 'verification_campaign_due',
                'severity': severity,
                'title': title,
                'description': desc,
                'entity_type': 'verification_campaign',
                'entity_id': camp.id,
                'entity_reference': camp.campaign_reference,
                'asset_id': None,
                'due_date': camp.end_date,
                'days_overdue': days_overdue,
                'responsible_user_id': camp.created_by_id,
                'target_route': 'verification',
            }

    # 6. Fully Depreciated Assets In Service
    fully_depreciated = db.execute(
        select(AssetFinancial, Asset)
        .join(Asset, (Asset.company_id == AssetFinancial.company_id) & (Asset.id == AssetFinancial.asset_id))
        .where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.financial_status == 'fully_depreciated',
            Asset.status != 'disposed',
        )
    ).all()

    for fin, asset in fully_depreciated:
        key = ('fully_depreciated_in_use', 'asset_financial', fin.id)
        candidate_map[key] = {
            'alert_type': 'fully_depreciated_in_use',
            'severity': 'warning',
            'title': f"Fully Depreciated Asset In Active Service: {asset.asset_number}",
            'description': f"Asset {asset.asset_number} has reached residual value ({fin.current_book_value} {fin.currency}) but remains active in status '{asset.status}'.",
            'entity_type': 'asset_financial',
            'entity_id': fin.id,
            'entity_reference': asset.asset_number,
            'asset_id': asset.id,
            'due_date': None,
            'days_overdue': None,
            'responsible_user_id': None,
            'target_route': 'assets',
        }

    # 7. Approaching End of Useful Life
    active_financials = db.execute(
        select(AssetFinancial, Asset)
        .join(Asset, (Asset.company_id == AssetFinancial.company_id) & (Asset.id == AssetFinancial.asset_id))
        .where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.financial_status == 'active',
            Asset.status != 'disposed',
        )
    ).all()

    for fin, asset in active_financials:
        posted_count = db.scalar(
            select(func.count(AssetDepreciationEntry.id)).where(
                AssetDepreciationEntry.company_id == company_id,
                AssetDepreciationEntry.asset_id == fin.asset_id,
            )
        ) or 0
        remaining_months = fin.useful_life_months - posted_count
        if 0 < remaining_months <= 3:
            key = ('approaching_eol', 'asset_financial', fin.id)
            candidate_map[key] = {
                'alert_type': 'approaching_eol',
                'severity': 'warning' if remaining_months <= 1 else 'info',
                'title': f"Approaching End of Useful Life: {asset.asset_number} ({remaining_months} months remaining)",
                'description': f"Asset {asset.asset_number} has {remaining_months} month(s) of useful life remaining before reaching residual value.",
                'entity_type': 'asset_financial',
                'entity_id': fin.id,
                'entity_reference': asset.asset_number,
                'asset_id': asset.id,
                'due_date': None,
                'days_overdue': None,
                'responsible_user_id': None,
                'target_route': 'assets',
            }

    # 8. Purchase Order Delivery Overdue
    pos = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status.in_(['open', 'partially_received']),
            PurchaseOrder.expected_date.is_not(None),
            PurchaseOrder.expected_date < today,
        )
    ).all()

    for po in pos:
        days_overdue = (today - po.expected_date).days
        severity = 'critical' if days_overdue > 7 else 'warning'
        key = ('purchase_order_overdue', 'purchase_order', po.id)
        candidate_map[key] = {
            'alert_type': 'purchase_order_overdue',
            'severity': severity,
            'title': f"Purchase Order Delivery Overdue: {po.order_number}",
            'description': f"PO {po.order_number} was expected on {po.expected_date.isoformat()} ({days_overdue} days ago) with status '{po.status}'.",
            'entity_type': 'purchase_order',
            'entity_id': po.id,
            'entity_reference': po.order_number,
            'asset_id': None,
            'due_date': po.expected_date,
            'days_overdue': days_overdue,
            'responsible_user_id': None,
            'target_route': 'procurement',
        }

    # Fetch existing active alerts for reconciliation
    active_alerts = db.scalars(
        select(AssetAlert)
        .where(
            AssetAlert.company_id == company_id,
            AssetAlert.status.in_(['open', 'acknowledged']),
        )
        .with_for_update()
    ).all()

    active_map = {(a.alert_type, a.entity_type, a.entity_id): a for a in active_alerts}

    # Check previously handled alerts (manually resolved or dismissed) to avoid recreating them
    handled_records = db.scalars(
        select(AssetAlert).where(
            AssetAlert.company_id == company_id,
            AssetAlert.status.in_(['resolved', 'dismissed']),
            AssetAlert.resolution_reason.in_(['manual_resolution', 'dismissed']),
        )
    ).all()
    handled_keys = {(a.alert_type, a.entity_type, a.entity_id) for a in handled_records}

    created_count = 0
    updated_count = 0
    auto_resolved_count = 0

    # Reconcile candidates
    for key, c in candidate_map.items():
        if key in active_map:
            existing = active_map[key]
            existing.severity = c['severity']
            existing.title = c['title']
            existing.description = c['description']
            existing.due_date = c['due_date']
            existing.days_overdue = c['days_overdue']
            existing.entity_reference = c['entity_reference']
            existing.target_route = c['target_route']
            if existing.responsible_user_id is None and c['responsible_user_id'] is not None:
                existing.responsible_user_id = c['responsible_user_id']
            updated_count += 1
        elif key in handled_keys:
            # User explicitly resolved or dismissed this alert; do not resurrect
            continue
        else:
            new_alert = AssetAlert(
                company_id=company_id,
                alert_type=c['alert_type'],
                severity=c['severity'],
                status='open',
                title=c['title'],
                description=c['description'],
                entity_type=c['entity_type'],
                entity_id=c['entity_id'],
                entity_reference=c['entity_reference'],
                asset_id=c['asset_id'],
                due_date=c['due_date'],
                days_overdue=c['days_overdue'],
                responsible_user_id=c['responsible_user_id'],
                target_route=c['target_route'],
            )
            db.add(new_alert)
            created_count += 1

    # Auto-resolve orphaned active alerts whose condition has cleared
    now_utc = _utc_now()
    for key, existing in active_map.items():
        if key not in candidate_map:
            existing.status = 'resolved'
            existing.resolution_reason = 'source_resolved'
            existing.resolved_at = now_utc
            existing.resolution_notes = 'Underlying condition resolved or no longer active.'
            auto_resolved_count += 1

    db.commit()

    active_count = db.scalar(
        select(func.count(AssetAlert.id)).where(
            AssetAlert.company_id == company_id,
            AssetAlert.status.in_(['open', 'acknowledged']),
        )
    ) or 0

    return AlertSyncResponse(
        synced=True,
        created_count=created_count,
        updated_count=updated_count,
        auto_resolved_count=auto_resolved_count,
        active_count=active_count,
    )


def get_alert_summary(db: Session, company_id: UUID) -> AssetAlertSummary:
    """Returns aggregated summary metrics of active and historical alerts."""
    status_counts = dict(
        db.execute(
            select(AssetAlert.status, func.count(AssetAlert.id))
            .where(AssetAlert.company_id == company_id)
            .group_by(AssetAlert.status)
        ).all()
    )

    severity_counts = dict(
        db.execute(
            select(AssetAlert.severity, func.count(AssetAlert.id))
            .where(
                AssetAlert.company_id == company_id,
                AssetAlert.status.in_(['open', 'acknowledged']),
            )
            .group_by(AssetAlert.severity)
        ).all()
    )

    type_counts = dict(
        db.execute(
            select(AssetAlert.alert_type, func.count(AssetAlert.id))
            .where(
                AssetAlert.company_id == company_id,
                AssetAlert.status.in_(['open', 'acknowledged']),
            )
            .group_by(AssetAlert.alert_type)
        ).all()
    )

    return AssetAlertSummary(
        total_open=status_counts.get('open', 0),
        total_acknowledged=status_counts.get('acknowledged', 0),
        total_resolved=status_counts.get('resolved', 0),
        total_dismissed=status_counts.get('dismissed', 0),
        critical_count=severity_counts.get('critical', 0),
        warning_count=severity_counts.get('warning', 0),
        info_count=severity_counts.get('info', 0),
        by_type=type_counts,
    )


def get_alerts(
    db: Session,
    company_id: UUID,
    status_filter: str | None = None,
    severity: str | None = None,
    alert_type: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AssetAlertRead]:
    """Queries alerts for a company with filters, joins actor emails, and returns structured models."""
    resp_user = aliased(User, name='resp_user')
    ack_user = aliased(User, name='ack_user')
    res_user = aliased(User, name='res_user')

    stmt = (
        select(
            AssetAlert,
            resp_user.email.label('responsible_user_email'),
            ack_user.email.label('acknowledged_by_email'),
            res_user.email.label('resolved_by_email'),
        )
        .outerjoin(resp_user, resp_user.id == AssetAlert.responsible_user_id)
        .outerjoin(ack_user, ack_user.id == AssetAlert.acknowledged_by_id)
        .outerjoin(res_user, res_user.id == AssetAlert.resolved_by_id)
        .where(AssetAlert.company_id == company_id)
    )

    if status_filter:
        stmt = stmt.where(AssetAlert.status == status_filter)
    if severity:
        stmt = stmt.where(AssetAlert.severity == severity)
    if alert_type:
        stmt = stmt.where(AssetAlert.alert_type == alert_type)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                AssetAlert.title.ilike(term),
                AssetAlert.description.ilike(term),
                AssetAlert.entity_reference.ilike(term),
            )
        )

    # Order priority: active first, then severity (critical -> warning -> info), then created_at desc
    active_order = case(
        (AssetAlert.status.in_(['open', 'acknowledged']), 0),
        else_=1,
    )
    severity_order = case(
        (AssetAlert.severity == 'critical', 0),
        (AssetAlert.severity == 'warning', 1),
        else_=2,
    )

    stmt = stmt.order_by(
        active_order,
        severity_order,
        AssetAlert.created_at.desc(),
    ).offset(offset).limit(limit)

    rows = db.execute(stmt).all()
    results: list[AssetAlertRead] = []
    for alert, resp_email, ack_email, res_email in rows:
        item = AssetAlertRead.model_validate(alert)
        item.responsible_user_email = resp_email
        item.acknowledged_by_email = ack_email
        item.resolved_by_email = res_email
        results.append(item)

    return results


def _alert_to_read(db: Session, alert: AssetAlert) -> AssetAlertRead:
    resp_email = (
        db.scalar(select(User.email).where(User.id == alert.responsible_user_id))
        if alert.responsible_user_id
        else None
    )
    ack_email = (
        db.scalar(select(User.email).where(User.id == alert.acknowledged_by_id))
        if alert.acknowledged_by_id
        else None
    )
    res_email = (
        db.scalar(select(User.email).where(User.id == alert.resolved_by_id))
        if alert.resolved_by_id
        else None
    )
    read_obj = AssetAlertRead.model_validate(alert)
    read_obj.responsible_user_email = resp_email
    read_obj.acknowledged_by_email = ack_email
    read_obj.resolved_by_email = res_email
    return read_obj


def acknowledge_alert(
    db: Session,
    company_id: UUID,
    alert_id: UUID,
    user_id: UUID,
    payload: AlertAcknowledgeRequest,
) -> AssetAlertRead:
    """Acknowledges an active alert, marking it acknowledged and recording the timestamp."""
    alert = db.scalar(
        select(AssetAlert)
        .where(AssetAlert.company_id == company_id, AssetAlert.id == alert_id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Alert not found')
    if alert.status not in ('open', 'acknowledged'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Cannot acknowledge an alert with status {alert.status}',
        )

    alert.status = 'acknowledged'
    alert.acknowledged_at = _utc_now()
    alert.acknowledged_by_id = user_id
    if payload.notes:
        alert.resolution_notes = payload.notes

    record_security_event(
        db,
        action='asset_alert.acknowledged',
        entity_type='AssetAlert',
        entity_id=str(alert.id),
        actor_id=user_id,
        company_id=company_id,
        changes={'status': 'acknowledged', 'notes': payload.notes},
    )

    db.commit()
    db.refresh(alert)
    return _alert_to_read(db, alert)


def assign_alert(
    db: Session,
    company_id: UUID,
    alert_id: UUID,
    user_id: UUID,
    payload: AlertAssignRequest,
) -> AssetAlertRead:
    """Assigns an alert to a company member."""
    alert = db.scalar(
        select(AssetAlert)
        .where(AssetAlert.company_id == company_id, AssetAlert.id == alert_id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Alert not found')

    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.user_id == payload.responsible_user_id,
            CompanyMembership.status == 'active',
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Assigned user is not an active member of this company',
        )

    old_assignee = str(alert.responsible_user_id) if alert.responsible_user_id else None
    alert.responsible_user_id = payload.responsible_user_id

    record_security_event(
        db,
        action='asset_alert.assigned',
        entity_type='AssetAlert',
        entity_id=str(alert.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'responsible_user_id': {
                'old': old_assignee,
                'new': str(payload.responsible_user_id),
            }
        },
    )

    db.commit()
    db.refresh(alert)
    return _alert_to_read(db, alert)


def resolve_alert(
    db: Session,
    company_id: UUID,
    alert_id: UUID,
    user_id: UUID,
    payload: AlertResolveRequest,
) -> AssetAlertRead:
    """Manually resolves an alert with audit trail and resolution notes."""
    alert = db.scalar(
        select(AssetAlert)
        .where(AssetAlert.company_id == company_id, AssetAlert.id == alert_id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Alert not found')
    if alert.status == 'resolved':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Alert is already resolved',
        )

    alert.status = 'resolved'
    alert.resolved_at = _utc_now()
    alert.resolved_by_id = user_id
    alert.resolution_reason = payload.resolution_reason
    alert.resolution_notes = payload.resolution_notes

    record_security_event(
        db,
        action='asset_alert.resolved',
        entity_type='AssetAlert',
        entity_id=str(alert.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'status': 'resolved',
            'resolution_reason': payload.resolution_reason,
            'notes': payload.resolution_notes,
        },
    )

    db.commit()
    db.refresh(alert)
    return _alert_to_read(db, alert)


def dismiss_alert(
    db: Session,
    company_id: UUID,
    alert_id: UUID,
    user_id: UUID,
    payload: AlertDismissRequest,
) -> AssetAlertRead:
    """Dismisses an alert, removing it from active attention with audit logging."""
    alert = db.scalar(
        select(AssetAlert)
        .where(AssetAlert.company_id == company_id, AssetAlert.id == alert_id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Alert not found')
    if alert.status == 'dismissed':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Alert is already dismissed',
        )

    alert.status = 'dismissed'
    alert.resolved_at = _utc_now()
    alert.resolved_by_id = user_id
    alert.resolution_reason = 'dismissed'
    alert.resolution_notes = payload.resolution_notes

    record_security_event(
        db,
        action='asset_alert.dismissed',
        entity_type='AssetAlert',
        entity_id=str(alert.id),
        actor_id=user_id,
        company_id=company_id,
        changes={
            'status': 'dismissed',
            'resolution_reason': 'dismissed',
            'notes': payload.resolution_notes,
        },
    )

    db.commit()
    db.refresh(alert)
    return _alert_to_read(db, alert)

