"""Safe, repeatable, and idempotent sample demonstration data seeder for MindZen ALCM/ITAM.

Can be run on EC2 via Docker Compose:
    docker compose exec backend python -m app.cli.seed_demo_data [OPTIONS]
or via the host shell script wrapper:
    ./scripts/seed_demo_data.sh [OPTIONS]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging
import re
import socket
import sys
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.alert_service import sync_company_alerts
from app.audit import record_security_event
from app.authentication import INVITATION_LIFETIME, digest, normalize_email
from app.core.config import settings
from app.database import SessionLocal, engine
from app.finance_service import calculate_monthly_depreciation
from app.models import (
    Asset,
    AssetAlert,
    AssetAssignment,
    AssetCategory,
    AssetDepartmentUsage,
    AssetDepreciationEntry,
    AssetDisposal,
    AssetFinancial,
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
    Notification,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    ScheduledJobExecution,
    Site,
    Supplier,
    User,
    UserInvitation,
    VerificationCampaign,
    VerificationDiscrepancy,
    VerificationExpectedAsset,
    VerificationObservation,
)
from app.notification_service import NotificationService
from app.security_seed import seed_security_defaults
from app.services import INITIAL_CATEGORIES, next_asset_number

logger = logging.getLogger('demo_seeder')

DEMO_COMPANY_CODE = 'DEMO-CORP'
DEMO_COMPANY_NAME = 'MindZen Demonstration Corp'
DEMO_PREFIX = 'MZ'


@dataclass
class SeederOptions:
    company_code: str | None = None
    company_id: UUID | None = None
    create_company: bool = False
    dry_run: bool = False
    interactive: bool = True
    auto_confirm: bool = False


@dataclass
class EntityCounts:
    created: int = 0
    already_present: int = 0

    @property
    def total(self) -> int:
        return self.created + self.already_present


@dataclass
class SeedingSummary:
    company_id: UUID
    company_code: str
    company_name: str
    is_new_company: bool = False
    dry_run: bool = False
    counts: dict[str, EntityCounts] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, entity_name: str, created: bool) -> None:
        if entity_name not in self.counts:
            self.counts[entity_name] = EntityCounts()
        if created:
            self.counts[entity_name].created += 1
        else:
            self.counts[entity_name].already_present += 1

    @property
    def total_created(self) -> int:
        return sum(c.created for c in self.counts.values())

    @property
    def total_already_present(self) -> int:
        return sum(c.already_present for c in self.counts.values())


def _mask_url(url: str) -> str:
    """Masks database password in connection string for safe display."""
    return re.sub(r':([^@/?]+)@', ':***@', url)


def _resolve_target_company(db: Session, options: SeederOptions) -> tuple[Company, bool]:
    """Resolves target company or safely provisions the demo company."""
    if options.company_id:
        company = db.get(Company, options.company_id)
        if not company:
            raise ValueError(f"Company with ID '{options.company_id}' not found.")
        return company, False

    if options.company_code:
        company = db.scalar(select(Company).where(Company.code == options.company_code.strip()))
        if company:
            return company, False
        if options.create_company or options.company_code.strip() == DEMO_COMPANY_CODE:
            company = Company(
                code=options.company_code.strip(),
                name=f"{options.company_code.strip()} (MindZen ALCM)",
                is_active=True,
            )
            db.add(company)
            db.flush()
            return company, True
        raise ValueError(
            f"Company with code '{options.company_code}' does not exist. "
            "Use --create-company to provision it."
        )

    # No code or ID specified: check existing companies
    existing_demo = db.scalar(select(Company).where(Company.code == DEMO_COMPANY_CODE))
    if existing_demo:
        return existing_demo, False

    active_companies = db.scalars(select(Company).where(Company.is_active == True).order_by(Company.created_at)).all()
    if len(active_companies) == 1:
        return active_companies[0], False

    if len(active_companies) > 1:
        codes = [c.code for c in active_companies]
        if not options.interactive or options.auto_confirm:
            raise ValueError(
                f"Multiple active companies exist: {codes}. "
                "Specify target company with --company-code <code>."
            )
        print("\nAvailable Companies in Database:")
        for idx, comp in enumerate(active_companies, 1):
            print(f"  [{idx}] {comp.code} - {comp.name} (ID: {comp.id})")
        print(f"  [0] Create dedicated demo company ({DEMO_COMPANY_CODE})")
        choice = input(f"Select company to populate [1-{len(active_companies)}] or 0: ").strip()
        if choice == '0':
            company = Company(code=DEMO_COMPANY_CODE, name=DEMO_COMPANY_NAME, is_active=True)
            db.add(company)
            db.flush()
            return company, True
        try:
            chosen_idx = int(choice) - 1
            if 0 <= chosen_idx < len(active_companies):
                return active_companies[chosen_idx], False
        except ValueError:
            pass
        raise ValueError("Invalid company selection.")

    # No companies in database at all
    company = Company(code=DEMO_COMPANY_CODE, name=DEMO_COMPANY_NAME, is_active=True)
    db.add(company)
    db.flush()
    return company, True


def seed_demo_data(db: Session, options: SeederOptions) -> SeedingSummary:
    """Idempotently seeds realistic demonstration data into the target company."""
    # 0. Ensure system security roles and permissions are installed
    seed_security_defaults(db, commit=False)

    company, is_new_company = _resolve_target_company(db, options)
    summary = SeedingSummary(
        company_id=company.id,
        company_code=company.code,
        company_name=company.name,
        is_new_company=is_new_company,
        dry_run=options.dry_run,
    )

    today = date.today()
    now = datetime.now(timezone.utc)

    # 1. Numbering rule
    default_rule = db.scalar(
        select(AssetNumberRule).where(
            AssetNumberRule.company_id == company.id,
            AssetNumberRule.category_id.is_(None),
        )
    )
    if not default_rule:
        default_rule = AssetNumberRule(
            company_id=company.id,
            prefix=DEMO_PREFIX,
            separator='-',
            padding=6,
            next_value=1,
        )
        db.add(default_rule)
        db.flush()
        summary.record('Asset Number Rule', created=True)
    else:
        summary.record('Asset Number Rule', created=False)

    # 2. Asset Categories
    category_map: dict[str, AssetCategory] = {}
    for code, name in INITIAL_CATEGORIES:
        cat = db.scalar(
            select(AssetCategory).where(
                AssetCategory.company_id == company.id,
                AssetCategory.code == code,
            )
        )
        if not cat:
            cat = AssetCategory(company_id=company.id, code=code, name=name, is_active=True)
            db.add(cat)
            db.flush()
            summary.record('Asset Category', created=True)
        else:
            summary.record('Asset Category', created=False)
        category_map[code] = cat

    # 3. Departments
    dept_definitions = [
        ('DEMO-IT', 'Information Technology'),
        ('DEMO-ENG', 'Engineering & Product'),
        ('DEMO-OPS', 'Operations & Facilities'),
        ('DEMO-FIN', 'Finance & Accounting'),
        ('DEMO-SALES', 'Global Sales & Marketing'),
    ]
    dept_map: dict[str, Department] = {}
    for code, name in dept_definitions:
        dept = db.scalar(
            select(Department).where(Department.company_id == company.id, Department.code == code)
        )
        if not dept:
            dept = Department(company_id=company.id, code=code, name=name, is_active=True)
            db.add(dept)
            db.flush()
            summary.record('Department', created=True)
        else:
            summary.record('Department', created=False)
        dept_map[code] = dept

    # 4. Sites
    site_definitions = [
        ('DEMO-HQ', 'Corporate Headquarters', '100 Innovation Way, Tech Park, Suite 500'),
        ('DEMO-TECH', 'Silicon Valley Engineering Lab', '450 Research Boulevard, San Jose, CA'),
        ('DEMO-DC', 'Dallas Secure Data Center', '800 Datacenter Expressway, Dallas, TX'),
    ]
    site_map: dict[str, Site] = {}
    for code, name, addr in site_definitions:
        site = db.scalar(select(Site).where(Site.company_id == company.id, Site.code == code))
        if not site:
            site = Site(company_id=company.id, code=code, name=name, address=addr, is_active=True)
            db.add(site)
            db.flush()
            summary.record('Site', created=True)
        else:
            summary.record('Site', created=False)
        site_map[code] = site

    # 5. Locations
    location_definitions = [
        ('DEMO-HQ-F2', 'Executive Suite & Finance', site_map['DEMO-HQ'].id, '2nd Floor, Wing A'),
        ('DEMO-HQ-DESK', 'IT Central Service Desk', site_map['DEMO-HQ'].id, '1st Floor, Room 104'),
        ('DEMO-HQ-ENG', 'Open Engineering Space', site_map['DEMO-HQ'].id, '3rd Floor, Open Bay'),
        ('DEMO-TECH-LAB', 'Hardware Reliability Lab', site_map['DEMO-TECH'].id, 'Building B, Lab 2'),
        ('DEMO-DC-RACK1', 'Server Rack Row 1-A', site_map['DEMO-DC'].id, 'Cage 4, Rack 1-A'),
        ('DEMO-DC-RACK2', 'Server Rack Row 2-B', site_map['DEMO-DC'].id, 'Cage 4, Rack 2-B'),
    ]
    location_map: dict[str, Location] = {}
    for code, name, site_id, details in location_definitions:
        loc = db.scalar(
            select(Location).where(
                Location.company_id == company.id,
                Location.site_id == site_id,
                Location.code == code,
            )
        )
        if not loc:
            loc = Location(company_id=company.id, site_id=site_id, code=code, name=name, details=details, is_active=True)
            db.add(loc)
            db.flush()
            summary.record('Location', created=True)
        else:
            summary.record('Location', created=False)
        location_map[code] = loc

    # 6. Cost Centres
    cost_centre_definitions = [
        ('DEMO-CC-IT', 'Corporate IT Infrastructure'),
        ('DEMO-CC-RD', 'Research & Product Development'),
        ('DEMO-CC-OPS', 'Global Business Operations'),
        ('DEMO-CC-FIN', 'Corporate Financial Management'),
    ]
    cost_centre_map: dict[str, CostCenter] = {}
    for code, name in cost_centre_definitions:
        cc = db.scalar(select(CostCenter).where(CostCenter.company_id == company.id, CostCenter.code == code))
        if not cc:
            cc = CostCenter(company_id=company.id, code=code, name=name, is_active=True)
            db.add(cc)
            db.flush()
            summary.record('Cost Center', created=True)
        else:
            summary.record('Cost Center', created=False)
        cost_centre_map[code] = cc

    # 7. Custodians & Company Members
    roles = {r.code: r for r in db.scalars(select(Role).where(Role.scope == 'company')).all()}
    existing_actor = db.scalar(
        select(User)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(CompanyMembership.company_id == company.id, CompanyMembership.status == 'active')
    )

    custodian_definitions = [
        ('alex.chen@demo.mindzen.invalid', 'asset_manager', 'Alex Chen'),
        ('priya.patel@demo.mindzen.invalid', 'it_support', 'Priya Patel'),
        ('marcus.vance@demo.mindzen.invalid', 'read_only_user', 'Marcus Vance'),
        ('elena.rostova@demo.mindzen.invalid', 'read_only_user', 'Elena Rostova'),
    ]
    custodian_users: dict[str, User] = {}
    for email, role_code, full_name in custodian_definitions:
        norm_email = normalize_email(email)
        user = db.scalar(select(User).where(User.email == norm_email))
        created_user = False
        if not user:
            # Safe user without password hash (cannot authenticate via password)
            user = User(email=norm_email, password_hash=None, is_active=True)
            db.add(user)
            db.flush()
            created_user = True
            summary.record('Demo User Profile', created=True)
        else:
            summary.record('Demo User Profile', created=False)
        custodian_users[norm_email] = user

        # Membership
        membership = db.scalar(
            select(CompanyMembership).where(
                CompanyMembership.company_id == company.id,
                CompanyMembership.user_id == user.id,
            )
        )
        if not membership:
            role = roles.get(role_code) or roles.get('read_only_user')
            membership = CompanyMembership(
                company_id=company.id,
                user_id=user.id,
                role_id=role.id,
                status='active',
                assigned_by_id=existing_actor.id if existing_actor else user.id,
            )
            db.add(membership)
            db.flush()
            summary.record('Company Membership', created=True)
        else:
            summary.record('Company Membership', created=False)

    primary_actor = existing_actor or custodian_users['alex.chen@demo.mindzen.invalid']

    # 8. Suppliers
    supplier_definitions = [
        ('DEMO-DELL', 'Dell Technologies Global', 'enterprise-orders@dell.demo.invalid', '+1-800-456-3355'),
        ('DEMO-APPLE', 'Apple Enterprise Sales', 'b2b-orders@apple.demo.invalid', '+1-800-854-3680'),
        ('DEMO-CISCO', 'Cisco Systems Commercial', 'support@cisco.demo.invalid', '+1-800-553-6387'),
        ('DEMO-HP', 'HP Enterprise Solutions', 'contract-orders@hpe.demo.invalid', '+1-800-752-0900'),
    ]
    supplier_map: dict[str, Supplier] = {}
    for code, name, email, phone in supplier_definitions:
        sup = db.scalar(select(Supplier).where(Supplier.company_id == company.id, Supplier.code == code))
        if not sup:
            sup = Supplier(company_id=company.id, code=code, name=name, email=email, phone=phone, is_active=True)
            db.add(sup)
            db.flush()
            summary.record('Supplier', created=True)
        else:
            summary.record('Supplier', created=False)
        supplier_map[code] = sup

    # 9. Procurement: Purchase Orders and Goods Receipts
    # PO 1: Dell Hardware (Received in full)
    po1 = db.scalar(select(PurchaseOrder).where(PurchaseOrder.company_id == company.id, PurchaseOrder.order_number == 'DEMO-PO-2026-001'))
    po1_lines: dict[str, PurchaseOrderLine] = {}
    if not po1:
        po1 = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier_map['DEMO-DELL'].id,
            order_number='DEMO-PO-2026-001',
            status='received',
            ordered_date=today - timedelta(days=180),
            expected_date=today - timedelta(days=165),
            notes='Annual engineering laptop and datacenter server bulk order.',
        )
        db.add(po1)
        db.flush()
        summary.record('Purchase Order', created=True)

        l1 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po1.id,
            category_id=category_map['LAPTOP'].id,
            description='Dell Latitude 7440 Ultrabook 14-inch Core i7 32GB RAM',
            quantity_ordered=5,
            unit_cost=Decimal('1450.00'),
        )
        l2 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po1.id,
            category_id=category_map['SERVER'].id,
            description='Dell PowerEdge R760 Rack Server 2U Dual Xeon 128GB RAM',
            quantity_ordered=2,
            unit_cost=Decimal('6800.00'),
        )
        db.add_all([l1, l2])
        db.flush()
        po1_lines['laptops'] = l1
        po1_lines['servers'] = l2
        summary.record('Purchase Order Line', created=True)
        summary.record('Purchase Order Line', created=True)
    else:
        summary.record('Purchase Order', created=False)
        lines = db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po1.id)).all()
        for ln in lines:
            if ln.category_id == category_map['LAPTOP'].id:
                po1_lines['laptops'] = ln
            elif ln.category_id == category_map['SERVER'].id:
                po1_lines['servers'] = ln
            summary.record('Purchase Order Line', created=False)

    # GRN 1 for PO 1
    grn1 = db.scalar(select(GoodsReceipt).where(GoodsReceipt.company_id == company.id, GoodsReceipt.receipt_number == 'DEMO-GRN-2026-001'))
    grn1_lines: dict[str, GoodsReceiptLine] = {}
    if not grn1:
        grn1 = GoodsReceipt(
            company_id=company.id,
            purchase_order_id=po1.id,
            receipt_number='DEMO-GRN-2026-001',
            received_date=today - timedelta(days=165),
            delivery_reference='DEL-BOL-994821',
            notes='All items verified against bill of lading in perfect condition.',
        )
        db.add(grn1)
        db.flush()
        summary.record('Goods Receipt', created=True)

        gl1 = GoodsReceiptLine(
            company_id=company.id,
            goods_receipt_id=grn1.id,
            purchase_order_id=po1.id,
            purchase_order_line_id=po1_lines['laptops'].id,
            quantity_received=5,
            quantity_rejected=0,
        )
        gl2 = GoodsReceiptLine(
            company_id=company.id,
            goods_receipt_id=grn1.id,
            purchase_order_id=po1.id,
            purchase_order_line_id=po1_lines['servers'].id,
            quantity_received=2,
            quantity_rejected=0,
        )
        db.add_all([gl1, gl2])
        db.flush()
        grn1_lines['laptops'] = gl1
        grn1_lines['servers'] = gl2
        summary.record('Goods Receipt Line', created=True)
        summary.record('Goods Receipt Line', created=True)
    else:
        summary.record('Goods Receipt', created=False)
        glines = db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == grn1.id)).all()
        for gln in glines:
            if gln.purchase_order_line_id == po1_lines.get('laptops', gln).id:
                grn1_lines['laptops'] = gln
            else:
                grn1_lines['servers'] = gln
            summary.record('Goods Receipt Line', created=False)

    # PO 2: Apple Hardware (Partially received with 1 damaged display rejected)
    po2 = db.scalar(select(PurchaseOrder).where(PurchaseOrder.company_id == company.id, PurchaseOrder.order_number == 'DEMO-PO-2026-002'))
    po2_lines: dict[str, PurchaseOrderLine] = {}
    if not po2:
        po2 = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier_map['DEMO-APPLE'].id,
            order_number='DEMO-PO-2026-002',
            status='partially_received',
            ordered_date=today - timedelta(days=60),
            expected_date=today - timedelta(days=45),
            notes='Design & product executive workstation refresh.',
        )
        db.add(po2)
        db.flush()
        summary.record('Purchase Order', created=True)

        l1 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po2.id,
            category_id=category_map['LAPTOP'].id,
            description='Apple MacBook Pro 16-inch M3 Max 36GB 1TB SSD',
            quantity_ordered=4,
            unit_cost=Decimal('3200.00'),
        )
        l2 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po2.id,
            category_id=category_map['DESKTOP'].id,
            description='Apple Studio Display 27-inch 5K Retina Standard Glass',
            quantity_ordered=3,
            unit_cost=Decimal('1599.00'),
        )
        db.add_all([l1, l2])
        db.flush()
        po2_lines['macbooks'] = l1
        po2_lines['displays'] = l2
        summary.record('Purchase Order Line', created=True)
        summary.record('Purchase Order Line', created=True)
    else:
        summary.record('Purchase Order', created=False)
        for ln in db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po2.id)).all():
            if ln.category_id == category_map['LAPTOP'].id:
                po2_lines['macbooks'] = ln
            else:
                po2_lines['displays'] = ln
            summary.record('Purchase Order Line', created=False)

    # GRN 2 for PO 2
    grn2 = db.scalar(select(GoodsReceipt).where(GoodsReceipt.company_id == company.id, GoodsReceipt.receipt_number == 'DEMO-GRN-2026-002'))
    grn2_lines: dict[str, GoodsReceiptLine] = {}
    if not grn2:
        grn2 = GoodsReceipt(
            company_id=company.id,
            purchase_order_id=po2.id,
            receipt_number='DEMO-GRN-2026-002',
            received_date=today - timedelta(days=45),
            delivery_reference='APL-SHP-55201',
            notes='Partial shipment; 1 display unit rejected due to packaging puncture & hairline screen fissure.',
        )
        db.add(grn2)
        db.flush()
        summary.record('Goods Receipt', created=True)

        gl1 = GoodsReceiptLine(
            company_id=company.id,
            goods_receipt_id=grn2.id,
            purchase_order_id=po2.id,
            purchase_order_line_id=po2_lines['macbooks'].id,
            quantity_received=2,
            quantity_rejected=0,
        )
        gl2 = GoodsReceiptLine(
            company_id=company.id,
            goods_receipt_id=grn2.id,
            purchase_order_id=po2.id,
            purchase_order_line_id=po2_lines['displays'].id,
            quantity_received=2,
            quantity_rejected=1,
            discrepancy_notes='Unit 2 had transit box puncture causing hairline panel crack. RMA #APL-RMA-8819 requested.',
        )
        db.add_all([gl1, gl2])
        db.flush()
        grn2_lines['macbooks'] = gl1
        grn2_lines['displays'] = gl2
        summary.record('Goods Receipt Line', created=True)
        summary.record('Goods Receipt Line', created=True)
    else:
        summary.record('Goods Receipt', created=False)
        for gln in db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == grn2.id)).all():
            if gln.purchase_order_line_id == po2_lines.get('macbooks', gln).id:
                grn2_lines['macbooks'] = gln
            else:
                grn2_lines['displays'] = gln
            summary.record('Goods Receipt Line', created=False)

    # PO 3: Cisco Switches (Overdue delivery -> triggers alert)
    po3 = db.scalar(select(PurchaseOrder).where(PurchaseOrder.company_id == company.id, PurchaseOrder.order_number == 'DEMO-PO-2026-003'))
    if not po3:
        po3 = PurchaseOrder(
            company_id=company.id,
            supplier_id=supplier_map['DEMO-CISCO'].id,
            order_number='DEMO-PO-2026-003',
            status='open',
            ordered_date=today - timedelta(days=25),
            expected_date=today - timedelta(days=3),  # 3 days overdue!
            notes='Datacenter switch expansion and campus Wi-Fi upgrade.',
        )
        db.add(po3)
        db.flush()
        summary.record('Purchase Order', created=True)

        l1 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po3.id,
            category_id=category_map['NETWORK'].id,
            description='Cisco Catalyst 9300 48-Port PoE+ Enterprise Switch',
            quantity_ordered=2,
            unit_cost=Decimal('4500.00'),
        )
        l2 = PurchaseOrderLine(
            company_id=company.id,
            purchase_order_id=po3.id,
            category_id=category_map['NETWORK'].id,
            description='Cisco Catalyst 9120AX Series Wi-Fi 6 Access Point',
            quantity_ordered=4,
            unit_cost=Decimal('850.00'),
        )
        db.add_all([l1, l2])
        db.flush()
        summary.record('Purchase Order Line', created=True)
        summary.record('Purchase Order Line', created=True)
    else:
        summary.record('Purchase Order', created=False)
        for _ in db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po3.id)).all():
            summary.record('Purchase Order Line', created=False)

    # 10. Assets Register Population
    asset_catalog = [
        # Laptops from PO 1
        {
            'serial': 'DEMO-SN-DL74-001',
            'category': 'LAPTOP',
            'model': 'Dell Latitude 7440 Ultrabook 14-inch',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('1450.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': 'Priya Patel',
            'grn_line': grn1_lines.get('laptops'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-DL74-002',
            'category': 'LAPTOP',
            'model': 'Dell Latitude 7440 Ultrabook 14-inch',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('1450.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-F2',
            'dept': 'DEMO-SALES',
            'cost_center': 'DEMO-CC-OPS',
            'custodian': 'Marcus Vance',
            'grn_line': grn1_lines.get('laptops'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-DL74-003',
            'category': 'LAPTOP',
            'model': 'Dell Latitude 7440 Ultrabook 14-inch',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('1450.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': grn1_lines.get('laptops'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-DL74-004',
            'category': 'LAPTOP',
            'model': 'Dell Latitude 7440 Ultrabook 14-inch',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('1450.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': grn1_lines.get('laptops'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-DL74-005',
            'category': 'LAPTOP',
            'model': 'Dell Latitude 7440 Ultrabook 14-inch',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('1450.00'),
            'status': 'in_stock',
            'site': 'DEMO-TECH',
            'location': 'DEMO-TECH-LAB',
            'dept': 'DEMO-ENG',
            'cost_center': 'DEMO-CC-RD',
            'custodian': None,
            'grn_line': grn1_lines.get('laptops'),
            'useful_life': 36,
        },
        # Servers from PO 1
        {
            'serial': 'DEMO-SN-PE76-001',
            'category': 'SERVER',
            'model': 'Dell PowerEdge R760 2U Dual Xeon 128GB',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('6800.00'),
            'status': 'maintenance',  # Undergoing maintenance!
            'site': 'DEMO-DC',
            'location': 'DEMO-DC-RACK1',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': grn1_lines.get('servers'),
            'useful_life': 60,
        },
        {
            'serial': 'DEMO-SN-PE76-002',
            'category': 'SERVER',
            'model': 'Dell PowerEdge R760 2U Dual Xeon 128GB',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=165),
            'cost': Decimal('6800.00'),
            'status': 'in_stock',
            'site': 'DEMO-DC',
            'location': 'DEMO-DC-RACK1',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': grn1_lines.get('servers'),
            'useful_life': 60,
        },
        # Apple Hardware from PO 2
        {
            'serial': 'DEMO-SN-MBP16-001',
            'category': 'LAPTOP',
            'model': 'Apple MacBook Pro 16-inch M3 Max 36GB',
            'mfg': 'Apple',
            'acq_date': today - timedelta(days=45),
            'cost': Decimal('3200.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-ENG',
            'dept': 'DEMO-ENG',
            'cost_center': 'DEMO-CC-RD',
            'custodian': 'Alex Chen',
            'grn_line': grn2_lines.get('macbooks'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-MBP16-002',
            'category': 'LAPTOP',
            'model': 'Apple MacBook Pro 16-inch M3 Max 36GB',
            'mfg': 'Apple',
            'acq_date': today - timedelta(days=45),
            'cost': Decimal('3200.00'),
            'status': 'assigned',
            'site': 'DEMO-TECH',
            'location': 'DEMO-TECH-LAB',
            'dept': 'DEMO-ENG',
            'cost_center': 'DEMO-CC-RD',
            'custodian': 'Elena Rostova',
            'grn_line': grn2_lines.get('macbooks'),
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-ASD-001',
            'category': 'DESKTOP',
            'model': 'Apple Studio Display 27-inch 5K Retina',
            'mfg': 'Apple',
            'acq_date': today - timedelta(days=45),
            'cost': Decimal('1599.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-ENG',
            'dept': 'DEMO-ENG',
            'cost_center': 'DEMO-CC-RD',
            'custodian': 'Alex Chen',
            'grn_line': grn2_lines.get('displays'),
            'useful_life': 48,
        },
        # Workstations & Servers
        {
            'serial': 'DEMO-SN-TP16-001',
            'category': 'LAPTOP',
            'model': 'Lenovo ThinkPad P16 Gen 2 Core i9 64GB',
            'mfg': 'Lenovo',
            'acq_date': today - timedelta(days=240),
            'cost': Decimal('2850.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-ENG',
            'dept': 'DEMO-ENG',
            'cost_center': 'DEMO-CC-RD',
            'custodian': 'Alex Chen',
            'grn_line': None,
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-TP16-002',
            'category': 'LAPTOP',
            'model': 'Lenovo ThinkPad P16 Gen 2 Core i9 64GB',
            'mfg': 'Lenovo',
            'acq_date': today - timedelta(days=240),
            'cost': Decimal('2850.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-HPE8-001',
            'category': 'DESKTOP',
            'model': 'HP EliteOne 870 G9 27-inch All-in-One',
            'mfg': 'HP',
            'acq_date': today - timedelta(days=300),
            'cost': Decimal('1750.00'),
            'status': 'assigned',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-F2',
            'dept': 'DEMO-FIN',
            'cost_center': 'DEMO-CC-FIN',
            'custodian': 'Alex Chen',
            'grn_line': None,
            'useful_life': 48,
        },
        {
            'serial': 'DEMO-SN-HPDL-001',
            'category': 'SERVER',
            'model': 'HPE ProLiant DL380 Gen11 32-Core Xeon 128GB',
            'mfg': 'HPE',
            'acq_date': today - timedelta(days=1020),  # ~34 months ago (useful life 36m -> approaching EOL!)
            'cost': Decimal('7200.00'),
            'status': 'in_stock',
            'site': 'DEMO-DC',
            'location': 'DEMO-DC-RACK2',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 36,
        },
        {
            'serial': 'DEMO-SN-C95-001',
            'category': 'NETWORK',
            'model': 'Cisco Catalyst 9500 24-Port 100G Core Switch',
            'mfg': 'Cisco',
            'acq_date': today - timedelta(days=500),
            'cost': Decimal('12500.00'),
            'status': 'in_stock',
            'site': 'DEMO-DC',
            'location': 'DEMO-DC-RACK1',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 60,
        },
        {
            'serial': 'DEMO-SN-FG100-001',
            'category': 'NETWORK',
            'model': 'Fortinet FortiGate 100F Security Gateway',
            'mfg': 'Fortinet',
            'acq_date': today - timedelta(days=350),
            'cost': Decimal('3400.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 60,
        },
        {
            'serial': 'DEMO-SN-HPPR-001',
            'category': 'PRINTER',
            'model': 'HP LaserJet Enterprise M608dn High-Volume',
            'mfg': 'HP',
            'acq_date': today - timedelta(days=200),
            'cost': Decimal('1200.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-F2',
            'dept': 'DEMO-FIN',
            'cost_center': 'DEMO-CC-FIN',
            'custodian': None,
            'grn_line': None,
            'useful_life': 60,
        },
        {
            'serial': 'DEMO-SN-ZBPR-001',
            'category': 'PRINTER',
            'model': 'Zebra ZT411 Industrial RFID Label Printer',
            'mfg': 'Zebra',
            'acq_date': today - timedelta(days=150),
            'cost': Decimal('1850.00'),
            'status': 'in_stock',
            'site': 'DEMO-TECH',
            'location': 'DEMO-TECH-LAB',
            'dept': 'DEMO-OPS',
            'cost_center': 'DEMO-CC-OPS',
            'custodian': None,
            'grn_line': None,
            'useful_life': 48,
        },
        {
            'serial': 'DEMO-SN-JB75-001',
            'category': 'PERIPHERAL',
            'model': 'Jabra Speak 750 UC Wireless Speakerphone',
            'mfg': 'Jabra',
            'acq_date': today - timedelta(days=120),
            'cost': Decimal('320.00'),
            'status': 'in_stock',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-F2',
            'dept': 'DEMO-SALES',
            'cost_center': 'DEMO-CC-OPS',
            'custodian': None,
            'grn_line': None,
            'useful_life': 24,
        },
        # Fully Depreciated In-Service Asset -> triggers alert
        {
            'serial': 'DEMO-SN-T480-LEG',
            'category': 'LAPTOP',
            'model': 'Lenovo ThinkPad T480 Core i5 16GB RAM',
            'mfg': 'Lenovo',
            'acq_date': today - timedelta(days=780),  # 26 months ago
            'cost': Decimal('1100.00'),
            'status': 'in_stock',  # In service / in stock!
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 24,  # Fully depreciated 2 months ago!
        },
        # Disposed Asset
        {
            'serial': 'DEMO-SN-OPT7-DISP',
            'category': 'DESKTOP',
            'model': 'Dell OptiPlex 7070 Micro Desktop i7 16GB',
            'mfg': 'Dell',
            'acq_date': today - timedelta(days=900),
            'cost': Decimal('850.00'),
            'status': 'disposed',
            'site': 'DEMO-HQ',
            'location': 'DEMO-HQ-DESK',
            'dept': 'DEMO-IT',
            'cost_center': 'DEMO-CC-IT',
            'custodian': None,
            'grn_line': None,
            'useful_life': 36,
        },
    ]

    asset_map: dict[str, Asset] = {}
    for spec in asset_catalog:
        asset = db.scalar(select(Asset).where(Asset.company_id == company.id, Asset.serial_number == spec['serial']))
        cat = category_map[spec['category']]
        site = site_map[spec['site']] if spec.get('site') else None
        loc = location_map[spec['location']] if spec.get('location') else None
        dept = dept_map[spec['dept']] if spec.get('dept') else None
        cc = cost_centre_map[spec['cost_center']] if spec.get('cost_center') else None
        grn_line = spec.get('grn_line')

        if not asset:
            ast_num = next_asset_number(db, company.id, cat.id)
            asset = Asset(
                company_id=company.id,
                category_id=cat.id,
                asset_number=ast_num,
                serial_number=spec['serial'],
                manufacturer=spec['mfg'],
                model=spec['model'],
                acquisition_date=spec['acq_date'],
                acquisition_cost=spec['cost'],
                status=spec['status'],
                site_id=site.id if site else None,
                location_id=loc.id if loc else None,
                responsible_department_id=dept.id if dept else None,
                cost_center_id=cc.id if cc else None,
                custodian_name=spec.get('custodian'),
                goods_receipt_line_id=grn_line.id if grn_line else None,
            )
            db.add(asset)
            db.flush()
            summary.record('Asset', created=True)
        else:
            summary.record('Asset', created=False)
        asset_map[spec['serial']] = asset

    # 11. Asset Assignments, Handovers, Returns, and Transfers
    assignment_specs = [
        {
            'asset_serial': 'DEMO-SN-MBP16-001',
            'recipient_email': 'alex.chen@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=45),
            'status': 'active',
            'dept': 'DEMO-ENG',
            'location': 'DEMO-HQ-ENG',
            'ref': 'DEMO-ASG-001',
            'handover_date': today - timedelta(days=45),
            'handover_condition': 'excellent',
            'included_items': '96W USB-C Power Adapter, MagSafe 3 Cable, Laptop Sleeve',
            'ack': 'Acknowledged device usage and confidentiality agreement.',
        },
        {
            'asset_serial': 'DEMO-SN-MBP16-002',
            'recipient_email': 'elena.rostova@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=40),
            'status': 'active',
            'dept': 'DEMO-ENG',
            'location': 'DEMO-TECH-LAB',
            'ref': 'DEMO-ASG-002',
            'handover_date': today - timedelta(days=40),
            'handover_condition': 'good',
            'included_items': '140W USB-C Power Adapter, Thunderbolt 4 Cable',
            'ack': 'Signed device acceptance protocol.',
        },
        {
            'asset_serial': 'DEMO-SN-DL74-001',
            'recipient_email': 'priya.patel@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=150),
            'status': 'active',
            'dept': 'DEMO-IT',
            'location': 'DEMO-HQ-DESK',
            'ref': 'DEMO-ASG-003',
            'handover_date': today - timedelta(days=150),
            'handover_condition': 'good',
            'ack': 'Standard IT staff deployment.',
        },
        {
            'asset_serial': 'DEMO-SN-DL74-002',
            'recipient_email': 'marcus.vance@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=140),
            'status': 'active',
            'dept': 'DEMO-SALES',
            'location': 'DEMO-HQ-F2',
            'ref': 'DEMO-ASG-004',
            'handover_date': today - timedelta(days=140),
            'handover_condition': 'good',
            'ack': 'Sales field representative laptop kit.',
        },
        {
            'asset_serial': 'DEMO-SN-HPE8-001',
            'recipient_email': 'alex.chen@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=250),
            'status': 'active',
            'dept': 'DEMO-FIN',
            'location': 'DEMO-HQ-F2',
            'ref': 'DEMO-ASG-005',
            'handover_date': today - timedelta(days=250),
            'handover_condition': 'good',
            'ack': 'Corporate finance workstation deployment.',
        },
        # Completed Return Record
        {
            'asset_serial': 'DEMO-SN-DL74-003',
            'recipient_email': 'marcus.vance@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=150),
            'status': 'returned',
            'dept': 'DEMO-SALES',
            'location': 'DEMO-HQ-F2',
            'ref': 'DEMO-ASG-006-RET',
            'handover_date': today - timedelta(days=150),
            'handover_condition': 'good',
            'ended_at': now - timedelta(days=15),
            'return_date': today - timedelta(days=15),
            'return_condition': 'good',
            'return_notes': 'Returned upon reallocation to new sales hire.',
            'next_asset_status': 'in_stock',
        },
        # Transferred Record
        {
            'asset_serial': 'DEMO-SN-TP16-001',
            'recipient_email': 'alex.chen@demo.mindzen.invalid',
            'effective_date': today - timedelta(days=60),
            'status': 'active',
            'dept': 'DEMO-ENG',
            'location': 'DEMO-HQ-ENG',
            'ref': 'DEMO-ASG-007-TXF',
            'handover_date': today - timedelta(days=60),
            'handover_condition': 'good',
            'transfer_reason': 'Transferred to Lead Systems Architect for Project Apollo CAD benchmarking.',
        },
    ]

    for aspec in assignment_specs:
        target_asset = asset_map[aspec['asset_serial']]
        recip_user = custodian_users[aspec['recipient_email']]
        asg = db.scalar(
            select(AssetAssignment).where(
                AssetAssignment.company_id == company.id,
                AssetAssignment.asset_id == target_asset.id,
                AssetAssignment.reference == aspec['ref'],
            )
        )
        if not asg:
            asg = AssetAssignment(
                company_id=company.id,
                asset_id=target_asset.id,
                recipient_id=recip_user.id,
                responsible_department_id=dept_map[aspec['dept']].id,
                location_id=location_map[aspec['location']].id,
                effective_date=aspec['effective_date'],
                status=aspec['status'],
                reference=aspec['ref'],
                handover_date=aspec.get('handover_date'),
                handover_condition=aspec.get('handover_condition'),
                included_items=aspec.get('included_items'),
                acknowledgement=aspec.get('ack'),
                ended_at=aspec.get('ended_at'),
                return_date=aspec.get('return_date'),
                return_condition=aspec.get('return_condition'),
                return_notes=aspec.get('return_notes'),
                next_asset_status=aspec.get('next_asset_status'),
                transfer_reason=aspec.get('transfer_reason'),
            )
            db.add(asg)
            db.flush()
            summary.record('Asset Assignment', created=True)
        else:
            summary.record('Asset Assignment', created=False)

    # 12. Service Contracts (Warranties & AMCs)
    contract_specs = [
        # Healthy Warranty
        {
            'serial': 'DEMO-SN-PE76-001',
            'type': 'warranty',
            'ref': 'DELL-WAR-7601',
            'provider': 'Dell ProSupport Plus Mission Critical 4hr Onsite',
            'supplier': 'DEMO-DELL',
            'start': today - timedelta(days=165),
            'end': today + timedelta(days=565),  # 18+ months remaining
            'desc': '24x7 mission-critical server hardware replacement and memory diagnostics.',
        },
        # Warranty Expiring in 15 days -> Triggers Alert!
        {
            'serial': 'DEMO-SN-DL74-001',
            'type': 'warranty',
            'ref': 'DELL-WAR-7401',
            'provider': 'Dell ProSupport Next Business Day',
            'supplier': 'DEMO-DELL',
            'start': today - timedelta(days=350),
            'end': today + timedelta(days=15),  # Expiring soon!
            'desc': 'Laptop onsite hardware repair and battery coverage.',
        },
        # Warranty Expired 10 days ago -> Triggers Critical Alert!
        {
            'serial': 'DEMO-SN-C95-001',
            'type': 'warranty',
            'ref': 'CSCO-SNTC-9501',
            'provider': 'Cisco Smart Net Total Care',
            'supplier': 'DEMO-CISCO',
            'start': today - timedelta(days=500),
            'end': today - timedelta(days=10),  # Expired!
            'desc': 'Core optical chassis advanced hardware replacement.',
        },
        # AMC Expiring in 25 days -> Triggers Alert!
        {
            'serial': 'DEMO-SN-HPDL-001',
            'type': 'amc',
            'ref': 'HPE-AMC-3801',
            'provider': 'HPE Pointnext Complete Care',
            'supplier': 'DEMO-HP',
            'start': today - timedelta(days=340),
            'end': today + timedelta(days=25),  # Expiring soon!
            'desc': 'Comprehensive enterprise datacenter annual maintenance and firmware patch management.',
        },
        # Active AMC
        {
            'serial': 'DEMO-SN-FG100-001',
            'type': 'amc',
            'ref': 'FTNT-AMC-1001',
            'provider': 'Fortinet FortiCare 24x7 Enterprise Support',
            'supplier': None,
            'start': today - timedelta(days=300),
            'end': today + timedelta(days=65),
            'desc': 'Intrusion prevention signature updates and hardware failover support.',
        },
    ]

    for cspec in contract_specs:
        c_asset = asset_map[cspec['serial']]
        c_supp = supplier_map.get(cspec['supplier']) if cspec.get('supplier') else None
        contract = db.scalar(
            select(AssetServiceContract).where(
                AssetServiceContract.company_id == company.id,
                AssetServiceContract.asset_id == c_asset.id,
                AssetServiceContract.reference_number == cspec['ref'],
            )
        )
        if not contract:
            contract = AssetServiceContract(
                company_id=company.id,
                asset_id=c_asset.id,
                supplier_id=c_supp.id if c_supp else None,
                contract_type=cspec['type'],
                provider_name=cspec['provider'],
                reference_number=cspec['ref'],
                start_date=cspec['start'],
                end_date=cspec['end'],
                coverage_description=cspec['desc'],
                support_contact='support@vendor-service.demo.invalid',
                status='active',
            )
            db.add(contract)
            db.flush()
            summary.record('Service Contract', created=True)
        else:
            summary.record('Service Contract', created=False)

    # 13. Maintenance Requests
    maint_specs = [
        # Urgent Overdue SLA -> Triggers Critical Alert!
        {
            'serial': 'DEMO-SN-PE76-001',
            'title': 'Primary Power Supply PSU1 Failure on Database Server',
            'issue': 'Redundant power supply unit 1 has amber fault light and is offline. Running on secondary PSU only. Immediate replacement required.',
            'priority': 'urgent',
            'status': 'open',
            'reported': today - timedelta(days=4),  # urgent SLA 2d -> overdue by 2 days!
            'assignee': None,
        },
        # High Priority Overdue SLA -> Triggers Warning Alert!
        {
            'serial': 'DEMO-SN-C95-001',
            'title': 'Uplink Port SFP+ CRC Error Rate High',
            'issue': '10G optical transceiver on port 1/1/24 reporting high frame check sequence error rate affecting building uplink.',
            'priority': 'high',
            'status': 'in_progress',
            'reported': today - timedelta(days=8),  # high SLA 5d -> overdue by 3 days!
            'assignee': 'priya.patel@demo.mindzen.invalid',
        },
        # Normal Priority Completed Maintenance
        {
            'serial': 'DEMO-SN-TP16-002',
            'title': 'Cooling Fan Vibration and Thermal Throttling',
            'issue': 'Excessive fan noise under load causing CPU thermal throttling during CAD compilation.',
            'priority': 'normal',
            'status': 'closed',
            'reported': today - timedelta(days=30),
            'completed': today - timedelta(days=15),
            'cost': Decimal('185.00'),
            'work': 'Replaced dual internal thermal fan assembly and reapplied thermal paste.',
            'resolution': 'Verified thermal temps at idle (38C) and peak load (72C). Operational testing passed.',
            'assignee': 'priya.patel@demo.mindzen.invalid',
        },
        # Low Priority Open Maintenance
        {
            'serial': 'DEMO-SN-HPPR-001',
            'title': 'Paper Feed Roller Maintenance Kit Warning',
            'issue': 'Printer control panel shows roller maintenance kit due for replacement.',
            'priority': 'low',
            'status': 'open',
            'reported': today - timedelta(days=3),
            'assignee': None,
        },
    ]

    for mspec in maint_specs:
        m_asset = asset_map[mspec['serial']]
        m_assignee = custodian_users.get(mspec['assignee']) if mspec.get('assignee') else None
        maint = db.scalar(
            select(MaintenanceRequest).where(
                MaintenanceRequest.company_id == company.id,
                MaintenanceRequest.asset_id == m_asset.id,
                MaintenanceRequest.title == mspec['title'],
            )
        )
        if not maint:
            maint = MaintenanceRequest(
                company_id=company.id,
                asset_id=m_asset.id,
                requester_id=primary_actor.id,
                assignee_id=m_assignee.id if m_assignee else None,
                title=mspec['title'],
                issue_description=mspec['issue'],
                priority=mspec['priority'],
                status=mspec['status'],
                reported_date=mspec['reported'],
                completed_date=mspec.get('completed'),
                cost=mspec.get('cost'),
                work_performed=mspec.get('work'),
                resolution_notes=mspec.get('resolution'),
            )
            db.add(maint)
            db.flush()
            summary.record('Maintenance Request', created=True)
        else:
            summary.record('Maintenance Request', created=False)

    # 14. Financial Lifecycle (Straight-Line Depreciation & Disposal)
    for spec in asset_catalog:
        f_asset = asset_map[spec['serial']]
        financial = db.scalar(select(AssetFinancial).where(AssetFinancial.company_id == company.id, AssetFinancial.asset_id == f_asset.id))
        is_fully_deprec = spec['serial'] == 'DEMO-SN-T480-LEG'
        is_disposed = spec['serial'] == 'DEMO-SN-OPT7-DISP'
        useful_life = spec['useful_life']
        cost = spec['cost']
        residual = Decimal('0.00')

        if not financial:
            if is_fully_deprec:
                accum = cost - residual
                book_val = residual
                fin_status = 'fully_depreciated'
            elif is_disposed:
                accum = Decimal('650.00')
                book_val = cost - accum  # 200.00
                fin_status = 'disposed'
            else:
                accum = Decimal('0.00')
                book_val = cost
                fin_status = 'active'

            financial = AssetFinancial(
                company_id=company.id,
                asset_id=f_asset.id,
                capitalised_cost=cost,
                currency='USD',
                depreciation_method='straight_line',
                useful_life_months=useful_life,
                residual_value=residual,
                depreciation_start_date=spec['acq_date'],
                accumulated_depreciation=accum,
                current_book_value=book_val,
                financial_status=fin_status,
            )
            db.add(financial)
            db.flush()
            summary.record('Financial Profile', created=True)
        else:
            summary.record('Financial Profile', created=False)

    # Post sample historical monthly depreciation entries
    # Post entries for active server and laptop
    deprec_sample_assets = ['DEMO-SN-PE76-002', 'DEMO-SN-MBP16-001']
    sample_periods = [
        ('2026-01', date(2026, 1, 1), date(2026, 1, 31)),
        ('2026-02', date(2026, 2, 1), date(2026, 2, 28)),
        ('2026-03', date(2026, 3, 1), date(2026, 3, 31)),
    ]
    for sn in deprec_sample_assets:
        d_asset = asset_map[sn]
        d_fin = db.scalar(select(AssetFinancial).where(AssetFinancial.company_id == company.id, AssetFinancial.asset_id == d_asset.id))
        monthly_amt = calculate_monthly_depreciation(d_fin.capitalised_cost, d_fin.residual_value, d_fin.useful_life_months)
        running_accum = Decimal('0.00')

        for period_str, p_start, p_end in sample_periods:
            entry = db.scalar(
                select(AssetDepreciationEntry).where(
                    AssetDepreciationEntry.company_id == company.id,
                    AssetDepreciationEntry.asset_id == d_asset.id,
                    AssetDepreciationEntry.period == period_str,
                )
            )
            running_accum += monthly_amt
            book_after = d_fin.capitalised_cost - running_accum
            if not entry:
                entry = AssetDepreciationEntry(
                    company_id=company.id,
                    asset_id=d_asset.id,
                    period=period_str,
                    period_start_date=p_start,
                    period_end_date=p_end,
                    depreciation_amount=monthly_amt,
                    accumulated_depreciation_after=running_accum,
                    book_value_after=book_after,
                    method='straight_line',
                    posted_by_id=primary_actor.id,
                    notes='Scheduled monthly straight-line batch run.',
                )
                db.add(entry)
                db.flush()
                d_fin.accumulated_depreciation = running_accum
                d_fin.current_book_value = book_after
                summary.record('Depreciation Entry', created=True)
            else:
                summary.record('Depreciation Entry', created=False)

    # Disposed Asset Record
    disp_asset = asset_map['DEMO-SN-OPT7-DISP']
    disposal = db.scalar(select(AssetDisposal).where(AssetDisposal.company_id == company.id, AssetDisposal.asset_id == disp_asset.id))
    if not disposal:
        disposal = AssetDisposal(
            company_id=company.id,
            asset_id=disp_asset.id,
            disposal_date=today - timedelta(days=30),
            disposal_reason='obsolete',
            disposal_method='direct_sale',
            sale_proceeds=Decimal('250.00'),
            net_book_value_at_disposal=Decimal('200.00'),
            gain_loss=Decimal('50.00'),  # 250 - 200 = 50.00 gain!
            notes='Sold to certified regional electronics refurbisher. All storage sanitized per NIST 800-88.',
            disposed_by_id=primary_actor.id,
        )
        db.add(disposal)
        db.flush()
        summary.record('Asset Disposal', created=True)
    else:
        summary.record('Asset Disposal', created=False)

    # 15. Physical Asset Verification Campaign & Discrepancies
    camp = db.scalar(
        select(VerificationCampaign).where(
            VerificationCampaign.company_id == company.id,
            VerificationCampaign.campaign_reference == 'DEMO-CAMP-2026-Q1',
        )
    )
    if not camp:
        camp = VerificationCampaign(
            company_id=company.id,
            campaign_reference='DEMO-CAMP-2026-Q1',
            name='Q1 2026 Physical IT Asset Verification',
            description='Comprehensive verification of datacenter racks and headquarters engineering inventory.',
            status='in_progress',
            start_date=today - timedelta(days=18),
            end_date=today + timedelta(days=3),  # Ending in 3 days -> triggers alert!
            created_by_id=primary_actor.id,
            started_at=now - timedelta(days=18),
        )
        db.add(camp)
        db.flush()
        summary.record('Verification Campaign', created=True)
    else:
        summary.record('Verification Campaign', created=False)

    # Populate expected assets snapshot for campaign
    expected_assets_map: dict[UUID, VerificationExpectedAsset] = {}
    for sn, ast in asset_map.items():
        if ast.status == 'disposed':
            continue
        exp = db.scalar(
            select(VerificationExpectedAsset).where(
                VerificationExpectedAsset.campaign_id == camp.id,
                VerificationExpectedAsset.asset_id == ast.id,
            )
        )
        if not exp:
            exp = VerificationExpectedAsset(
                company_id=company.id,
                campaign_id=camp.id,
                asset_id=ast.id,
                expected_site_id=ast.site_id,
                expected_location_id=ast.location_id,
                expected_department_id=ast.responsible_department_id,
                expected_custodian_name=ast.custodian_name,
                expected_condition='good',
                expected_status=ast.status,
            )
            db.add(exp)
            db.flush()
            summary.record('Expected Asset', created=True)
        else:
            summary.record('Expected Asset', created=False)
        expected_assets_map[ast.id] = exp

    # Observations & Discrepancies
    # 1. Matched observation (MacBook Pro)
    mbp1_ast = asset_map['DEMO-SN-MBP16-001']
    mbp1_exp = expected_assets_map[mbp1_ast.id]
    obs1 = db.scalar(select(VerificationObservation).where(VerificationObservation.campaign_id == camp.id, VerificationObservation.expected_asset_id == mbp1_exp.id))
    if not obs1:
        obs1 = VerificationObservation(
            company_id=company.id,
            campaign_id=camp.id,
            expected_asset_id=mbp1_exp.id,
            asset_id=mbp1_ast.id,
            is_found=True,
            actual_site_id=mbp1_ast.site_id,
            actual_location_id=mbp1_ast.location_id,
            actual_department_id=mbp1_ast.responsible_department_id,
            observed_condition='good',
            verification_date=today - timedelta(days=10),
            verified_by_id=primary_actor.id,
            remarks='Verified present with custodian Alex Chen. Asset tag intact.',
        )
        db.add(obs1)
        db.flush()
        summary.record('Verification Observation', created=True)
    else:
        summary.record('Verification Observation', created=False)

    # 2. Location mismatch discrepancy
    srv_ast = asset_map['DEMO-SN-PE76-002']
    srv_exp = expected_assets_map[srv_ast.id]
    obs2 = db.scalar(select(VerificationObservation).where(VerificationObservation.campaign_id == camp.id, VerificationObservation.expected_asset_id == srv_exp.id))
    if not obs2:
        obs2 = VerificationObservation(
            company_id=company.id,
            campaign_id=camp.id,
            expected_asset_id=srv_exp.id,
            asset_id=srv_ast.id,
            is_found=True,
            actual_site_id=site_map['DEMO-HQ'].id,
            actual_location_id=location_map['DEMO-HQ-DESK'].id,  # Moved from DC to Desk!
            actual_department_id=dept_map['DEMO-IT'].id,
            observed_condition='good',
            verification_date=today - timedelta(days=12),
            verified_by_id=primary_actor.id,
            remarks='Found at HQ Service Desk for pre-deployment burn-in.',
        )
        db.add(obs2)
        db.flush()
        summary.record('Verification Observation', created=True)

        disc_loc = VerificationDiscrepancy(
            company_id=company.id,
            campaign_id=camp.id,
            observation_id=obs2.id,
            expected_asset_id=srv_exp.id,
            asset_id=srv_ast.id,
            discrepancy_type='location_mismatch',
            status='resolved',
            resolution_action='update_master',
            resolution_notes='Confirmed temporary staging location at HQ Service Desk.',
            resolved_by_id=primary_actor.id,
            resolved_at=now - timedelta(days=5),
        )
        db.add(disc_loc)
        db.flush()
        summary.record('Verification Discrepancy', created=True)
    else:
        summary.record('Verification Observation', created=False)

    # 3. Missing asset discrepancy (Open > 14 days -> triggers alert!)
    spk_ast = asset_map['DEMO-SN-JB75-001']
    spk_exp = expected_assets_map[spk_ast.id]
    obs3 = db.scalar(select(VerificationObservation).where(VerificationObservation.campaign_id == camp.id, VerificationObservation.expected_asset_id == spk_exp.id))
    if not obs3:
        obs3 = VerificationObservation(
            company_id=company.id,
            campaign_id=camp.id,
            expected_asset_id=spk_exp.id,
            asset_id=spk_ast.id,
            is_found=False,
            observed_condition='unknown',
            verification_date=today - timedelta(days=16),
            verified_by_id=primary_actor.id,
            remarks='Conference room speakerphone not located at designated cabinet.',
        )
        db.add(obs3)
        db.flush()
        summary.record('Verification Observation', created=True)

        disc_missing = VerificationDiscrepancy(
            company_id=company.id,
            campaign_id=camp.id,
            observation_id=obs3.id,
            expected_asset_id=spk_exp.id,
            asset_id=spk_ast.id,
            discrepancy_type='missing',
            status='open',
            created_at=now - timedelta(days=16),
            notes='Unresolved for 16 days. Facilities inquiry initiated.',
        )
        db.add(disc_missing)
        db.flush()
        summary.record('Verification Discrepancy', created=True)
    else:
        summary.record('Verification Observation', created=False)

    if options.dry_run:
        summary.record('Alert Engine Sync Evaluated (Preview)', created=True)
        summary.record('Scheduled Job Execution (Preview)', created=True)
        db.rollback()
        return summary

    # 16. Authoritative Alert Sync & Notification Processing
    # Flush database state before alert sync
    db.flush()
    sync_res = sync_company_alerts(db, company.id)
    summary.record('Alert Engine Sync Evaluated', created=True)

    # Acknowledge 1 alert (urgent maintenance)
    urgent_alert = db.scalar(
        select(AssetAlert).where(
            AssetAlert.company_id == company.id,
            AssetAlert.alert_type == 'maintenance_overdue',
            AssetAlert.severity == 'critical',
            AssetAlert.status == 'open',
        )
    )
    if urgent_alert:
        urgent_alert.status = 'acknowledged'
        urgent_alert.acknowledged_at = now - timedelta(hours=2)
        urgent_alert.acknowledged_by_id = primary_actor.id
        summary.record('Alert Acknowledged', created=True)

    # Assign 1 alert to Priya Patel
    warn_alert = db.scalar(
        select(AssetAlert).where(
            AssetAlert.company_id == company.id,
            AssetAlert.alert_type == 'maintenance_overdue',
            AssetAlert.severity == 'warning',
            AssetAlert.status == 'open',
        )
    )
    if warn_alert:
        warn_alert.responsible_user_id = custodian_users['priya.patel@demo.mindzen.invalid'].id
        summary.record('Alert Assigned', created=True)

    # Trigger notifications for critical alerts
    NotificationService.process_alert_notifications(db, company.id)
    summary.record('Critical Notifications Processed', created=True)

    # 17. Scheduled Job Execution History
    existing_job = db.scalar(
        select(ScheduledJobExecution).where(
            ScheduledJobExecution.job_name == 'alert_lifecycle_sync',
            ScheduledJobExecution.status == 'completed',
        )
    )
    if not existing_job:
        job = ScheduledJobExecution(
            job_name='alert_lifecycle_sync',
            status='completed',
            started_at=now - timedelta(minutes=15),
            last_heartbeat_at=now - timedelta(minutes=14),
            completed_at=now - timedelta(minutes=14),
            duration_ms=1150,
            total_companies_processed=1,
            alerts_created=sync_res.created_count,
            alerts_updated=sync_res.updated_count,
            alerts_auto_resolved=sync_res.auto_resolved_count,
            node_id=socket.gethostname(),
        )
        db.add(job)
        db.flush()
        summary.record('Scheduled Job Execution', created=True)
    else:
        summary.record('Scheduled Job Execution', created=False)

    # 18. Audit Events
    record_security_event(
        db,
        action='demo.seed_data_applied',
        entity_type='Company',
        entity_id=str(company.id),
        actor_id=primary_actor.id,
        company_id=company.id,
        changes={'company_code': company.code, 'total_created': summary.total_created},
    )

    db.commit()
    return summary


def _print_summary_table(summary: SeedingSummary) -> None:
    """Renders formatted console summary of seeding operation."""
    mode_str = "DRY-RUN (No database modifications committed)" if summary.dry_run else "LIVE EXECUTION (Committed)"
    print("\n" + "=" * 70)
    print(f"MindZen ALCM / ITAM — Sample Demonstration Data Seeder")
    print(f"Status: {mode_str}")
    print(f"Target Company: {summary.company_code} ({summary.company_name})")
    print(f"Company ID:     {summary.company_id}")
    print("=" * 70)
    print(f"{'Entity Type':<35} | {'Created':<10} | {'Existing':<10} | {'Total':<10}")
    print("-" * 70)

    for name, cnt in sorted(summary.counts.items()):
        print(f"{name:<35} | {cnt.created:<10} | {cnt.already_present:<10} | {cnt.total:<10}")

    print("-" * 70)
    print(f"{'TOTALS':<35} | {summary.total_created:<10} | {summary.total_already_present:<10} | {summary.total_created + summary.total_already_present:<10}")
    print("=" * 70)

    if not summary.dry_run:
        print("\nDemonstration Dataset Highlights:")
        print("  • Asset Register: Laptops, Desktops, Servers, Network, Printers, Peripherals.")
        print("  • Assignments: Active custody, completed return, and transferred assignment.")
        print("  • Procurement: Multi-line orders, goods receipts, partial deliveries, rejected RMA item.")
        print("  • Finance: Straight-line depreciation entries posted, fully depreciated asset, disposal gain.")
        print("  • Verification: Q1 audit campaign, observations, missing & location mismatch discrepancies.")
        print("  • Action Centre: Live alerts for expired warranty, SLA overdue maintenance, ending campaign.")
        print("  • In-App Notifications: Critical alerts delivered with unread bell counter.")
        print("  • Executive Dashboard: Live KPI cards, status charts, and recent activity timeline.")
        print("\nAccess the web application at your deployed URL to explore the populated data.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Populate PostgreSQL database with realistic sample data for MindZen ALCM/ITAM demonstrations.",
    )
    parser.add_argument('--company-code', help='Target company code (e.g. DEMO-CORP)')
    parser.add_argument('--company-id', type=UUID, help='Target company UUID')
    parser.add_argument('--create-company', action='store_true', help='Create the company if it does not already exist')
    parser.add_argument('--dry-run', action='store_true', help='Preview planned changes without writing to database')
    parser.add_argument('--yes', '-y', action='store_true', help='Execute without interactive confirmation prompt')

    args = parser.parse_args()

    options = SeederOptions(
        company_code=args.company_code,
        company_id=args.company_id,
        create_company=args.create_company,
        dry_run=args.dry_run,
        interactive=sys.stdin.isatty(),
        auto_confirm=args.yes,
    )

    db_url_masked = _mask_url(settings.database_url)
    print(f"Connecting to database: {db_url_masked}")

    with SessionLocal() as db:
        try:
            # 1. Resolve intended target company for confirmation display
            target_company, is_new = _resolve_target_company(db, options)
            db.rollback()  # Reset any pending queries

            print(f"\nTarget Database: {db_url_masked}")
            print(f"Target Company:  {target_company.code} - {target_company.name} ({'New' if is_new else 'Existing'})")
            if options.dry_run:
                print("Mode:            DRY-RUN (Simulating operation without committing changes)")
            else:
                print("Mode:            INSERTION (Will safely insert idempotent demonstration records)")

            # 2. Confirmation prompt (unless --yes or --dry-run)
            if not options.dry_run and not options.auto_confirm:
                if options.interactive:
                    confirm = input("\nProceed with seeding demonstration records? [y/N]: ").strip().lower()
                    if confirm not in ('y', 'yes'):
                        print("Operation cancelled. No changes were made.")
                        sys.exit(0)
                else:
                    print("Error: Running in non-interactive environment without --yes / -y flag. Aborting.")
                    sys.exit(1)

            # 3. Execute Seeding
            summary = seed_demo_data(db, options)
            _print_summary_table(summary)

        except Exception as exc:
            db.rollback()
            print(f"\nSeeder encountered an error: {exc}", file=sys.stderr)
            logger.exception("Seeding failed")
            sys.exit(1)


if __name__ == '__main__':
    main()

