"""Milestone 2C.4: External ERP Purchase Order Ingestion Service.

Provides an optional, secure, idempotent external Purchase Order ingestion workflow.
Internal PO creation remains completely independent and continues using ReferenceNumberService.
External PO ingestion never consumes internal PO sequence numbers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.models import (
    AssetCategory,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.schemas import (
    ExternalPurchaseOrderImportPayload,
    PurchaseOrderRead,
)
from app.services import recalculate_purchase_order_status


@dataclass(frozen=True)
class TrustedErpIntegration:
    source_system: str
    source_instance_id: str
    display_prefix: str
    description: str = ""
    is_active: bool = True
    company_id: UUID | None = None


# Default trusted enterprise ERP systems and instances supported by MindZen
DEFAULT_TRUSTED_INTEGRATIONS: dict[tuple[str, str], TrustedErpIntegration] = {
    ('SAP', 'SAP-PROD-01'): TrustedErpIntegration(
        source_system='SAP',
        source_instance_id='SAP-PROD-01',
        display_prefix='SAP',
        description='Production SAP S/4HANA ERP Instance',
    ),
    ('SAP', 'SAP-EU-01'): TrustedErpIntegration(
        source_system='SAP',
        source_instance_id='SAP-EU-01',
        display_prefix='SAP-EU',
        description='European SAP ECC Instance',
    ),
    ('NETSUITE', 'NS-PROD-01'): TrustedErpIntegration(
        source_system='NETSUITE',
        source_instance_id='NS-PROD-01',
        display_prefix='NS',
        description='Production NetSuite ERP Instance',
    ),
    ('ORACLE', 'ORA-PROD-01'): TrustedErpIntegration(
        source_system='ORACLE',
        source_instance_id='ORA-PROD-01',
        display_prefix='ORA',
        description='Production Oracle Fusion Cloud ERP Instance',
    ),
    ('DYNAMICS', 'DYN-PROD-01'): TrustedErpIntegration(
        source_system='DYNAMICS',
        source_instance_id='DYN-PROD-01',
        display_prefix='DYN',
        description='Production Microsoft Dynamics 365 Finance Instance',
    ),
}

# In-memory registry for company-specific or dynamic trusted integrations
_DYNAMIC_INTEGRATIONS: dict[tuple[UUID | None, str, str], TrustedErpIntegration] = {}


def register_trusted_integration(
    source_system: str,
    source_instance_id: str,
    display_prefix: str,
    *,
    company_id: UUID | None = None,
    description: str = "",
    is_active: bool = True,
) -> None:
    """Register or override a trusted integration configuration."""
    clean_sys = source_system.strip().upper()
    clean_inst = source_instance_id.strip()
    clean_pfx = display_prefix.strip().upper()
    _DYNAMIC_INTEGRATIONS[(company_id, clean_sys, clean_inst)] = TrustedErpIntegration(
        source_system=clean_sys,
        source_instance_id=clean_inst,
        display_prefix=clean_pfx,
        description=description,
        is_active=is_active,
        company_id=company_id,
    )


def clear_dynamic_integrations() -> None:
    """Clear dynamic integrations (used in testing cleanup)."""
    _DYNAMIC_INTEGRATIONS.clear()


def get_trusted_integration(
    company_id: UUID, source_system: str, source_instance_id: str | None = None
) -> TrustedErpIntegration | None:
    """
    Look up a trusted ERP integration for a company.
    First checks company-specific registrations, then falls back to platform defaults.
    """
    clean_sys = source_system.strip().upper() if source_system else ""
    clean_inst = source_instance_id.strip() if source_instance_id else ""

    if clean_inst:
        # 1. Company-specific dynamic registration
        if (company_id, clean_sys, clean_inst) in _DYNAMIC_INTEGRATIONS:
            integ = _DYNAMIC_INTEGRATIONS[(company_id, clean_sys, clean_inst)]
            return integ if integ.is_active else None

        # 2. Global dynamic registration
        if (None, clean_sys, clean_inst) in _DYNAMIC_INTEGRATIONS:
            integ = _DYNAMIC_INTEGRATIONS[(None, clean_sys, clean_inst)]
            return integ if integ.is_active else None

        # 3. Platform default registrations
        if (clean_sys, clean_inst) in DEFAULT_TRUSTED_INTEGRATIONS:
            integ = DEFAULT_TRUSTED_INTEGRATIONS[(clean_sys, clean_inst)]
            return integ if integ.is_active else None

    # Fallback if source_instance_id not specified or not matched by exact instance
    for (cid, sys_name, inst_id), integ in _DYNAMIC_INTEGRATIONS.items():
        if cid == company_id and sys_name == clean_sys and integ.is_active:
            return integ

    for (cid, sys_name, inst_id), integ in _DYNAMIC_INTEGRATIONS.items():
        if cid is None and sys_name == clean_sys and integ.is_active:
            return integ

    for (sys_name, inst_id), integ in DEFAULT_TRUSTED_INTEGRATIONS.items():
        if sys_name == clean_sys and integ.is_active:
            return integ

    return None


def compute_payload_hash(payload_data: dict[str, Any]) -> str:
    """
    Compute a deterministic SHA-256 hash of the canonical incoming payload.
    """
    canonical_json = json.dumps(payload_data, sort_keys=True, default=str)
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def derive_display_order_number(display_prefix: str, external_reference: str) -> str:
    """
    Derive the unique MindZen display order number using the trusted source prefix.
    Ensures prefix is uppercase and prevents double-prefixing.
    """
    clean_ref = external_reference.strip()
    prefix_upper = display_prefix.strip().upper()
    prefix_check = f"{prefix_upper}-"
    if clean_ref.upper().startswith(prefix_check):
        suffix = clean_ref[len(prefix_check):]
        return f"{prefix_upper}-{suffix}"
    return f"{prefix_upper}-{clean_ref}"


def normalize_datetime(dt: datetime | None) -> datetime | None:
    """Normalize datetime to timezone-aware UTC datetime for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def import_external_purchase_order(
    db: Session,
    company_id: UUID,
    payload: ExternalPurchaseOrderImportPayload,
    actor_id: UUID,
) -> tuple[PurchaseOrder, bool]:
    """
    Execute an atomic, idempotent ingestion of an external ERP Purchase Order.
    Returns a tuple of (PurchaseOrder, is_created: bool).
    """
    # 1. Validate trusted integration configuration
    trusted_config = get_trusted_integration(
        company_id, payload.source_system, payload.source_instance_id
    )
    if trusted_config is None or not trusted_config.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Untrusted integration: source_system '{payload.source_system}' and "
                f"source_instance_id '{payload.source_instance_id}' are not configured as "
                "a trusted ERP integration for this company"
            ),
        )

    # 2. Validate supplier mapping
    sup_code = payload.supplier_external_code or payload.supplier_code
    if payload.supplier_id:
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.company_id == company_id,
                Supplier.id == payload.supplier_id,
                Supplier.is_active.is_(True),
            )
        )
    elif sup_code:
        supplier = db.scalar(
            select(Supplier).where(
                Supplier.company_id == company_id,
                Supplier.code == sup_code.strip(),
                Supplier.is_active.is_(True),
            )
        )
    else:
        supplier = None

    if supplier is None:
        identifier = sup_code or payload.supplier_id
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Supplier mapping failed: Active supplier '{identifier}' not found in company",
        )

    # 3. Validate line duplicates and category mappings
    seen_ext_lines: set[str] = set()
    seen_line_nums: set[int] = set()
    category_map: dict[str, AssetCategory] = {}

    for line_payload in payload.lines:
        # Check duplicate external_line_id in payload
        if line_payload.external_line_id in seen_ext_lines:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate external_line_id '{line_payload.external_line_id}' in import payload",
            )
        seen_ext_lines.add(line_payload.external_line_id)

        # Check duplicate line_number in payload
        if line_payload.line_number is not None:
            if line_payload.line_number in seen_line_nums:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Duplicate line_number '{line_payload.line_number}' in import payload",
                )
            seen_line_nums.add(line_payload.line_number)

        # Resolve category
        cat_code = line_payload.category_external_code or line_payload.category_code
        if line_payload.category_id:
            category = db.scalar(
                select(AssetCategory).where(
                    AssetCategory.company_id == company_id,
                    AssetCategory.id == line_payload.category_id,
                    AssetCategory.is_active.is_(True),
                )
            )
        elif cat_code:
            category = db.scalar(
                select(AssetCategory).where(
                    AssetCategory.company_id == company_id,
                    AssetCategory.code == cat_code.strip(),
                    AssetCategory.is_active.is_(True),
                )
            )
        else:
            category = None

        if category is None:
            cat_id = cat_code or line_payload.category_id
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Category mapping failed: Active category '{cat_id}' not found in company "
                    f"for line '{line_payload.external_line_id}'"
                ),
            )
        category_map[line_payload.external_line_id] = category

    # 4. Canonical payload hash
    payload_dict = payload.model_dump(mode='json')
    incoming_hash = compute_payload_hash(payload_dict)
    clean_ref = payload.external_reference.strip()
    clean_sys_id = payload.external_system_id.strip() if payload.external_system_id else None

    # 5. Lookup existing external PO by identity
    existing_po = None
    if clean_sys_id:
        existing_po = db.scalar(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.company_id == company_id,
                PurchaseOrder.source_system == trusted_config.source_system,
                PurchaseOrder.source_instance_id == trusted_config.source_instance_id,
                PurchaseOrder.external_system_id == clean_sys_id,
            )
            .with_for_update()
        )

    if existing_po is None:
        existing_po = db.scalar(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.company_id == company_id,
                PurchaseOrder.source_system == trusted_config.source_system,
                PurchaseOrder.source_instance_id == trusted_config.source_instance_id,
                PurchaseOrder.external_system_id.is_(None),
                PurchaseOrder.external_reference == clean_ref,
            )
            .with_for_update()
        )

    now_utc = datetime.now(timezone.utc)

    # ---------------------------------------------------------------------
    # Case A: Existing PO Update
    # ---------------------------------------------------------------------
    if existing_po is not None:
        try:
            # Check identical payload
            if incoming_hash == existing_po.external_payload_hash:
                existing_po.external_last_synced_at = now_utc
                db.commit()
                return existing_po, False

            # Stale update protection
            incoming_updated = normalize_datetime(payload.external_updated_at)
            existing_updated = normalize_datetime(existing_po.external_updated_at)

            if incoming_updated is not None and existing_updated is not None:
                if incoming_updated < existing_updated:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Stale update rejected: Incoming ERP payload timestamp ({payload.external_updated_at}) "
                            f"is older than existing record timestamp ({existing_po.external_updated_at})"
                        ),
                    )
                if incoming_updated == existing_updated:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Conflicting update rejected: Incoming payload differs from existing record "
                            f"but carries an identical external_updated_at timestamp ({payload.external_updated_at})"
                        ),
                    )
            elif incoming_updated is None and existing_updated is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Payload missing external_updated_at cannot overwrite an existing timestamped record",
                )

            # Supplier mutability check if goods receipts exist
            has_receipts = db.scalar(
                select(func.count(GoodsReceipt.id)).where(
                    GoodsReceipt.company_id == company_id,
                    GoodsReceipt.purchase_order_id == existing_po.id,
                )
            )
            if has_receipts and existing_po.supplier_id != supplier.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot change supplier because goods have already been received against this purchase order",
                )

            # In-place line reconciliation
            existing_lines = db.scalars(
                select(PurchaseOrderLine)
                .where(
                    PurchaseOrderLine.company_id == company_id,
                    PurchaseOrderLine.purchase_order_id == existing_po.id,
                )
                .with_for_update()
            ).all()
            existing_lines_by_ext = {
                l.external_line_id: l for l in existing_lines if l.external_line_id
            }

            # Validate line modifications
            for line_payload in payload.lines:
                if line_payload.external_line_id in existing_lines_by_ext:
                    ex_line = existing_lines_by_ext[line_payload.external_line_id]
                    rec_qty = db.scalar(
                        select(func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0)).where(
                            GoodsReceiptLine.company_id == company_id,
                            GoodsReceiptLine.purchase_order_line_id == ex_line.id,
                        )
                    ) or 0
                    target_cat = category_map[line_payload.external_line_id]

                    if rec_qty > 0:
                        if ex_line.category_id != target_cat.id:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail=(
                                    f"Cannot change category for purchase order line '{ex_line.description}' "
                                    "because goods have already been received against it"
                                ),
                            )
                        if line_payload.quantity_ordered < rec_qty:
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=(
                                    f"Cannot reduce ordered quantity to {line_payload.quantity_ordered} for line "
                                    f"'{ex_line.description}' because {rec_qty} items have already been received"
                                ),
                            )

                    # In-place update preserving UUID
                    ex_line.description = line_payload.description
                    ex_line.quantity_ordered = line_payload.quantity_ordered
                    ex_line.unit_cost = line_payload.unit_cost
                    ex_line.line_number = line_payload.line_number
                    if rec_qty == 0:
                        ex_line.category_id = target_cat.id
                else:
                    # Append new line
                    db.add(
                        PurchaseOrderLine(
                            company_id=company_id,
                            purchase_order_id=existing_po.id,
                            category_id=category_map[line_payload.external_line_id].id,
                            description=line_payload.description,
                            quantity_ordered=line_payload.quantity_ordered,
                            unit_cost=line_payload.unit_cost,
                            external_line_id=line_payload.external_line_id,
                            line_number=line_payload.line_number,
                        )
                    )

            # Handle omitted lines
            for ext_id, ex_line in existing_lines_by_ext.items():
                if ext_id not in seen_ext_lines:
                    rec_qty = db.scalar(
                        select(func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0)).where(
                            GoodsReceiptLine.company_id == company_id,
                            GoodsReceiptLine.purchase_order_line_id == ex_line.id,
                        )
                    ) or 0
                    if rec_qty > 0:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Cannot omit or delete purchase order line '{ex_line.description}' ({ext_id}) "
                                "because goods have already been received against it"
                            ),
                        )
                    # Safe deletion for unreceived lines omitted by ERP update
                    db.delete(ex_line)

            # Update PO header fields
            existing_po.supplier_id = supplier.id
            existing_po.ordered_date = payload.ordered_date
            existing_po.expected_date = payload.expected_date
            existing_po.notes = payload.notes
            existing_po.external_updated_at = payload.external_updated_at
            existing_po.external_payload_hash = incoming_hash
            existing_po.external_last_synced_at = now_utc
            if clean_sys_id and not existing_po.external_system_id:
                existing_po.external_system_id = clean_sys_id

            db.flush()
            recalculate_purchase_order_status(db, existing_po)

            record_security_event(
                db,
                action='purchase_order_import_updated',
                entity_type='PurchaseOrder',
                entity_id=str(existing_po.id),
                actor_id=actor_id,
                company_id=company_id,
                changes={
                    'source_system': existing_po.source_system,
                    'source_instance_id': existing_po.source_instance_id,
                    'external_reference': existing_po.external_reference,
                    'external_system_id': existing_po.external_system_id,
                    'external_updated_at': str(existing_po.external_updated_at) if existing_po.external_updated_at else None,
                    'order_number': existing_po.order_number,
                    'status': existing_po.status,
                },
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Conflict during external purchase order update; a database constraint was violated",
                ) from exc
            db.refresh(existing_po)
            return existing_po, False
        except Exception:
            db.rollback()
            raise

    # ---------------------------------------------------------------------
    # Case B: First-time Import (INSERT)
    # ---------------------------------------------------------------------
    display_number = derive_display_order_number(
        trusted_config.display_prefix, clean_ref
    )

    # Validate display order_number uniqueness in this company
    existing_disp = db.scalar(
        select(PurchaseOrder.id).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.order_number == display_number,
        )
    )
    if existing_disp is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Purchase order display reference '{display_number}' is already in use by another "
                "purchase order in this company"
            ),
        )

    try:
        po = PurchaseOrder(
            company_id=company_id,
            supplier_id=supplier.id,
            order_number=display_number,
            origin='EXTERNAL',
            source_system=trusted_config.source_system,
            source_instance_id=trusted_config.source_instance_id,
            external_reference=clean_ref,
            external_system_id=clean_sys_id,
            external_last_synced_at=now_utc,
            external_updated_at=payload.external_updated_at,
            external_payload_hash=incoming_hash,
            ordered_date=payload.ordered_date,
            expected_date=payload.expected_date,
            notes=payload.notes,
            status='open',
        )
        db.add(po)
        db.flush()

        for line_payload in payload.lines:
            db.add(
                PurchaseOrderLine(
                    company_id=company_id,
                    purchase_order_id=po.id,
                    category_id=category_map[line_payload.external_line_id].id,
                    description=line_payload.description,
                    quantity_ordered=line_payload.quantity_ordered,
                    unit_cost=line_payload.unit_cost,
                    external_line_id=line_payload.external_line_id,
                    line_number=line_payload.line_number,
                )
            )

        db.flush()
        recalculate_purchase_order_status(db, po)

        record_security_event(
            db,
            action='purchase_order_imported',
            entity_type='PurchaseOrder',
            entity_id=str(po.id),
            actor_id=actor_id,
            company_id=company_id,
            changes={
                'source_system': po.source_system,
                'source_instance_id': po.source_instance_id,
                'external_reference': po.external_reference,
                'external_system_id': po.external_system_id,
                'external_updated_at': str(po.external_updated_at) if po.external_updated_at else None,
                'order_number': po.order_number,
                'status': po.status,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Handle concurrent insertion race condition: another thread/worker committed this external PO
        winning_po = None
        if clean_sys_id:
            winning_po = db.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.company_id == company_id,
                    PurchaseOrder.source_system == trusted_config.source_system,
                    PurchaseOrder.source_instance_id == trusted_config.source_instance_id,
                    PurchaseOrder.external_system_id == clean_sys_id,
                )
            )
        if winning_po is None:
            winning_po = db.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.company_id == company_id,
                    PurchaseOrder.source_system == trusted_config.source_system,
                    PurchaseOrder.source_instance_id == trusted_config.source_instance_id,
                    PurchaseOrder.external_reference == clean_ref,
                )
            )
        if winning_po is not None:
            if incoming_hash == winning_po.external_payload_hash:
                winning_po.external_last_synced_at = now_utc
                db.commit()
                db.refresh(winning_po)
                return winning_po, False
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conflict during external purchase order import; another process ingested this record concurrently with a different payload",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Purchase order display reference '{display_number}' is already in use by another "
                "purchase order in this company"
            ),
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(po)
    return po, True
