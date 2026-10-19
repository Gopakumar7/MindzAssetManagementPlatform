from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetDisposal,
    AssetFinancial,
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
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
    VerificationUnregisteredAsset,
)
from app.schemas import (
    AssetAllocationReportItem,
    AssetDepreciationReportItem,
    AssetDisposalReportItem,
    AssetRegisterReportItem,
    CategoryMetric,
    DashboardResponse,
    DepartmentMetric,
    ExpiringContractMetric,
    FinancialDashboardMetric,
    MaintenanceReportItem,
    MaintenanceSummaryMetric,
    ProcurementReportItem,
    ProcurementReportLineItem,
    ProcurementSummaryMetric,
    RecentActivityMetric,
    SiteMetric,
    VerificationCampaignReportItem,
    VerificationDiscrepancyReportItem,
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


@router.get(
    '/reports/verification-campaigns',
    response_model=list[VerificationCampaignReportItem],
    dependencies=[Depends(require_permission('verification.read'))],
)
def get_verification_campaigns_report(
    company_id: UUID,
    status_filter: str | None = Query(None, alias='status'),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    search: str | None = Query(None),
    format: str | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = select(VerificationCampaign).where(VerificationCampaign.company_id == company_id)
    if status_filter:
        query = query.where(VerificationCampaign.status == status_filter)
    if start_date:
        query = query.where(VerificationCampaign.start_date >= start_date)
    if end_date:
        query = query.where(VerificationCampaign.end_date <= end_date)
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
        total_exp = db.scalar(
            select(func.count(VerificationExpectedAsset.id)).where(
                VerificationExpectedAsset.company_id == company_id,
                VerificationExpectedAsset.campaign_id == c.id,
            )
        ) or 0
        total_ver = db.scalar(
            select(func.count(VerificationObservation.id)).where(
                VerificationObservation.company_id == company_id,
                VerificationObservation.campaign_id == c.id,
            )
        ) or 0
        total_miss = db.scalar(
            select(func.count(VerificationObservation.id)).where(
                VerificationObservation.company_id == company_id,
                VerificationObservation.campaign_id == c.id,
                VerificationObservation.is_found.is_(False),
            )
        ) or 0
        total_disc = db.scalar(
            select(func.count(VerificationDiscrepancy.id)).where(
                VerificationDiscrepancy.company_id == company_id,
                VerificationDiscrepancy.campaign_id == c.id,
            )
        ) or 0
        total_unreg = db.scalar(
            select(func.count(VerificationUnregisteredAsset.id)).where(
                VerificationUnregisteredAsset.company_id == company_id,
                VerificationUnregisteredAsset.campaign_id == c.id,
            )
        ) or 0
        pct = round((total_ver / total_exp * 100.0), 1) if total_exp > 0 else 0.0

        items.append(
            VerificationCampaignReportItem(
                campaign_id=c.id,
                campaign_reference=c.campaign_reference,
                campaign_name=c.name,
                status=c.status,
                start_date=c.start_date,
                end_date=c.end_date,
                total_expected=total_exp,
                total_verified=total_ver,
                total_missing=total_miss,
                discrepancy_count=total_disc,
                unregistered_count=total_unreg,
                completion_percentage=pct,
                created_at=c.created_at,
                completed_at=c.completed_at,
            )
        )

    if format == 'csv':
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Campaign Reference', 'Campaign Name', 'Status', 'Start Date', 'End Date', 'Expected Assets', 'Verified Assets', 'Missing Assets', 'Discrepancies', 'Unregistered Assets', 'Completion %'])
        for item in items:
            writer.writerow([
                item.campaign_reference, item.campaign_name, item.status, item.start_date, item.end_date,
                item.total_expected, item.total_verified, item.total_missing, item.discrepancy_count, item.unregistered_count, item.completion_percentage,
            ])
        return Response(content=buf.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="verification-campaigns.csv"'})

    return items


@router.get(
    '/reports/verification-discrepancies',
    response_model=list[VerificationDiscrepancyReportItem],
    dependencies=[Depends(require_permission('verification.read'))],
)
def get_verification_discrepancies_report(
    company_id: UUID,
    campaign_id: UUID | None = Query(None),
    discrepancy_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias='status'),
    format: str | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            VerificationDiscrepancy,
            VerificationCampaign.campaign_reference,
            VerificationCampaign.name.label('campaign_name'),
            Asset.asset_number,
            User.email.label('resolved_by_name'),
        )
        .join(VerificationCampaign, VerificationCampaign.id == VerificationDiscrepancy.campaign_id)
        .outerjoin(Asset, Asset.id == VerificationDiscrepancy.asset_id)
        .outerjoin(User, User.id == VerificationDiscrepancy.resolved_by_id)
        .where(VerificationDiscrepancy.company_id == company_id)
    )
    if campaign_id:
        query = query.where(VerificationDiscrepancy.campaign_id == campaign_id)
    if discrepancy_type:
        query = query.where(VerificationDiscrepancy.discrepancy_type == discrepancy_type)
    if status_filter:
        query = query.where(VerificationDiscrepancy.status == status_filter)
    query = query.order_by(VerificationDiscrepancy.created_at.desc())
    rows = db.execute(query).all()

    items = []
    for r in rows:
        d = r.VerificationDiscrepancy
        exp_summary = str(d.expected_data) if d.expected_data else None
        obs_summary = str(d.observed_data) if d.observed_data else None
        items.append(
            VerificationDiscrepancyReportItem(
                discrepancy_id=d.id,
                campaign_reference=r.campaign_reference,
                campaign_name=r.campaign_name,
                asset_number=r.asset_number,
                discrepancy_type=d.discrepancy_type,
                status=d.status,
                expected_summary=exp_summary,
                observed_summary=obs_summary,
                notes=d.notes,
                resolution_action=d.resolution_action,
                resolution_notes=d.resolution_notes,
                resolved_by_name=r.resolved_by_name,
                resolved_at=d.resolved_at,
                created_at=d.created_at,
            )
        )

    if format == 'csv':
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Discrepancy ID', 'Campaign Reference', 'Asset Number', 'Type', 'Status', 'Resolution Action', 'Resolution Notes', 'Resolved By', 'Resolved At'])
        for item in items:
            writer.writerow([
                str(item.discrepancy_id), item.campaign_reference, item.asset_number or '', item.discrepancy_type,
                item.status, item.resolution_action or '', item.resolution_notes or '', item.resolved_by_name or '', item.resolved_at or '',
            ])
        return Response(content=buf.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="verification-discrepancies.csv"'})

    return items


@router.get(
    '/reports/asset-depreciation',
    response_model=list[AssetDepreciationReportItem],
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_asset_depreciation_report(
    company_id: UUID,
    category_id: UUID | None = Query(None),
    site_id: UUID | None = Query(None),
    location_id: UUID | None = Query(None),
    financial_status: str | None = Query(None),
    format: str | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            Asset,
            AssetFinancial,
            AssetCategory.name.label('category_name'),
            Site.name.label('site_name'),
            Location.name.label('location_name'),
        )
        .join(AssetFinancial, (AssetFinancial.company_id == Asset.company_id) & (AssetFinancial.asset_id == Asset.id))
        .join(AssetCategory, (AssetCategory.company_id == Asset.company_id) & (AssetCategory.id == Asset.category_id))
        .outerjoin(Site, (Site.company_id == Asset.company_id) & (Site.id == Asset.site_id))
        .outerjoin(Location, (Location.company_id == Asset.company_id) & (Location.id == Asset.location_id))
        .where(Asset.company_id == company_id)
    )
    if category_id:
        query = query.where(Asset.category_id == category_id)
    if site_id:
        query = query.where(Asset.site_id == site_id)
    if location_id:
        query = query.where(Asset.location_id == location_id)
    if financial_status:
        query = query.where(AssetFinancial.financial_status == financial_status)

    query = query.order_by(Asset.asset_number.asc())
    rows = db.execute(query).all()

    items = [
        AssetDepreciationReportItem(
            asset_id=r.Asset.id,
            asset_number=r.Asset.asset_number,
            asset_name=r.Asset.model or r.Asset.asset_number,
            category_name=r.category_name,
            site_name=r.site_name,
            location_name=r.location_name,
            acquisition_date=r.Asset.acquisition_date,
            capitalised_cost=r.AssetFinancial.capitalised_cost,
            currency=r.AssetFinancial.currency,
            depreciation_method=r.AssetFinancial.depreciation_method,
            useful_life_months=r.AssetFinancial.useful_life_months,
            residual_value=r.AssetFinancial.residual_value,
            depreciation_start_date=r.AssetFinancial.depreciation_start_date,
            accumulated_depreciation=r.AssetFinancial.accumulated_depreciation,
            current_book_value=r.AssetFinancial.current_book_value,
            financial_status=r.AssetFinancial.financial_status,
        )
        for r in rows
    ]

    if format == 'csv':
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            'Asset Number', 'Asset Name', 'Category', 'Site', 'Location',
            'Acquisition Date', 'Capitalised Cost', 'Currency', 'Method',
            'Useful Life (Months)', 'Residual Value', 'Depreciation Start Date',
            'Accumulated Depreciation', 'Current Book Value', 'Financial Status',
        ])
        for item in items:
            writer.writerow([
                item.asset_number, item.asset_name, item.category_name,
                item.site_name or '', item.location_name or '',
                item.acquisition_date or '', str(item.capitalised_cost), item.currency,
                item.depreciation_method, item.useful_life_months, str(item.residual_value),
                item.depreciation_start_date, str(item.accumulated_depreciation),
                str(item.current_book_value), item.financial_status,
            ])
        return Response(
            content=buf.getvalue(),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename="asset-depreciation.csv"'},
        )

    return items


@router.get(
    '/reports/asset-disposals',
    response_model=list[AssetDisposalReportItem],
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_asset_disposals_report(
    company_id: UUID,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    disposal_reason: str | None = Query(None),
    disposal_method: str | None = Query(None),
    format: str | None = Query(None),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(
            AssetDisposal,
            Asset.asset_number,
            Asset.model.label('asset_name'),
            AssetCategory.name.label('category_name'),
            Asset.acquisition_date,
            Asset.acquisition_cost,
            User.email.label('disposed_by_email'),
        )
        .join(Asset, (Asset.company_id == AssetDisposal.company_id) & (Asset.id == AssetDisposal.asset_id))
        .join(AssetCategory, (AssetCategory.company_id == Asset.company_id) & (AssetCategory.id == Asset.category_id))
        .outerjoin(User, User.id == AssetDisposal.disposed_by_id)
        .where(AssetDisposal.company_id == company_id)
    )
    if start_date:
        query = query.where(AssetDisposal.disposal_date >= start_date)
    if end_date:
        query = query.where(AssetDisposal.disposal_date <= end_date)
    if disposal_reason:
        query = query.where(AssetDisposal.disposal_reason == disposal_reason)
    if disposal_method:
        query = query.where(AssetDisposal.disposal_method == disposal_method)

    query = query.order_by(AssetDisposal.disposal_date.desc(), AssetDisposal.created_at.desc())
    rows = db.execute(query).all()

    items = [
        AssetDisposalReportItem(
            asset_id=r.AssetDisposal.asset_id,
            asset_number=r.asset_number,
            asset_name=r.asset_name or r.asset_number,
            category_name=r.category_name,
            acquisition_date=r.acquisition_date,
            acquisition_cost=Decimal(str(r.acquisition_cost)) if r.acquisition_cost is not None else None,
            disposal_date=r.AssetDisposal.disposal_date,
            disposal_reason=r.AssetDisposal.disposal_reason,
            disposal_method=r.AssetDisposal.disposal_method,
            sale_proceeds=r.AssetDisposal.sale_proceeds,
            net_book_value_at_disposal=r.AssetDisposal.net_book_value_at_disposal,
            gain_loss=r.AssetDisposal.gain_loss,
            disposed_by_email=r.disposed_by_email,
            notes=r.AssetDisposal.notes,
        )
        for r in rows
    ]

    if format == 'csv':
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            'Asset Number', 'Asset Name', 'Category', 'Acquisition Date', 'Acquisition Cost',
            'Disposal Date', 'Disposal Reason', 'Disposal Method', 'Sale Proceeds',
            'Net Book Value at Disposal', 'Gain/Loss', 'Disposed By', 'Notes',
        ])
        for item in items:
            writer.writerow([
                item.asset_number, item.asset_name, item.category_name,
                item.acquisition_date or '', str(item.acquisition_cost) if item.acquisition_cost is not None else '',
                item.disposal_date, item.disposal_reason, item.disposal_method,
                str(item.sale_proceeds), str(item.net_book_value_at_disposal),
                str(item.gain_loss), item.disposed_by_email or '', item.notes or '',
            ])
        return Response(
            content=buf.getvalue(),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename="asset-disposals.csv"'},
        )

    return items


@router.get(
    '/dashboard/financial',
    response_model=FinancialDashboardMetric,
    dependencies=[Depends(require_permission('finance.read'))],
)
def get_financial_dashboard_metrics(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)

    # 1. Active / in-service financial summaries
    active_financials = db.scalars(
        select(AssetFinancial)
        .where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.financial_status.in_(['active', 'fully_depreciated']),
        )
    ).all()

    total_cost = sum((f.capitalised_cost for f in active_financials), Decimal('0.00'))
    total_accum = sum((f.accumulated_depreciation for f in active_financials), Decimal('0.00'))
    total_nbv = sum((f.current_book_value for f in active_financials), Decimal('0.00'))

    # Approaching EOL: useful life <= 3 months remaining
    from app.models import AssetDepreciationEntry
    approaching_eol = 0
    for f in active_financials:
        if f.financial_status == 'active':
            posted_count = db.scalar(
                select(func.count(AssetDepreciationEntry.id)).where(
                    AssetDepreciationEntry.company_id == company_id,
                    AssetDepreciationEntry.asset_id == f.asset_id,
                )
            ) or 0
            remaining_months = f.useful_life_months - posted_count
            if 0 < remaining_months <= 3:
                approaching_eol += 1

    # Fully depreciated but still in service (status != 'disposed')
    fully_depreciated_active = db.scalar(
        select(func.count(AssetFinancial.id))
        .join(Asset, (Asset.company_id == AssetFinancial.company_id) & (Asset.id == AssetFinancial.asset_id))
        .where(
            AssetFinancial.company_id == company_id,
            AssetFinancial.financial_status == 'fully_depreciated',
            Asset.status != 'disposed',
        )
    ) or 0

    # Disposal aggregates
    disposals = db.scalars(
        select(AssetDisposal).where(AssetDisposal.company_id == company_id)
    ).all()

    disposed_count = len(disposals)
    total_proceeds = sum((d.sale_proceeds for d in disposals), Decimal('0.00'))
    total_gain_loss = sum((d.gain_loss for d in disposals), Decimal('0.00'))

    return FinancialDashboardMetric(
        total_capitalised_cost=total_cost,
        total_accumulated_depreciation=total_accum,
        total_net_book_value=total_nbv,
        approaching_eol_count=approaching_eol,
        fully_depreciated_active_count=fully_depreciated_active,
        disposed_count=disposed_count,
        total_disposal_proceeds=total_proceeds,
        total_disposal_gain_loss=total_gain_loss,
    )
