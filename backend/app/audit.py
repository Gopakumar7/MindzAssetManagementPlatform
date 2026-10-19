from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetDepartmentUsage,
    AssetHistory,
    AssetNumberRule,
    AssetServiceContract,
    AuditEvent,
    Company,
    CompanyMembership,
    CostCenter,
    Department,
    GoodsReceipt,
    GoodsReceiptLine,
    Location,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    Site,
    Supplier,
    SystemRoleAssignment,
    User,
    UserInvitation,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
    VerificationUnregisteredAsset,
)

_AUDITED_FIELDS: dict[type, tuple[str, ...]] = {
    Company: ('code', 'name', 'is_active'),
    Department: ('company_id', 'code', 'name', 'is_active'),
    Site: ('company_id', 'code', 'name', 'is_active'),
    Location: ('company_id', 'site_id', 'code', 'name', 'is_active'),
    CostCenter: ('company_id', 'code', 'name', 'is_active'),
    AssetCategory: ('company_id', 'code', 'name', 'description', 'is_active'),
    AssetNumberRule: ('company_id', 'category_id', 'prefix', 'separator', 'padding'),
    Asset: (
        'company_id', 'category_id', 'asset_number', 'serial_number', 'manufacturer',
        'model', 'acquisition_date', 'acquisition_cost', 'status', 'site_id',
        'location_id', 'responsible_department_id', 'cost_center_id', 'warranty_start',
        'warranty_end', 'goods_receipt_line_id',
    ),
    Supplier: ('company_id', 'code', 'name', 'email', 'phone', 'notes', 'is_active'),
    PurchaseOrder: (
        'company_id', 'supplier_id', 'order_number', 'status', 'ordered_date',
        'expected_date', 'notes',
    ),
    PurchaseOrderLine: (
        'company_id', 'purchase_order_id', 'category_id', 'description',
        'quantity_ordered', 'unit_cost',
    ),
    GoodsReceipt: (
        'company_id', 'purchase_order_id', 'receipt_number', 'received_date',
        'delivery_reference', 'notes',
    ),
    GoodsReceiptLine: (
        'company_id', 'goods_receipt_id', 'purchase_order_id',
        'purchase_order_line_id', 'quantity_received', 'quantity_rejected',
        'discrepancy_notes',
    ),
    AssetServiceContract: (
        'company_id', 'asset_id', 'supplier_id', 'contract_type', 'provider_name',
        'reference_number', 'start_date', 'end_date', 'coverage_description',
        'support_contact', 'status',
    ),
    MaintenanceRequest: (
        'company_id', 'asset_id', 'requester_id', 'assignee_id', 'title',
        'priority', 'status', 'reported_date', 'diagnosis', 'work_performed',
        'resolution_notes', 'completed_date', 'cost',
    ),
    AssetDepartmentUsage: ('company_id', 'asset_id', 'department_id', 'purpose', 'started_at', 'ended_at'),
    AssetHistory: ('company_id', 'asset_id', 'event_type', 'field_name', 'old_value', 'new_value'),
    AssetAssignment: (
        'company_id', 'asset_id', 'recipient_id', 'responsible_department_id', 'location_id',
        'effective_date', 'status', 'notes', 'reference', 'handover_date', 'handover_condition',
        'included_items', 'acknowledgement', 'handover_notes', 'ended_at', 'return_date',
        'return_condition', 'return_notes', 'issue_details', 'next_asset_status', 'transfer_reason',
        'previous_assignment_id',
    ),
    User: ('email', 'is_active'),
    CompanyMembership: ('company_id', 'user_id', 'role_id', 'status'),
    SystemRoleAssignment: ('user_id', 'role_id'),
    Role: ('code', 'name', 'scope'),
    UserInvitation: ('membership_id', 'expires_at', 'accepted_at', 'revoked_at'),
    VerificationCampaign: (
        'company_id', 'campaign_reference', 'name', 'status', 'start_date', 'end_date',
        'started_at', 'completed_at', 'closed_by_id',
    ),
    VerificationExpectedAsset: (
        'company_id', 'campaign_id', 'asset_id', 'expected_site_id', 'expected_location_id',
        'expected_department_id', 'expected_custodian_id', 'expected_condition', 'expected_status',
    ),
    VerificationObservation: (
        'company_id', 'campaign_id', 'expected_asset_id', 'asset_id', 'is_found',
        'actual_site_id', 'actual_location_id', 'actual_department_id', 'actual_custodian_id',
        'observed_condition', 'verification_date', 'verified_by_id', 'remarks',
    ),
    VerificationDiscrepancy: (
        'company_id', 'campaign_id', 'observation_id', 'expected_asset_id', 'asset_id',
        'discrepancy_type', 'status', 'resolution_action', 'resolution_notes', 'resolved_by_id',
        'resolved_at',
    ),
    VerificationUnregisteredAsset: (
        'company_id', 'campaign_id', 'serial_number', 'description', 'category_id',
        'site_id', 'location_id', 'custodian_id', 'observed_condition', 'status',
        'registered_asset_id',
    ),
}


def _json_value(value):
    if isinstance(value, (UUID, date, datetime, Decimal, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def record_security_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_id: UUID | None = None,
    company_id: UUID | None = None,
    outcome: str = 'success',
    changes: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            occurred_at=datetime.now(timezone.utc),
            actor_id=actor_id if actor_id is not None else db.info.get('audit_actor_id'),
            company_id=company_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            outcome=outcome,
            request_id=db.info.get('audit_request_id'),
            changes=changes,
        )
    )


def _company_id(entity) -> UUID | None:
    if isinstance(entity, Company):
        return entity.id
    return getattr(entity, 'company_id', None)


@event.listens_for(Session, 'before_commit')
def audit_unit_of_work(db: Session) -> None:
    if db.info.get('audit_in_progress'):
        return

    candidates = [
        entity
        for entity in (*db.new, *db.dirty, *db.deleted)
        if type(entity) in _AUDITED_FIELDS and not isinstance(entity, AuditEvent)
    ]
    if not candidates:
        return

    snapshots = []
    for entity in candidates:
        state = inspect(entity)
        before = {}
        after = {}
        is_new = entity in db.new
        is_deleted = entity in db.deleted
        for field in _AUDITED_FIELDS[type(entity)]:
            history = state.attrs[field].history
            current = getattr(entity, field)
            if is_new:
                after[field] = _json_value(current)
            elif is_deleted:
                before[field] = _json_value(current)
            elif history.has_changes():
                old = history.deleted[0] if history.deleted else None
                before[field] = _json_value(old)
                after[field] = _json_value(current)
        if is_new or is_deleted or before or after:
            snapshots.append((entity, is_new, is_deleted, before, after))

    if not snapshots:
        return

    db.info['audit_in_progress'] = True
    try:
        db.flush()
        for entity, is_new, is_deleted, before, after in snapshots:
            action = 'created' if is_new else 'deleted' if is_deleted else 'updated'
            changes = {'before': before, 'after': after}
            record_security_event(
                db,
                action=action,
                entity_type=type(entity).__name__,
                entity_id=str(getattr(entity, 'id', None) or getattr(entity, 'membership_id', '')),
                company_id=_company_id(entity),
                changes=changes,
            )
    finally:
        db.info.pop('audit_in_progress', None)


@event.listens_for(Session, 'before_flush')
def prevent_audit_mutation(db: Session, _flush_context, _instances) -> None:
    if any(isinstance(item, AuditEvent) for item in (*db.dirty, *db.deleted)):
        raise ValueError('Audit events are append-only')
