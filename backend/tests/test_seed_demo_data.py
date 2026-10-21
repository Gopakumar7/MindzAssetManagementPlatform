from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.cli.seed_demo_data import SeederOptions, seed_demo_data
from app.models import (
    Asset,
    AssetAlert,
    AssetAssignment,
    AssetCategory,
    AssetDepreciationEntry,
    AssetDisposal,
    AssetFinancial,
    AssetServiceContract,
    Company,
    CompanyMembership,
    CostCenter,
    Department,
    GoodsReceipt,
    GoodsReceiptLine,
    Location,
    MaintenanceRequest,
    Notification,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    ScheduledJobExecution,
    Site,
    Supplier,
    User,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
)


def _setup_target_company(db_session, code: str = 'TEST-SEED-CO') -> Company:
    company = Company(code=code, name=f'Test Company {code}', is_active=True)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company


def test_seed_demo_data_initial_population(db_session):
    """Verifies that all entity types are populated with valid relationships on initial run."""
    company = _setup_target_company(db_session, 'SEED-INIT-1')
    options = SeederOptions(company_id=company.id, dry_run=False, auto_confirm=True)

    summary = seed_demo_data(db_session, options)

    assert summary.company_id == company.id
    assert summary.company_code == 'SEED-INIT-1'
    assert summary.total_created > 0
    assert summary.total_already_present == 0

    # 1. Master data assertions
    depts = db_session.scalars(select(Department).where(Department.company_id == company.id)).all()
    assert len(depts) == 5
    dept_codes = {d.code for d in depts}
    assert {'DEMO-IT', 'DEMO-ENG', 'DEMO-OPS', 'DEMO-FIN', 'DEMO-SALES'}.issubset(dept_codes)

    sites = db_session.scalars(select(Site).where(Site.company_id == company.id)).all()
    assert len(sites) == 3

    locations = db_session.scalars(select(Location).where(Location.company_id == company.id)).all()
    assert len(locations) == 6
    # Location FKs to sites
    for loc in locations:
        assert loc.site_id in {s.id for s in sites}

    cost_centers = db_session.scalars(select(CostCenter).where(CostCenter.company_id == company.id)).all()
    assert len(cost_centers) == 4

    categories = db_session.scalars(select(AssetCategory).where(AssetCategory.company_id == company.id)).all()
    assert len(categories) >= 6

    # 2. Suppliers and Procurement assertions
    suppliers = db_session.scalars(select(Supplier).where(Supplier.company_id == company.id)).all()
    assert len(suppliers) == 4

    orders = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == company.id)).all()
    assert len(orders) == 3
    order_nums = {o.order_number: o for o in orders}
    assert 'DEMO-PO-2026-001' in order_nums
    assert order_nums['DEMO-PO-2026-001'].status == 'received'
    assert 'DEMO-PO-2026-002' in order_nums
    assert order_nums['DEMO-PO-2026-002'].status == 'partially_received'
    assert 'DEMO-PO-2026-003' in order_nums
    assert order_nums['DEMO-PO-2026-003'].status == 'open'

    receipts = db_session.scalars(select(GoodsReceipt).where(GoodsReceipt.company_id == company.id)).all()
    assert len(receipts) == 2

    # 3. Asset register assertions
    assets = db_session.scalars(select(Asset).where(Asset.company_id == company.id)).all()
    assert len(assets) >= 15
    statuses = {a.status for a in assets}
    assert {'in_stock', 'assigned', 'maintenance', 'disposed'}.issubset(statuses)

    # Assets linked to goods receipt lines
    linked_grn_assets = [a for a in assets if a.goods_receipt_line_id is not None]
    assert len(linked_grn_assets) >= 7

    # 4. Assignments assertions
    assignments = db_session.scalars(select(AssetAssignment).where(AssetAssignment.company_id == company.id)).all()
    assert len(assignments) >= 5
    asg_statuses = {asg.status for asg in assignments}
    assert {'active', 'returned'}.issubset(asg_statuses)

    # 5. Service contracts assertions
    contracts = db_session.scalars(select(AssetServiceContract).where(AssetServiceContract.company_id == company.id)).all()
    assert len(contracts) == 5
    types = {c.contract_type for c in contracts}
    assert {'warranty', 'amc'}.issubset(types)

    # 6. Maintenance requests assertions
    maint_reqs = db_session.scalars(select(MaintenanceRequest).where(MaintenanceRequest.company_id == company.id)).all()
    assert len(maint_reqs) == 4
    priorities = {m.priority for m in maint_reqs}
    assert {'urgent', 'high', 'normal', 'low'}.issubset(priorities)

    # 7. Financial lifecycle assertions
    financials = db_session.scalars(select(AssetFinancial).where(AssetFinancial.company_id == company.id)).all()
    assert len(financials) == len(assets)
    deprec_entries = db_session.scalars(select(AssetDepreciationEntry).where(AssetDepreciationEntry.company_id == company.id)).all()
    assert len(deprec_entries) >= 6

    disposals = db_session.scalars(select(AssetDisposal).where(AssetDisposal.company_id == company.id)).all()
    assert len(disposals) == 1
    assert disposals[0].gain_loss == Decimal('50.00')

    # 8. Verification assertions
    campaigns = db_session.scalars(select(VerificationCampaign).where(VerificationCampaign.company_id == company.id)).all()
    assert len(campaigns) == 1
    expected = db_session.scalars(select(VerificationExpectedAsset).where(VerificationExpectedAsset.company_id == company.id)).all()
    assert len(expected) >= 10
    observations = db_session.scalars(select(VerificationObservation).where(VerificationObservation.company_id == company.id)).all()
    assert len(observations) == 3
    discrepancies = db_session.scalars(select(VerificationDiscrepancy).where(VerificationDiscrepancy.company_id == company.id)).all()
    assert len(discrepancies) == 2

    # 9. Alerts and notifications assertions
    alerts = db_session.scalars(select(AssetAlert).where(AssetAlert.company_id == company.id)).all()
    assert len(alerts) >= 5
    alert_types = {al.alert_type for al in alerts}
    assert 'warranty_expiry' in alert_types
    assert 'maintenance_overdue' in alert_types

    notifications = db_session.scalars(select(Notification).where(Notification.company_id == company.id)).all()
    assert len(notifications) >= 1

    jobs = db_session.scalars(select(ScheduledJobExecution).where(ScheduledJobExecution.status == 'completed')).all()
    assert len(jobs) >= 1


def test_seed_demo_data_idempotency_no_duplicates(db_session):
    """Running seeder a second time on the same company must produce 0 new records and 0 duplicates."""
    company = _setup_target_company(db_session, 'SEED-IDEMP-1')
    options = SeederOptions(company_id=company.id, dry_run=False, auto_confirm=True)

    # First execution
    summary1 = seed_demo_data(db_session, options)
    created_run1 = summary1.total_created
    assert created_run1 > 0

    # Snapshot entity counts after Run 1
    counts_run1 = {
        'departments': db_session.scalar(select(func.count(Department.id)).where(Department.company_id == company.id)),
        'sites': db_session.scalar(select(func.count(Site.id)).where(Site.company_id == company.id)),
        'locations': db_session.scalar(select(func.count(Location.id)).where(Location.company_id == company.id)),
        'cost_centers': db_session.scalar(select(func.count(CostCenter.id)).where(CostCenter.company_id == company.id)),
        'suppliers': db_session.scalar(select(func.count(Supplier.id)).where(Supplier.company_id == company.id)),
        'purchase_orders': db_session.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == company.id)),
        'goods_receipts': db_session.scalar(select(func.count(GoodsReceipt.id)).where(GoodsReceipt.company_id == company.id)),
        'assets': db_session.scalar(select(func.count(Asset.id)).where(Asset.company_id == company.id)),
        'assignments': db_session.scalar(select(func.count(AssetAssignment.id)).where(AssetAssignment.company_id == company.id)),
        'contracts': db_session.scalar(select(func.count(AssetServiceContract.id)).where(AssetServiceContract.company_id == company.id)),
        'maintenance_requests': db_session.scalar(select(func.count(MaintenanceRequest.id)).where(MaintenanceRequest.company_id == company.id)),
        'financials': db_session.scalar(select(func.count(AssetFinancial.id)).where(AssetFinancial.company_id == company.id)),
        'depreciation_entries': db_session.scalar(select(func.count(AssetDepreciationEntry.id)).where(AssetDepreciationEntry.company_id == company.id)),
        'disposals': db_session.scalar(select(func.count(AssetDisposal.id)).where(AssetDisposal.company_id == company.id)),
        'campaigns': db_session.scalar(select(func.count(VerificationCampaign.id)).where(VerificationCampaign.company_id == company.id)),
    }

    # Second execution on identical company
    summary2 = seed_demo_data(db_session, options)

    # Zero new master records created on second pass
    assert summary2.counts['Department'].created == 0
    assert summary2.counts['Site'].created == 0
    assert summary2.counts['Location'].created == 0
    assert summary2.counts['Cost Center'].created == 0
    assert summary2.counts['Supplier'].created == 0
    assert summary2.counts['Purchase Order'].created == 0
    assert summary2.counts['Goods Receipt'].created == 0
    assert summary2.counts['Asset'].created == 0
    assert summary2.counts['Asset Assignment'].created == 0
    assert summary2.counts['Service Contract'].created == 0
    assert summary2.counts['Maintenance Request'].created == 0
    assert summary2.counts['Financial Profile'].created == 0
    assert summary2.counts['Depreciation Entry'].created == 0
    assert summary2.counts['Asset Disposal'].created == 0
    assert summary2.counts['Verification Campaign'].created == 0

    # Snapshot entity counts after Run 2
    counts_run2 = {
        'departments': db_session.scalar(select(func.count(Department.id)).where(Department.company_id == company.id)),
        'sites': db_session.scalar(select(func.count(Site.id)).where(Site.company_id == company.id)),
        'locations': db_session.scalar(select(func.count(Location.id)).where(Location.company_id == company.id)),
        'cost_centers': db_session.scalar(select(func.count(CostCenter.id)).where(CostCenter.company_id == company.id)),
        'suppliers': db_session.scalar(select(func.count(Supplier.id)).where(Supplier.company_id == company.id)),
        'purchase_orders': db_session.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == company.id)),
        'goods_receipts': db_session.scalar(select(func.count(GoodsReceipt.id)).where(GoodsReceipt.company_id == company.id)),
        'assets': db_session.scalar(select(func.count(Asset.id)).where(Asset.company_id == company.id)),
        'assignments': db_session.scalar(select(func.count(AssetAssignment.id)).where(AssetAssignment.company_id == company.id)),
        'contracts': db_session.scalar(select(func.count(AssetServiceContract.id)).where(AssetServiceContract.company_id == company.id)),
        'maintenance_requests': db_session.scalar(select(func.count(MaintenanceRequest.id)).where(MaintenanceRequest.company_id == company.id)),
        'financials': db_session.scalar(select(func.count(AssetFinancial.id)).where(AssetFinancial.company_id == company.id)),
        'depreciation_entries': db_session.scalar(select(func.count(AssetDepreciationEntry.id)).where(AssetDepreciationEntry.company_id == company.id)),
        'disposals': db_session.scalar(select(func.count(AssetDisposal.id)).where(AssetDisposal.company_id == company.id)),
        'campaigns': db_session.scalar(select(func.count(VerificationCampaign.id)).where(VerificationCampaign.company_id == company.id)),
    }

    # All counts must be perfectly identical
    assert counts_run1 == counts_run2


def test_seed_demo_data_preserves_preexisting_data(db_session):
    """Verifies that pre-existing custom user records are never deleted or corrupted."""
    company = _setup_target_company(db_session, 'SEED-PRESERVE-1')

    # Create pre-existing custom department and category
    custom_dept = Department(company_id=company.id, code='CUSTOM-DEPT-99', name='Pre-existing Custom Dept', is_active=True)
    custom_cat = AssetCategory(company_id=company.id, code='CUSTOM-CAT-99', name='Pre-existing Custom Cat', is_active=True)
    db_session.add_all([custom_dept, custom_cat])
    db_session.commit()

    # Create custom pre-existing asset
    custom_asset = Asset(
        company_id=company.id,
        category_id=custom_cat.id,
        asset_number='CUSTOM-AST-9999',
        serial_number='CUSTOM-SN-9999',
        model='Legacy Bespoke Mainframe',
        status='in_stock',
        responsible_department_id=custom_dept.id,
    )
    db_session.add(custom_asset)
    db_session.commit()

    options = SeederOptions(company_id=company.id, dry_run=False, auto_confirm=True)
    summary = seed_demo_data(db_session, options)

    assert summary.total_created > 0

    # Assert pre-existing asset still exists untouched
    preserved_asset = db_session.scalar(
        select(Asset).where(Asset.company_id == company.id, Asset.serial_number == 'CUSTOM-SN-9999')
    )
    assert preserved_asset is not None
    assert preserved_asset.asset_number == 'CUSTOM-AST-9999'
    assert preserved_asset.model == 'Legacy Bespoke Mainframe'
    assert preserved_asset.responsible_department_id == custom_dept.id

    # Assert pre-existing dept and cat still exist untouched
    preserved_dept = db_session.scalar(
        select(Department).where(Department.company_id == company.id, Department.code == 'CUSTOM-DEPT-99')
    )
    assert preserved_dept is not None
    assert preserved_dept.name == 'Pre-existing Custom Dept'


def test_seed_demo_data_dry_run_mode(db_session):
    """Dry run mode must compute and report summary counts without committing changes to the database."""
    company = _setup_target_company(db_session, 'SEED-DRYRUN-1')
    options = SeederOptions(company_id=company.id, dry_run=True, auto_confirm=True)

    summary = seed_demo_data(db_session, options)

    assert summary.dry_run is True
    assert summary.total_created > 0

    # Verify zero records were committed to the database
    dept_count = db_session.scalar(select(func.count(Department.id)).where(Department.company_id == company.id))
    assert dept_count == 0

    asset_count = db_session.scalar(select(func.count(Asset.id)).where(Asset.company_id == company.id))
    assert asset_count == 0

    po_count = db_session.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == company.id))
    assert po_count == 0


def test_seed_demo_data_company_isolation(db_session):
    """Seeding Company A must never insert records or alter state in Company B."""
    comp_a = _setup_target_company(db_session, 'SEED-ISO-A')
    comp_b = _setup_target_company(db_session, 'SEED-ISO-B')

    options_a = SeederOptions(company_id=comp_a.id, dry_run=False, auto_confirm=True)
    summary_a = seed_demo_data(db_session, options_a)

    assert summary_a.total_created > 0

    # Verify Company B has exactly zero assets, departments, suppliers, or POs
    assert db_session.scalar(select(func.count(Asset.id)).where(Asset.company_id == comp_b.id)) == 0
    assert db_session.scalar(select(func.count(Department.id)).where(Department.company_id == comp_b.id)) == 0
    assert db_session.scalar(select(func.count(Supplier.id)).where(Supplier.company_id == comp_b.id)) == 0
    assert db_session.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.company_id == comp_b.id)) == 0
    assert db_session.scalar(select(func.count(AssetAlert.id)).where(AssetAlert.company_id == comp_b.id)) == 0


def test_seed_demo_data_missing_company_behavior(db_session):
    """Requesting an unknown company code without --create-company must raise an error and abort safely."""
    options = SeederOptions(
        company_code='NON-EXISTENT-CO-999',
        create_company=False,
        dry_run=False,
        auto_confirm=True,
    )
    with pytest.raises(ValueError, match="does not exist"):
        seed_demo_data(db_session, options)


def test_seed_demo_data_create_company_flag(db_session):
    """Specifying a new company code with --create-company provisions it and populates data."""
    options = SeederOptions(
        company_code='PROV-DEMO-CO',
        create_company=True,
        dry_run=False,
        auto_confirm=True,
    )
    summary = seed_demo_data(db_session, options)

    assert summary.company_code == 'PROV-DEMO-CO'
    assert summary.is_new_company is True
    assert summary.total_created > 0

    # Company was persisted
    persisted = db_session.scalar(select(Company).where(Company.code == 'PROV-DEMO-CO'))
    assert persisted is not None
    assert persisted.is_active is True

