from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Asset,
    AssetCategory,
    AssetDepartmentUsage,
    AssetHistory,
    AssetNumberRule,
    Company,
    CostCenter,
    Department,
    Location,
    ReferenceSequence,
    Site,
)
from app.reference_service import (
    ReferenceNumberService,
    ReservedPrefixCollisionError,
    SequenceNotFoundError,
)
from app.schemas import AssetCreate, AssetUpdate, CompanyCreate

INITIAL_CATEGORIES = (
    ('LAPTOP', 'Laptops'),
    ('DESKTOP', 'Desktops'),
    ('SERVER', 'Servers'),
    ('PRINTER', 'Printers'),
    ('NETWORK', 'Network equipment'),
    ('PERIPHERAL', 'Peripherals'),
)


def get_company(db: Session, company_id: UUID, *, active: bool = False) -> Company:
    company = db.get(Company, company_id)
    if company is None or (active and not company.is_active):
        raise HTTPException(status_code=404, detail='Company not found')
    return company


def get_scoped(db: Session, model, company_id: UUID, item_id: UUID, label: str):
    item = db.scalar(select(model).where(model.company_id == company_id, model.id == item_id))
    if item is None:
        raise HTTPException(status_code=404, detail=f'{label} not found in this company')
    return item


def create_company(db: Session, payload: CompanyCreate) -> Company:
    prefix_base = (payload.number_prefix or "").strip().upper()
    if not prefix_base:
        raise HTTPException(
            status_code=422,
            detail="An explicit number_prefix is required for company creation and numbering provisioning.",
        )

    company = Company(code=payload.code.strip(), name=payload.name.strip(), is_active=payload.is_active)
    db.add(company)
    db.flush()

    try:
        ReferenceNumberService.provision_company_sequences(db, company.id, prefix_base=prefix_base)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Company provisioning failed during reference sequence initialization: {exc}",
        ) from exc

    db.add(
        AssetNumberRule(
            company_id=company.id,
            prefix=prefix_base,
            separator=payload.number_separator,
            padding=payload.number_padding,
            next_value=1,
        )
    )
    for code, name in INITIAL_CATEGORIES:
        db.add(AssetCategory(company_id=company.id, code=code, name=name, is_active=True))
    db.commit()
    db.refresh(company)
    return company


def validate_site_location(db: Session, company_id: UUID, site_id: UUID | None, location_id: UUID | None) -> None:
    if site_id is not None:
        site = get_scoped(db, Site, company_id, site_id, 'Site')
        if not site.is_active:
            raise HTTPException(status_code=422, detail='Site is inactive')
    if location_id is not None:
        location = get_scoped(db, Location, company_id, location_id, 'Location')
        if not location.is_active:
            raise HTTPException(status_code=422, detail='Location is inactive')
        if site_id is None or location.site_id != site_id:
            raise HTTPException(status_code=422, detail='Location must belong to the selected site')


def validate_asset_relations(db: Session, company_id: UUID, category_id: UUID, site_id: UUID | None,
                             location_id: UUID | None, department_id: UUID | None, cost_center_id: UUID | None) -> None:
    category = get_scoped(db, AssetCategory, company_id, category_id, 'Asset category')
    if not category.is_active:
        raise HTTPException(status_code=422, detail='Asset category is inactive')
    validate_site_location(db, company_id, site_id, location_id)
    if department_id is not None:
        department = get_scoped(db, Department, company_id, department_id, 'Department')
        if not department.is_active:
            raise HTTPException(status_code=422, detail='Department is inactive')
    if cost_center_id is not None:
        center = get_scoped(db, CostCenter, company_id, cost_center_id, 'Cost centre')
        if not center.is_active:
            raise HTTPException(status_code=422, detail='Cost centre is inactive')


def record_history(db: Session, asset: Asset, event_type: str, field_name: str | None = None,
                   old_value: str | None = None, new_value: str | None = None) -> None:
    db.add(
        AssetHistory(
            company_id=asset.company_id,
            asset_id=asset.id,
            event_type=event_type,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            occurred_at=datetime.now(timezone.utc),
        )
    )


def next_asset_number(db: Session, company_id: UUID, category_id: UUID | None = None) -> str:
    """
    Centralized asset number allocator helper.
    Delegates directly to ReferenceNumberService as the sole allocator.
    Category-specific legacy rules no longer override the central sequence.
    Allocation occurs within caller's active database transaction without internal commits.
    """
    return ReferenceNumberService.allocate(
        db,
        company_id,
        "asset",
        is_permanent=True,
    )


def create_asset(
    db: Session,
    company_id: UUID,
    payload: AssetCreate,
    *,
    commit: bool = True,
    goods_receipt_line_id: UUID | None = None,
) -> Asset:
    company = get_company(db, company_id, active=True)
    validate_asset_relations(
        db, company_id, payload.category_id, payload.site_id, payload.location_id,
        payload.responsible_department_id, payload.cost_center_id,
    )
    if payload.asset_number and payload.asset_number.strip():
        number = payload.asset_number.strip()
        try:
            ReferenceNumberService.validate_manual_identifier(
                db, company_id, "asset", number
            )
        except SequenceNotFoundError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Company {company_id} has not been provisioned with asset numbering rules.",
            ) from exc
        except ReservedPrefixCollisionError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc

        # 2. Duplicate check within company:
        dup = db.scalar(
            select(Asset.id).where(
                Asset.company_id == company_id,
                Asset.asset_number == number,
            )
        )
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Asset number '{number}' already exists in this company",
            )
    else:
        number = ReferenceNumberService.allocate(
            db,
            company_id,
            "asset",
            is_permanent=True,
        )

    asset = Asset(
        company_id=company.id,
        asset_number=number,
        goods_receipt_line_id=goods_receipt_line_id,
        **payload.model_dump(exclude={'asset_number'}),
    )
    db.add(asset)
    db.flush()
    record_history(db, asset, 'created')
    if commit:
        db.commit()
        db.refresh(asset)
    return asset


def update_asset(db: Session, company_id: UUID, asset_id: UUID, payload: AssetUpdate) -> Asset:
    asset = get_scoped(db, Asset, company_id, asset_id, 'Asset')
    updates = payload.model_dump(exclude_unset=True)
    target = {**{key: getattr(asset, key) for key in ('category_id', 'site_id', 'location_id', 'responsible_department_id', 'cost_center_id')},
              **{key: updates[key] for key in updates if key in {'category_id', 'site_id', 'location_id', 'responsible_department_id', 'cost_center_id'}}}
    validate_asset_relations(
        db, company_id, target['category_id'], target['site_id'], target['location_id'],
        target['responsible_department_id'], target['cost_center_id'],
    )
    if target['location_id'] is not None and target['site_id'] is None:
        raise HTTPException(status_code=422, detail='A site is required when assigning a physical location')
    warranty_start = updates.get('warranty_start', asset.warranty_start)
    warranty_end = updates.get('warranty_end', asset.warranty_end)
    if warranty_start is not None and warranty_end is not None and warranty_end < warranty_start:
        raise HTTPException(status_code=422, detail='Warranty end must be on or after warranty start')

    for field, new_value in updates.items():
        old_value = getattr(asset, field)
        if old_value != new_value:
            record_history(
                db, asset, 'updated', field,
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            )
            setattr(asset, field, new_value)
    db.commit()
    db.refresh(asset)
    return asset


def ensure_unique_asset_number(db: Session, company_id: UUID, asset_number: str, exclude_id: UUID | None = None) -> None:
    query = select(Asset.id).where(Asset.company_id == company_id, Asset.asset_number == asset_number)
    if exclude_id is not None:
        query = query.where(Asset.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=409, detail='Asset number is already in use by this company')


def get_page(db: Session, query, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}

def calculate_purchase_order_status(db: Session, order: PurchaseOrder) -> str:
    """
    Authoritative line-level status determination for a Purchase Order.

    Status determination rules:
    1. OPEN:
       - No active PO line has any received quantity (or PO has no active lines).
    2. PARTIALLY_RECEIVED:
       - At least one active PO line has received quantity (> 0), AND
       - At least one active PO line still has outstanding quantity (received < ordered).
    3. RECEIVED:
       - Every active PO line has been fully received (received >= ordered, for all lines, with line count > 0).
       - Over-receipt on one line must NEVER compensate for under-receipt on another line.

    Received quantity aggregation is calculated directly from actual GoodsReceiptLine records.
    """
    if order.status == 'cancelled':
        return 'cancelled'
    db.flush()
    stmt = (
        select(
            PurchaseOrderLine.id,
            PurchaseOrderLine.quantity_ordered,
            func.coalesce(
                func.sum(
                    GoodsReceiptLine.quantity_received
                    - GoodsReceiptLine.quantity_rejected
                ),
                0,
            ).label('received_qty'),
        )
        .outerjoin(
            GoodsReceiptLine,
            (GoodsReceiptLine.purchase_order_line_id == PurchaseOrderLine.id)
            & (GoodsReceiptLine.company_id == PurchaseOrderLine.company_id),
        )
        .where(
            PurchaseOrderLine.company_id == order.company_id,
            PurchaseOrderLine.purchase_order_id == order.id,
        )
        .group_by(PurchaseOrderLine.id, PurchaseOrderLine.quantity_ordered)
    )
    results = db.execute(stmt).all()

    if not results:
        return 'open'

    has_any_received = False
    all_fully_received = True

    for _, qty_ordered, qty_received in results:
        if qty_received > 0:
            has_any_received = True
        if qty_received < qty_ordered:
            all_fully_received = False

    if all_fully_received:
        return 'received'
    elif has_any_received:
        return 'partially_received'
    else:
        return 'open'


def recalculate_purchase_order_status(db: Session, order: PurchaseOrder) -> str:
    """
    Recalculates and updates order.status using authoritative line-level status rules.
    Returns the updated status string.
    """
    if order.status == 'cancelled':
        return 'cancelled'
    new_status = calculate_purchase_order_status(db, order)
    order.status = new_status
    return new_status

