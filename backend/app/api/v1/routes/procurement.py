from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
    GoodsReceiptCreate,
    GoodsReceiptLineRead,
    GoodsReceiptRead,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    ReceivedAssetRead,
    SupplierCreate,
    SupplierRead,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import create_asset, get_company

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
            )
        )
    return PurchaseOrderRead(
        **{key: getattr(order, key) for key in (
            'id', 'company_id', 'supplier_id', 'order_number', 'status',
            'ordered_date', 'expected_date', 'notes', 'created_at',
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
    order = PurchaseOrder(
        company_id=company_id,
        supplier_id=supplier.id,
        order_number=payload.order_number.strip(),
        ordered_date=payload.ordered_date,
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
    if order.status != 'open':
        raise HTTPException(
            status_code=409,
            detail=f'Cannot edit purchase order in "{order.status}" status; only open purchase orders may be modified',
        )

    has_receipts = db.scalar(
        select(func.count(GoodsReceipt.id)).where(
            GoodsReceipt.company_id == company_id,
            GoodsReceipt.purchase_order_id == order.id,
        )
    )
    if has_receipts:
        raise HTTPException(
            status_code=409,
            detail='Cannot edit purchase order because goods have already been received against it',
        )

    supplier_id = payload.supplier_id or order.supplier_id
    supplier = db.scalar(select(Supplier).where(
        Supplier.company_id == company_id,
        Supplier.id == supplier_id,
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

    new_order_number = payload.order_number.strip() if payload.order_number else order.order_number
    if new_order_number != order.order_number:
        existing = db.scalar(select(PurchaseOrder.id).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.order_number == new_order_number,
            PurchaseOrder.id != order.id,
        ))
        if existing:
            raise HTTPException(status_code=409, detail=f'Order number "{new_order_number}" already exists in this company')

    new_ordered_date = payload.ordered_date or order.ordered_date
    new_expected_date = payload.expected_date if payload.expected_date is not None else order.expected_date
    if new_expected_date and new_expected_date < new_ordered_date:
        raise HTTPException(status_code=422, detail='expected_date must be on or after ordered_date')

    order.supplier_id = supplier.id
    order.order_number = new_order_number
    order.ordered_date = new_ordered_date
    order.expected_date = new_expected_date
    if payload.notes is not None:
        order.notes = payload.notes

    db.execute(
        delete(PurchaseOrderLine).where(
            PurchaseOrderLine.company_id == company_id,
            PurchaseOrderLine.purchase_order_id == order.id,
        )
    )
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

    record_security_event(
        db,
        action='purchase_order_updated',
        entity_type='PurchaseOrder',
        entity_id=str(order.id),
        actor_id=actor.user.id,
        company_id=company_id,
        changes={
            'supplier_id': str(supplier.id),
            'order_number': order.order_number,
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
    receipt_number = payload.receipt_number.strip()
    if not receipt_number:
        raise HTTPException(status_code=422, detail='Receipt number cannot be blank')
    if db.scalar(
        select(GoodsReceipt.id).where(
            GoodsReceipt.company_id == company_id,
            GoodsReceipt.receipt_number == receipt_number,
        )
    ) is not None:
        raise HTTPException(
            status_code=409,
            detail=f'Goods receipt number "{receipt_number}" already exists in this company',
        )
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
    total_received = db.scalar(
        select(func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0)).where(
            GoodsReceiptLine.company_id == company_id,
            GoodsReceiptLine.purchase_order_id == order.id,
        )
    ) or 0
    total_ordered = db.scalar(
        select(func.coalesce(func.sum(PurchaseOrderLine.quantity_ordered), 0)).where(
            PurchaseOrderLine.company_id == company_id,
            PurchaseOrderLine.purchase_order_id == order.id,
        )
    ) or 0
    order.status = 'received' if total_received >= total_ordered else 'partially_received'
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
