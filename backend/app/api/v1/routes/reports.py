from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetServiceContract,
    AuditEvent,
    Department,
    GoodsReceipt,
    GoodsReceiptLine,
    Location,
    MaintenanceRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    Site,
    Supplier,
    User,
)
from app.schemas import (
    AssetAllocationReportItem,
    AssetRegisterReportItem,
    CategoryMetric,
    DashboardResponse,
    DepartmentMetric,
    ExpiringContractMetric,
    MaintenanceReportItem,
    MaintenanceSummaryMetric,
    ProcurementReportItem,
    ProcurementReportLineItem,
    ProcurementSummaryMetric,
    RecentActivityMetric,
    SiteMetric,
    WarrantyExpiryReportItem,
)
from app.security import CurrentActor, current_actor, require_permission
from app.services import get_company

router = APIRouter(
    prefix='/companies/{company_id}',
    tags=['reports'],
    dependencies=[Depends(current_actor)],
)


@router.get(
    '/dashboard',
    response_model=DashboardResponse,
    dependencies=[Depends(require_permission('dashboard.read'))],
)
def get_dashboard(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)

    # 1. Total assets & by lifecycle status
    status_rows = db.execute(
        select(Asset.status, func.count(Asset.id))
        .where(Asset.company_id == company_id)
        .group_by(Asset.status)
    ).all()
    assets_by_status = {row[0]: row[1] for row in status_rows}
    total_assets = sum(assets_by_status.values())

    # 2. Assets by category
    cat_rows = db.execute(
        select(AssetCategory.id, AssetCategory.name, func.count(Asset.id))
        .join(Asset, Asset.category_id == AssetCategory.id)
        .where(Asset.company_id == company_id)
        .group_by(AssetCategory.id, AssetCategory.name)
        .order_by(func.count(Asset.id).desc(), AssetCategory.name.asc())
    ).all()
    assets_by_category = [
        CategoryMetric(category_id=row[0], category_name=row[1], count=row[2])
        for row in cat_rows
    ]

    # 3. Assets by site
    site_rows = db.execute(
        select(Site.id, Site.name, func.count(Asset.id))
        .join(Asset, Asset.site_id == Site.id)
        .where(Asset.company_id == company_id)
        .group_by(Site.id, Site.name)
        .order_by(func.count(Asset.id).desc(), Site.name.asc())
    ).all()
    unassigned_site_count = db.scalar(
        select(func.count(Asset.id)).where(Asset.company_id == company_id, Asset.site_id.is_(None))
    ) or 0
    assets_by_site = [
        SiteMetric(site_id=row[0], site_name=row[1], count=row[2])
        for row in site_rows
    ]
    if unassigned_site_count > 0:
        assets_by_site.append(SiteMetric(site_id=None, site_name='Unassigned', count=unassigned_site_count))

    # 4. Assets by department
    dept_rows = db.execute(
        select(Department.id, Department.name, func.count(Asset.id))
        .join(Asset, Asset.responsible_department_id == Department.id)
        .where(Asset.company_id == company_id)
        .group_by(Department.id, Department.name)
        .order_by(func.count(Asset.id).desc(), Department.name.asc())
    ).all()
    unassigned_dept_count = db.scalar(
        select(func.count(Asset.id)).where(Asset.company_id == company_id, Asset.responsible_department_id.is_(None))
    ) or 0
    assets_by_department = [
        DepartmentMetric(department_id=row[0], department_name=row[1], count=row[2])
        for row in dept_rows
    ]
    if unassigned_dept_count > 0:
        assets_by_department.append(DepartmentMetric(department_id=None, department_name='Unassigned', count=unassigned_dept_count))

    # 5. Expiring contracts in next 30 days (active only)
    today = date.today()
    thirty_days = today + timedelta(days=30)
    expiring_rows = db.execute(
        select(AssetServiceContract, Asset.asset_number)
        .join(Asset, Asset.id == AssetServiceContract.asset_id)
        .where(
            AssetServiceContract.company_id == company_id,
            AssetServiceContract.status == 'active',
            AssetServiceContract.end_date >= today,
            AssetServiceContract.end_date <= thirty_days,
        )
        .order_by(AssetServiceContract.end_date.asc())
    ).all()
    expiring_contracts = [
        ExpiringContractMetric(
            id=row[0].id,
            contract_type=row[0].contract_type,
            reference_number=row[0].reference_number,
            provider_name=row[0].provider_name,
            asset_id=row[0].asset_id,
            asset_number=row[1],
            end_date=row[0].end_date,
            days_remaining=(row[0].end_date - today).days,
        )
        for row in expiring_rows
    ]

    # 6. Maintenance summary
    m_rows = db.execute(
        select(MaintenanceRequest.status, func.count(MaintenanceRequest.id))
        .where(MaintenanceRequest.company_id == company_id)
        .group_by(MaintenanceRequest.status)
    ).all()
    m_map = {row[0]: row[1] for row in m_rows}
    open_c = m_map.get('open', 0)
    in_prog_c = m_map.get('in_progress', 0)
    maintenance_summary = MaintenanceSummaryMetric(
        open=open_c,
        in_progress=in_prog_c,
        resolved=m_map.get('resolved', 0),
        closed=m_map.get('closed', 0),
        total_open_and_in_progress=open_c + in_prog_c,
    )

    # 7. Procurement summary
    po_rows = db.execute(
        select(PurchaseOrder.status, func.count(PurchaseOrder.id))
        .where(PurchaseOrder.company_id == company_id)
        .group_by(PurchaseOrder.status)
    ).all()
    po_map = {row[0]: row[1] for row in po_rows}
    total_pos = sum(po_map.values())

    total_grs = db.scalar(
        select(func.count(GoodsReceipt.id)).where(GoodsReceipt.company_id == company_id)
    ) or 0

    recv_rej = db.execute(
        select(
            func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0),
            func.coalesce(func.sum(GoodsReceiptLine.quantity_rejected), 0),
        ).where(GoodsReceiptLine.company_id == company_id)
    ).first()
    items_recv = recv_rej[0] if recv_rej else 0
    items_rej = recv_rej[1] if recv_rej else 0

    procurement_summary = ProcurementSummaryMetric(
        total_purchase_orders=total_pos,
        orders_by_status=po_map,
        total_goods_receipts=total_grs,
        total_items_received=items_recv,
        total_items_rejected=items_rej,
    )

    # 8. Recent activity
    recent_events = db.execute(
        select(AuditEvent, User.email)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .where(AuditEvent.company_id == company_id)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(10)
    ).all()
    recent_activity = [
        RecentActivityMetric(
            id=ev[0].id,
            action=ev[0].action,
            entity_type=ev[0].entity_type,
            entity_id=ev[0].entity_id,
            actor_id=ev[0].actor_id,
            actor_email=ev[1],
            outcome=ev[0].outcome,
            occurred_at=ev[0].occurred_at,
        )
        for ev in recent_events
    ]

    return DashboardResponse(
        total_assets=total_assets,
        assets_by_status=assets_by_status,
        assets_by_category=assets_by_category,
        assets_by_site=assets_by_site,
        assets_by_department=assets_by_department,
        expiring_contracts_count=len(expiring_contracts),
        expiring_contracts=expiring_contracts,
        maintenance_summary=maintenance_summary,
        procurement_summary=procurement_summary,
        recent_activity=recent_activity,
    )


@router.get(
    '/reports/asset-register',
    response_model=list[AssetRegisterReportItem],
    dependencies=[Depends(require_permission('asset.read'))],
)
def report_asset_register(
    company_id: UUID,
    status: str | None = None,
    category_id: UUID | None = None,
    site_id: UUID | None = None,
    department_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            Asset,
            AssetCategory.name.label('category_name'),
            Site.name.label('site_name'),
            Department.name.label('department_name'),
        )
        .join(AssetCategory, AssetCategory.id == Asset.category_id)
        .outerjoin(Site, Site.id == Asset.site_id)
        .outerjoin(Department, Department.id == Asset.responsible_department_id)
        .where(Asset.company_id == company_id)
    )
    if status:
        query = query.where(Asset.status == status)
    if category_id:
        query = query.where(Asset.category_id == category_id)
    if site_id:
        query = query.where(Asset.site_id == site_id)
    if department_id:
        query = query.where(Asset.responsible_department_id == department_id)
    if search:
        search_filter = f'%{search.strip()}%'
        query = query.where(
            or_(
                Asset.asset_number.ilike(search_filter),
                Asset.model.ilike(search_filter),
                Asset.manufacturer.ilike(search_filter),
                Asset.serial_number.ilike(search_filter),
                Asset.custodian_name.ilike(search_filter),
            )
        )
    query = query.order_by(Asset.asset_number.asc())
    rows = db.execute(query).all()
    return [
        AssetRegisterReportItem(
            id=row.Asset.id,
            asset_number=row.Asset.asset_number,
            category_id=row.Asset.category_id,
            category_name=row.category_name,
            manufacturer=row.Asset.manufacturer,
            model=row.Asset.model,
            serial_number=row.Asset.serial_number,
            status=row.Asset.status,
            site_id=row.Asset.site_id,
            site_name=row.site_name,
            department_id=row.Asset.responsible_department_id,
            department_name=row.department_name,
            custodian_name=row.Asset.custodian_name,
            acquisition_date=row.Asset.acquisition_date,
            acquisition_cost=Decimal(str(row.Asset.acquisition_cost)) if row.Asset.acquisition_cost is not None else None,
            warranty_start=row.Asset.warranty_start,
            warranty_end=row.Asset.warranty_end,
        )
        for row in rows
    ]


@router.get(
    '/reports/asset-allocation',
    response_model=list[AssetAllocationReportItem],
    dependencies=[Depends(require_permission('asset.read'))],
)
def report_asset_allocation(
    company_id: UUID,
    recipient_id: UUID | None = None,
    department_id: UUID | None = None,
    site_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            Asset,
            AssetCategory.name.label('category_name'),
            AssetAssignment,
            User.email.label('recipient_email'),
            Department.name.label('department_name'),
            Site.name.label('site_name'),
            Location.name.label('location_name'),
        )
        .join(AssetCategory, AssetCategory.id == Asset.category_id)
        .outerjoin(
            AssetAssignment,
            (AssetAssignment.asset_id == Asset.id) & (AssetAssignment.status == 'active'),
        )
        .outerjoin(User, User.id == AssetAssignment.recipient_id)
        .outerjoin(Department, Department.id == Asset.responsible_department_id)
        .outerjoin(Site, Site.id == Asset.site_id)
        .outerjoin(Location, Location.id == Asset.location_id)
        .where(
            Asset.company_id == company_id,
            Asset.status == 'assigned',
        )
    )
    if recipient_id:
        query = query.where(AssetAssignment.recipient_id == recipient_id)
    if department_id:
        query = query.where(Asset.responsible_department_id == department_id)
    if site_id:
        query = query.where(Asset.site_id == site_id)
    if search:
        search_filter = f'%{search.strip()}%'
        query = query.where(
            or_(
                Asset.asset_number.ilike(search_filter),
                Asset.model.ilike(search_filter),
                Asset.custodian_name.ilike(search_filter),
                User.email.ilike(search_filter),
            )
        )
    query = query.order_by(Asset.asset_number.asc())
    rows = db.execute(query).all()
    return [
        AssetAllocationReportItem(
            assignment_id=row.AssetAssignment.id if row.AssetAssignment else None,
            asset_id=row.Asset.id,
            asset_number=row.Asset.asset_number,
            model=row.Asset.model,
            category_name=row.category_name,
            recipient_id=row.AssetAssignment.recipient_id if row.AssetAssignment else None,
            recipient_email=row.recipient_email or row.Asset.custodian_name,
            department_id=row.Asset.responsible_department_id,
            department_name=row.department_name,
            site_id=row.Asset.site_id,
            site_name=row.site_name,
            location_id=row.Asset.location_id,
            location_name=row.location_name,
            effective_date=row.AssetAssignment.effective_date if row.AssetAssignment else row.Asset.acquisition_date,
            status=row.Asset.status,
            reference=row.AssetAssignment.reference if row.AssetAssignment else None,
        )
        for row in rows
    ]


@router.get(
    '/reports/warranty-expiry',
    response_model=list[WarrantyExpiryReportItem],
    dependencies=[Depends(require_permission('maintenance.read'))],
)
def report_warranty_expiry(
    company_id: UUID,
    contract_type: str | None = None,
    coverage_status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            AssetServiceContract,
            Asset.asset_number.label('asset_number'),
            Asset.model.label('asset_model'),
            Supplier.name.label('supplier_name'),
        )
        .join(Asset, Asset.id == AssetServiceContract.asset_id)
        .outerjoin(Supplier, Supplier.id == AssetServiceContract.supplier_id)
        .where(AssetServiceContract.company_id == company_id)
    )
    if contract_type:
        query = query.where(AssetServiceContract.contract_type == contract_type)
    if search:
        search_filter = f'%{search.strip()}%'
        query = query.where(
            or_(
                AssetServiceContract.reference_number.ilike(search_filter),
                AssetServiceContract.provider_name.ilike(search_filter),
                Supplier.name.ilike(search_filter),
                Asset.asset_number.ilike(search_filter),
            )
        )
    query = query.order_by(AssetServiceContract.end_date.asc())
    rows = db.execute(query).all()
    today = date.today()
    results = []
    for row in rows:
        contract = row.AssetServiceContract
        if contract.status == 'cancelled':
            cov_status = 'cancelled'
        elif contract.start_date > today:
            cov_status = 'upcoming'
        elif contract.end_date < today:
            cov_status = 'expired'
        elif (contract.end_date - today).days <= 30:
            cov_status = 'expiring_soon'
        else:
            cov_status = 'active'

        if coverage_status and cov_status != coverage_status:
            continue

        results.append(
            WarrantyExpiryReportItem(
                id=contract.id,
                contract_type=contract.contract_type,
                reference_number=contract.reference_number,
                provider_name=contract.provider_name,
                supplier_name=row.supplier_name,
                asset_id=contract.asset_id,
                asset_number=row.asset_number,
                asset_model=row.asset_model,
                start_date=contract.start_date,
                end_date=contract.end_date,
                days_remaining=(contract.end_date - today).days,
                status=contract.status,
                coverage_status=cov_status,
                support_contact=contract.support_contact,
            )
        )
    return results


@router.get(
    '/reports/maintenance',
    response_model=list[MaintenanceReportItem],
    dependencies=[Depends(require_permission('maintenance.read'))],
)
def report_maintenance(
    company_id: UUID,
    status: str | None = None,
    priority: str | None = None,
    asset_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    requester_alias = aliased(User)
    assignee_alias = aliased(User)
    query = (
        select(
            MaintenanceRequest,
            Asset.asset_number.label('asset_number'),
            requester_alias.email.label('requester_email'),
            assignee_alias.email.label('assignee_email'),
        )
        .join(Asset, Asset.id == MaintenanceRequest.asset_id)
        .join(requester_alias, requester_alias.id == MaintenanceRequest.requester_id)
        .outerjoin(assignee_alias, assignee_alias.id == MaintenanceRequest.assignee_id)
        .where(MaintenanceRequest.company_id == company_id)
    )
    if status:
        query = query.where(MaintenanceRequest.status == status)
    if priority:
        query = query.where(MaintenanceRequest.priority == priority)
    if asset_id:
        query = query.where(MaintenanceRequest.asset_id == asset_id)
    if search:
        search_filter = f'%{search.strip()}%'
        query = query.where(
            or_(
                MaintenanceRequest.title.ilike(search_filter),
                Asset.asset_number.ilike(search_filter),
                requester_alias.email.ilike(search_filter),
                assignee_alias.email.ilike(search_filter),
            )
        )
    query = query.order_by(MaintenanceRequest.reported_date.desc(), MaintenanceRequest.created_at.desc())
    rows = db.execute(query).all()
    return [
        MaintenanceReportItem(
            id=row.MaintenanceRequest.id,
            title=row.MaintenanceRequest.title,
            asset_id=row.MaintenanceRequest.asset_id,
            asset_number=row.asset_number,
            priority=row.MaintenanceRequest.priority,
            status=row.MaintenanceRequest.status,
            requester_email=row.requester_email,
            assignee_email=row.assignee_email,
            reported_date=row.MaintenanceRequest.reported_date,
            completed_date=row.MaintenanceRequest.completed_date,
            cost=row.MaintenanceRequest.cost,
            diagnosis=row.MaintenanceRequest.diagnosis,
            work_performed=row.MaintenanceRequest.work_performed,
            resolution_notes=row.MaintenanceRequest.resolution_notes,
        )
        for row in rows
    ]


@router.get(
    '/reports/procurement',
    response_model=list[ProcurementReportItem],
    dependencies=[Depends(require_permission('procurement.read'))],
)
def report_procurement(
    company_id: UUID,
    status: str | None = None,
    supplier_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            PurchaseOrder,
            Supplier.name.label('supplier_name'),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(PurchaseOrder.company_id == company_id)
    )
    if status:
        query = query.where(PurchaseOrder.status == status)
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if search:
        search_filter = f'%{search.strip()}%'
        query = query.where(
            or_(
                PurchaseOrder.order_number.ilike(search_filter),
                Supplier.name.ilike(search_filter),
            )
        )
    query = query.order_by(PurchaseOrder.ordered_date.desc(), PurchaseOrder.created_at.desc())
    po_rows = db.execute(query).all()

    items = []
    for po_row in po_rows:
        order = po_row.PurchaseOrder
        lines = (
            db.execute(
                select(
                    PurchaseOrderLine,
                    AssetCategory.name.label('category_name'),
                )
                .join(AssetCategory, AssetCategory.id == PurchaseOrderLine.category_id)
                .where(
                    PurchaseOrderLine.company_id == company_id,
                    PurchaseOrderLine.purchase_order_id == order.id,
                )
                .order_by(PurchaseOrderLine.id)
            )
            .all()
        )

        receipts = db.scalars(
            select(GoodsReceipt.receipt_number)
            .where(
                GoodsReceipt.company_id == company_id,
                GoodsReceipt.purchase_order_id == order.id,
            )
            .order_by(GoodsReceipt.received_date.desc())
        ).all()

        line_items = []
        total_ordered = 0
        total_received = 0
        total_outstanding = 0

        for line_row in lines:
            line = line_row.PurchaseOrderLine
            rec_sums = db.execute(
                select(
                    func.coalesce(func.sum(GoodsReceiptLine.quantity_received), 0),
                    func.coalesce(func.sum(GoodsReceiptLine.quantity_rejected), 0),
                ).where(
                    GoodsReceiptLine.company_id == company_id,
                    GoodsReceiptLine.purchase_order_line_id == line.id,
                )
            ).first()
            qty_recv = rec_sums[0] if rec_sums else 0
            qty_rej = rec_sums[1] if rec_sums else 0
            qty_out = max(0, line.quantity_ordered - qty_recv)

            total_ordered += line.quantity_ordered
            total_received += qty_recv
            total_outstanding += qty_out

            line_items.append(
                ProcurementReportLineItem(
                    line_id=line.id,
                    category_id=line.category_id,
                    category_name=line_row.category_name,
                    description=line.description,
                    quantity_ordered=line.quantity_ordered,
                    quantity_received=qty_recv,
                    quantity_rejected=qty_rej,
                    quantity_outstanding=qty_out,
                    unit_cost=Decimal(str(line.unit_cost)),
                )
            )

        items.append(
            ProcurementReportItem(
                order_id=order.id,
                order_number=order.order_number,
                supplier_id=order.supplier_id,
                supplier_name=po_row.supplier_name,
                ordered_date=order.ordered_date,
                expected_date=order.expected_date,
                order_status=order.status,
                total_ordered_quantity=total_ordered,
                total_received_quantity=total_received,
                total_outstanding_quantity=total_outstanding,
                lines=line_items,
                receipt_numbers=list(receipts),
            )
        )
    return items
