from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_security_event
from app.database import get_db
from app.models import (
    Asset,
    AssetCategory,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.schemas import (
    AssetCreate,
    ExternalPurchaseOrderImportPayload,
    GoodsReceiptCreate,
    GoodsReceiptLineRead,
    GoodsReceiptRead,
    PurchaseOrderCancel,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    ReceivedAssetRead,
    SupplierCreate,
    SupplierRead,
)
from app.security import CurrentActor, current_actor, require_permission
from app.erp_ingestion_service import import_external_purchase_order
from app.services import (
    calculate_purchase_order_status,
    create_asset,
    get_company,
    recalculate_purchase_order_status,
)
from datetime import datetime, timezone
from app.reference_service import (
    DEFAULT_TIMEZONE,
    ReferenceNumberService,
    ReservedPrefixCollisionError,
    SequenceInactiveError,
    SequenceNotFoundError,
)

router = APIRouter(prefix='/companies/{company_id}', tags=['procurement'], dependencies=[Depends(current_actor)])


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='The procurement record conflicts with existing company data') from exc


def order_read(db: Session, order: PurchaseOrder) -> PurchaseOrderRead:
    lines = db.scalars(
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.company_id == order.company_id, PurchaseOrderLine.purchase_order_id == order.id)
        .order_by(PurchaseOrderLine.id)
    ).all()
    read_lines = []
    for line in lines:
        received_qty = db.scalar(
            select(func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0)).where(
                GoodsReceiptLine.company_id == order.company_id,
                GoodsReceiptLine.purchase_order_line_id == line.id,
            )
        ) or 0
        if received_qty < 0:
            received_qty = 0
        remaining_qty = max(0, line.quantity_ordered - received_qty)
        read_lines.append(
            PurchaseOrderLineRead(
                id=line.id,
                company_id=line.company_id,
                purchase_order_id=line.purchase_order_id,
                category_id=line.category_id,
                description=line.description,
                quantity_ordered=line.quantity_ordered,
                unit_cost=line.unit_cost,
                quantity_received=received_qty,
                quantity_remaining=remaining_qty,
                external_line_id=line.external_line_id,
                line_number=line.line_number,
            )
        )
    return PurchaseOrderRead(
        **{key: getattr(order, key) for key in (
            'id', 'company_id', 'supplier_id', 'order_number', 'status',
            'ordered_date', 'expected_date', 'notes', 'created_at',
            'origin', 'source_system', 'source_instance_id', 'external_reference',
            'external_system_id', 'external_last_synced_at', 'external_updated_at',
            'external_payload_hash',
            'cancelled_at', 'cancelled_by_id', 'cancellation_reason',
        )},
        lines=read_lines,
    )


def receipt_read(db: Session, receipt: GoodsReceipt) -> GoodsReceiptRead:
    lines = db.scalars(
        select(GoodsReceiptLine).where(
            GoodsReceiptLine.company_id == receipt.company_id,
            GoodsReceiptLine.goods_receipt_id == receipt.id,
        )
    ).all()
    response_lines = []
    for line in lines:
        assets = db.scalars(
            select(Asset).where(
                Asset.company_id == line.company_id,
                Asset.goods_receipt_line_id == line.id,
            ).order_by(Asset.asset_number)
        ).all()
        response_lines.append(
            GoodsReceiptLineRead(
                id=line.id,
                purchase_order_line_id=line.purchase_order_line_id,
                quantity_received=line.quantity_received,
                quantity_rejected=line.quantity_rejected,
                discrepancy_notes=line.discrepancy_notes,
                assets=[ReceivedAssetRead(
                    id=asset.id,
                    asset_number=asset.asset_number,
                    serial_number=asset.serial_number,
                    status=asset.status,
                ) for asset in assets],
            )
        )
    return GoodsReceiptRead(
        **{key: getattr(receipt, key) for key in (
            'id', 'company_id', 'purchase_order_id', 'receipt_number',
            'received_date', 'delivery_reference', 'notes', 'created_at',
        )},
        lines=response_lines,
    )


@router.get('/suppliers', response_model=list[SupplierRead], dependencies=[Depends(require_permission('procurement.read'))])
def list_suppliers(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    return db.scalars(select(Supplier).where(Supplier.company_id == company_id).order_by(Supplier.name)).all()


@router.post('/suppliers', response_model=SupplierRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission('procurement.manage'))])
def create_supplier(company_id: UUID, payload: SupplierCreate, db: Session = Depends(get_db)):
    get_company(db, company_id, active=True)
    supplier = Supplier(company_id=company_id, **payload.model_dump())
    db.add(supplier)
    commit(db)
    db.refresh(supplier)
    return supplier


@router.get('/purchase-orders', response_model=list[PurchaseOrderRead], dependencies=[Depends(require_permission('procurement.read'))])
def list_purchase_orders(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    orders = db.scalars(
        select(PurchaseOrder).where(PurchaseOrder.company_id == company_id).order_by(PurchaseOrder.created_at.desc())
    ).all()
    return [order_read(db, order) for order in orders]


@router.post('/purchase-orders', response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission('procurement.manage'))])
def create_purchase_order(
    company_id: UUID,
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.manage')),
):
    get_company(db, company_id, active=True)
    supplier = db.scalar(select(Supplier).where(
        Supplier.company_id == company_id,
        Supplier.id == payload.supplier_id,
        Supplier.is_active.is_(True),
    ))
    if supplier is None:
        raise HTTPException(status_code=422, detail='Supplier must be active in this company')
    category_ids = {line.category_id for line in payload.lines}
    categories = set(db.scalars(select(AssetCategory.id).where(
        AssetCategory.company_id == company_id,
        AssetCategory.id.in_(category_ids),
        AssetCategory.is_active.is_(True),
    )).all())
    if categories != category_ids:
        raise HTTPException(status_code=422, detail='Every purchase-order category must be active in this company')
    ordered_date = payload.ordered_date or datetime.now(DEFAULT_TIMEZONE).date()
    if payload.expected_date and payload.expected_date < ordered_date:
        raise HTTPException(status_code=422, detail='expected_date must be on or after ordered_date')

    if payload.order_number and payload.order_number.strip():
        raise HTTPException(
            status_code=422,
            detail='Manual purchase order numbers are not permitted for internal purchase orders. References are automatically generated by the reference numbering service.',
        )

    try:
        final_order_number = ReferenceNumberService.allocate(
            db,
            company_id,
            'purchase_order',
            business_date=ordered_date,
            is_permanent=False,
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=f'Company {company_id} has not been provisioned with purchase order numbering rules. Explicit company provisioning is required.',
        ) from exc
    except SequenceInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    order = PurchaseOrder(
        company_id=company_id,
        supplier_id=supplier.id,
        order_number=final_order_number,
        origin='INTERNAL',
        source_system=None,
        source_instance_id=None,
        external_reference=None,
        external_system_id=None,
        external_last_synced_at=None,
        external_updated_at=None,
        external_payload_hash=None,
        ordered_date=ordered_date,
        expected_date=payload.expected_date,
        notes=payload.notes,
    )
    db.add(order)
    db.flush()
    for line in payload.lines:
        db.add(PurchaseOrderLine(
            company_id=company_id,
            purchase_order_id=order.id,
            category_id=line.category_id,
            description=line.description,
            quantity_ordered=line.quantity_ordered,
            unit_cost=line.unit_cost,
        ))
    db.flush()
    recalculate_purchase_order_status(db, order)
    record_security_event(
        db,
        action='purchase_order_created',
        entity_type='PurchaseOrder',
        entity_id=str(order.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'supplier_id': str(supplier.id),
            'order_number': order.order_number,
            'origin': order.origin,
            'ordered_date': str(order.ordered_date),
            'lines': [{
                'category_id': str(line.category_id),
                'description': line.description,
                'quantity_ordered': line.quantity_ordered,
                'unit_cost': str(line.unit_cost),
            } for line in payload.lines],
        },
    )
    commit(db)
    db.refresh(order)
    return order_read(db, order)


@router.post(
    '/purchase-orders/external-import',
    response_model=PurchaseOrderRead,
    dependencies=[Depends(require_permission('procurement.import'))],
)
def import_external_purchase_order_route(
    company_id: UUID,
    payload: ExternalPurchaseOrderImportPayload,
    response: Response,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.import')),
):
    get_company(db, company_id, active=True)
    po, is_created = import_external_purchase_order(db, company_id, payload, actor.user.id)
    if is_created:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK
    return order_read(db, po)


@router.get(
    '/purchase-orders/{purchase_order_id}',
    response_model=PurchaseOrderRead,
    dependencies=[Depends(require_permission('procurement.read'))],
)
def get_purchase_order(company_id: UUID, purchase_order_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    order = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.id == purchase_order_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail='Purchase order not found')
    return order_read(db, order)


@router.put(
    '/purchase-orders/{purchase_order_id}',
    response_model=PurchaseOrderRead,
    dependencies=[Depends(require_permission('procurement.manage'))],
)
@router.patch(
    '/purchase-orders/{purchase_order_id}',
    response_model=PurchaseOrderRead,
    dependencies=[Depends(require_permission('procurement.manage'))],
)
def update_purchase_order(
    company_id: UUID,
    purchase_order_id: UUID,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.manage')),
):
    get_company(db, company_id, active=True)
    order = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.company_id == company_id, PurchaseOrder.id == purchase_order_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail='Purchase order not found')
    if order.status == 'cancelled':
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order "{order.order_number}" is cancelled and cannot be modified',
        )
    # 1. Reference immutability check
    if payload.order_number and payload.order_number.strip() != order.order_number:
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order reference "{order.order_number}" is immutable and cannot be modified',
        )

    # 2. Check supplier change against goods receipts
    if payload.supplier_id and payload.supplier_id != order.supplier_id:
        has_receipts = db.scalar(
            select(func.count(GoodsReceipt.id)).where(
                GoodsReceipt.company_id == company_id,
                GoodsReceipt.purchase_order_id == order.id,
            )
        )
        if has_receipts:
            raise HTTPException(
                status_code=409,
                detail='Cannot change supplier because goods have already been received against this purchase order',
            )
        supplier = db.scalar(select(Supplier).where(
            Supplier.company_id == company_id,
            Supplier.id == payload.supplier_id,
            Supplier.is_active.is_(True),
        ))
        if supplier is None:
            raise HTTPException(status_code=422, detail='Supplier must be active in this company')
        order.supplier_id = supplier.id

    # 3. Safe dates update
    new_ordered_date = payload.ordered_date or order.ordered_date
    new_expected_date = payload.expected_date if payload.expected_date is not None else order.expected_date
    if new_expected_date and new_expected_date < new_ordered_date:
        raise HTTPException(status_code=422, detail='expected_date must be on or after ordered_date')
    order.ordered_date = new_ordered_date
    order.expected_date = new_expected_date

    # 4. Safe notes update
    if payload.notes is not None:
        order.notes = payload.notes

    # 5. Granular line updates (if lines supplied in payload)
    audited_lines = None
    if payload.lines is not None:
        if len(payload.lines) == 0:
            raise HTTPException(status_code=422, detail='Purchase order must contain at least one line')
        category_ids = {line.category_id for line in payload.lines}
        categories = set(db.scalars(select(AssetCategory.id).where(
            AssetCategory.company_id == company_id,
            AssetCategory.id.in_(category_ids),
            AssetCategory.is_active.is_(True),
        )).all())
        if categories != category_ids:
            raise HTTPException(status_code=422, detail='Every purchase-order category must be active in this company')

        existing_lines = db.scalars(
            select(PurchaseOrderLine)
            .where(
                PurchaseOrderLine.company_id == company_id,
                PurchaseOrderLine.purchase_order_id == order.id,
            )
        ).all()
        existing_lines_by_id = {l.id: l for l in existing_lines}

        receipt_rows = db.execute(
            select(
                GoodsReceiptLine.purchase_order_line_id,
                func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0),
            )
            .where(
                GoodsReceiptLine.company_id == company_id,
                GoodsReceiptLine.purchase_order_id == order.id,
            )
            .group_by(GoodsReceiptLine.purchase_order_line_id)
        ).all()
        received_by_line = {row[0]: row[1] for row in receipt_rows}

        incoming_with_id = [line for line in payload.lines if line.id is not None]
        for line_payload in incoming_with_id:
            if line_payload.id not in existing_lines_by_id:
                raise HTTPException(
                    status_code=422,
                    detail=f'Purchase order line "{line_payload.id}" does not belong to this purchase order',
                )

        seen_ids = set()
        for line_payload in incoming_with_id:
            if line_payload.id in seen_ids:
                raise HTTPException(status_code=422, detail=f'Duplicate purchase order line ID in request: {line_payload.id}')
            seen_ids.add(line_payload.id)

        # Protect all lines with receipt history from deletion, category changes, or excessive quantity reduction
        for l in existing_lines:
            recv_qty = received_by_line.get(l.id, 0)
            if recv_qty > 0:
                if l.id not in seen_ids:
                    raise HTTPException(
                        status_code=409,
                        detail=f'Cannot delete purchase order line "{l.description}" ({l.id}) because goods have already been received against it',
                    )
                line_payload = next(lp for lp in incoming_with_id if lp.id == l.id)
                if line_payload.category_id != l.category_id:
                    raise HTTPException(
                        status_code=409,
                        detail=f'Cannot change category for purchase order line "{l.description}" because goods have already been received against it',
                    )
                if line_payload.quantity_ordered < recv_qty:
                    raise HTTPException(
                        status_code=422,
                        detail=f'Cannot reduce ordered quantity to {line_payload.quantity_ordered} for line "{l.description}" because {recv_qty} items have already been received',
                    )
                # Update line in-place, preserving UUID
                l.description = line_payload.description
                l.quantity_ordered = line_payload.quantity_ordered
                l.unit_cost = line_payload.unit_cost
                l.external_line_id = line_payload.external_line_id
                l.line_number = line_payload.line_number

        # Handle unreceived existing lines
        unreceived_existing = [l for l in existing_lines if received_by_line.get(l.id, 0) == 0]
        unconsumed_unreceived = [l for l in unreceived_existing if l.id not in seen_ids]

        # Explicitly updated unreceived lines
        for l in unreceived_existing:
            if l.id in seen_ids:
                line_payload = next(lp for lp in incoming_with_id if lp.id == l.id)
                l.category_id = line_payload.category_id
                l.description = line_payload.description
                l.quantity_ordered = line_payload.quantity_ordered
                l.unit_cost = line_payload.unit_cost
                l.external_line_id = line_payload.external_line_id
                l.line_number = line_payload.line_number

        # Handle lines without explicit ID
        incoming_without_id = [line for line in payload.lines if line.id is None]
        for line_payload in incoming_without_id:
            if unconsumed_unreceived:
                # Match to unconsumed unreceived line to preserve line UUID
                matched = unconsumed_unreceived.pop(0)
                matched.category_id = line_payload.category_id
                matched.description = line_payload.description
                matched.quantity_ordered = line_payload.quantity_ordered
                matched.unit_cost = line_payload.unit_cost
                matched.external_line_id = line_payload.external_line_id
                matched.line_number = line_payload.line_number
            else:
                # Add new line
                db.add(PurchaseOrderLine(
                    company_id=company_id,
                    purchase_order_id=order.id,
                    category_id=line_payload.category_id,
                    description=line_payload.description,
                    quantity_ordered=line_payload.quantity_ordered,
                    unit_cost=line_payload.unit_cost,
                    external_line_id=line_payload.external_line_id,
                    line_number=line_payload.line_number,
                ))

        # Delete any remaining unconsumed unreceived lines
        for l in unconsumed_unreceived:
            db.delete(l)

        db.flush()

        # Recalculate order status using authoritative line-level rules
        recalculate_purchase_order_status(db, order)

        audited_lines = [{
            'category_id': str(line.category_id),
            'description': line.description,
            'quantity_ordered': line.quantity_ordered,
            'unit_cost': str(line.unit_cost),
        } for line in payload.lines]

    record_security_event(
        db,
        action='purchase_order_updated',
        entity_type='PurchaseOrder',
        entity_id=str(order.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'supplier_id': str(order.supplier_id),
            'order_number': order.order_number,
            'origin': order.origin,
            'ordered_date': str(order.ordered_date),
            'expected_date': str(order.expected_date) if order.expected_date else None,
            'notes': order.notes,
            'lines': audited_lines,
        },
    )
    commit(db)
    db.refresh(order)
    return order_read(db, order)




@router.post(
    '/purchase-orders/{purchase_order_id}/cancel',
    response_model=PurchaseOrderRead,
    dependencies=[Depends(require_permission('procurement.manage'))],
)
def cancel_purchase_order(
    company_id: UUID,
    purchase_order_id: UUID,
    payload: PurchaseOrderCancel,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.manage')),
):
    get_company(db, company_id, active=True)
    order = db.scalar(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.id == purchase_order_id,
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail='Purchase order not found')

    # Origin check: External ERP purchase orders cannot be cancelled locally
    if order.origin == 'EXTERNAL':
        raise HTTPException(
            status_code=409,
            detail=(
                f'Purchase order "{order.order_number}" originated from external ERP '
                f'({order.source_system}) and cannot be cancelled locally. '
                f'Cancellation must originate from the source ERP.'
            ),
        )

    # Status checks:
    if order.status == 'cancelled':
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order "{order.order_number}" is already cancelled',
        )
    if order.status == 'received':
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order "{order.order_number}" is fully received and cannot be cancelled',
        )
    if order.status not in ('open', 'partially_received'):
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order "{order.order_number}" in status "{order.status}" cannot be cancelled',
        )

    previous_status = order.status
    cancelled_now = datetime.now(timezone.utc)
    order.status = 'cancelled'
    order.cancelled_at = cancelled_now
    order.cancelled_by_id = actor.user.id
    order.cancellation_reason = payload.reason.strip()

    record_security_event(
        db,
        action='purchase_order_cancelled',
        entity_type='PurchaseOrder',
        entity_id=str(order.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'order_number': order.order_number,
            'previous_status': previous_status,
            'status': 'cancelled',
            'reason': order.cancellation_reason,
            'cancelled_at': cancelled_now.isoformat(),
        },
    )
    commit(db)
    db.refresh(order)
    return order_read(db, order)


@router.delete(
    '/purchase-orders/{purchase_order_id}',
    dependencies=[Depends(require_permission('procurement.manage'))],
)
def delete_purchase_order(
    company_id: UUID,
    purchase_order_id: UUID,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.manage')),
):
    get_company(db, company_id, active=True)
    order = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.id == purchase_order_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail='Purchase order not found')

    has_receipts = db.scalar(
        select(func.count(GoodsReceipt.id)).where(
            GoodsReceipt.company_id == company_id,
            GoodsReceipt.purchase_order_id == order.id,
        )
    )
    if has_receipts:
        raise HTTPException(
            status_code=409,
            detail='Cannot delete purchase order because goods have already been received against it',
        )

    raise HTTPException(
        status_code=409,
        detail=f'Purchase order "{order.order_number}" has been issued (status: "{order.status}") and cannot be deleted. Issued purchase orders must be preserved for audit and reference continuity.',
    )

@router.get('/goods-receipts', response_model=list[GoodsReceiptRead], dependencies=[Depends(require_permission('procurement.read'))])
def list_goods_receipts(company_id: UUID, db: Session = Depends(get_db)):
    get_company(db, company_id)
    receipts = db.scalars(
        select(GoodsReceipt).where(GoodsReceipt.company_id == company_id).order_by(GoodsReceipt.received_date.desc())
    ).all()
    return [receipt_read(db, receipt) for receipt in receipts]


@router.post(
    '/purchase-orders/{purchase_order_id}/goods-receipts',
    response_model=GoodsReceiptRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission('procurement.manage'))],
)
def receive_goods(
    company_id: UUID,
    purchase_order_id: UUID,
    payload: GoodsReceiptCreate,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_permission('procurement.manage')),
):
    get_company(db, company_id, active=True)
    order = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.company_id == company_id, PurchaseOrder.id == purchase_order_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail='Purchase order not found')
    if order.status == 'cancelled':
        raise HTTPException(
            status_code=409,
            detail=f'Purchase order "{order.order_number}" is cancelled and cannot receive goods',
        )
    if order.status == 'received':
        raise HTTPException(status_code=409, detail='This purchase order has already been fully received')
    submitted_ids = [line.purchase_order_line_id for line in payload.lines]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise HTTPException(status_code=422, detail='A purchase-order line may appear only once per receipt')
    order_lines = {
        line.id: line for line in db.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.company_id == company_id,
                PurchaseOrderLine.purchase_order_id == order.id,
                PurchaseOrderLine.id.in_(submitted_ids),
            ).with_for_update()
        ).all()
    }
    if len(order_lines) != len(submitted_ids):
        raise HTTPException(status_code=422, detail='Every receipt line must belong to this purchase order')

    if payload.receipt_number and payload.receipt_number.strip():
        raise HTTPException(
            status_code=422,
            detail='Manual goods receipt numbers are not permitted. References are automatically generated by the reference numbering service.',
        )

    try:
        receipt_number = ReferenceNumberService.allocate(
            db,
            company_id,
            'goods_receipt',
            business_date=payload.received_date,
            is_permanent=False,
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(
            status_code=422,
            detail=f'Company {company_id} has not been provisioned with goods receipt numbering rules. Explicit company provisioning is required.',
        ) from exc
    except SequenceInactiveError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    receipt = GoodsReceipt(
        company_id=company_id,
        purchase_order_id=order.id,
        receipt_number=receipt_number,
        received_date=payload.received_date,
        delivery_reference=payload.delivery_reference,
        notes=payload.notes,
    )
    db.add(receipt)
    db.flush()
    audited_lines = []
    for line_payload in payload.lines:
        order_line = order_lines[line_payload.purchase_order_line_id]
        already_received = db.scalar(
            select(func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0)).where(
                GoodsReceiptLine.company_id == company_id,
                GoodsReceiptLine.purchase_order_line_id == order_line.id,
            )
        ) or 0
        if already_received + line_payload.quantity_received > order_line.quantity_ordered:
            raise HTTPException(
                status_code=422,
                detail=f'Receipt quantity exceeds the remaining ordered quantity for "{order_line.description}"',
            )
        accepted_quantity = line_payload.quantity_received - line_payload.quantity_rejected
        if accepted_quantity and line_payload.serial_numbers:
            normalized_serials = [serial.strip() if serial is not None else None for serial in line_payload.serial_numbers]
            if any(serial == '' for serial in normalized_serials):
                raise HTTPException(status_code=422, detail='Serial numbers cannot be blank')
        else:
            normalized_serials = [None] * accepted_quantity

        receipt_line = GoodsReceiptLine(
            company_id=company_id,
            goods_receipt_id=receipt.id,
            purchase_order_id=order.id,
            purchase_order_line_id=order_line.id,
            quantity_received=line_payload.quantity_received,
            quantity_rejected=line_payload.quantity_rejected,
            discrepancy_notes=line_payload.discrepancy_notes,
        )
        db.add(receipt_line)
        db.flush()
        supplier = db.get(Supplier, order.supplier_id)
        created_assets = []
        for serial in normalized_serials:
            asset = AssetCreate(
                category_id=order_line.category_id,
                serial_number=serial,
                manufacturer=None,
                model=order_line.description,
                acquisition_date=payload.received_date,
                acquisition_cost=order_line.unit_cost,
                status='in_stock',
                vendor_reference=supplier.code if supplier else None,
                invoice_reference=payload.delivery_reference,
            )
            registered_asset = create_asset(
                db,
                company_id,
                asset,
                commit=False,
                goods_receipt_line_id=receipt_line.id,
            )
            created_assets.append({
                'asset_id': str(registered_asset.id),
                'asset_number': registered_asset.asset_number,
                'serial_number': registered_asset.serial_number,
            })
        audited_lines.append({
            'purchase_order_line_id': str(order_line.id),
            'quantity_received': line_payload.quantity_received,
            'quantity_rejected': line_payload.quantity_rejected,
            'discrepancy_notes': line_payload.discrepancy_notes,
            'created_assets': created_assets,
        })
    db.flush()
    recalculate_purchase_order_status(db, order)
    record_security_event(
        db,
        action='goods_received',
        entity_type='GoodsReceipt',
        entity_id=str(receipt.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'purchase_order_id': str(order.id),
            'receipt_number': receipt.receipt_number,
            'received_date': str(receipt.received_date),
            'delivery_reference': receipt.delivery_reference,
            'lines': audited_lines,
        },
    )
    commit(db)
    db.refresh(receipt)
    return receipt_read(db, receipt)
