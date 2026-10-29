from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
    Column,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Uuid(as_uuid=True), ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Uuid(as_uuid=True), ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
)


class HealthCheck(Base):
    __tablename__ = 'health_checks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='ok')
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Department(Base):
    __tablename__ = 'departments'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_departments_company_id_id'),
        UniqueConstraint('company_id', 'code', name='uq_departments_company_code'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Site(Base):
    __tablename__ = 'sites'

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_sites_company_id_id'),
        UniqueConstraint('company_id', 'code', name='uq_sites_company_code'),
    )


class Location(Base):
    __tablename__ = 'locations'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_locations_company_id_id'),
        UniqueConstraint('company_id', 'site_id', 'code', name='uq_locations_site_code'),
        ForeignKeyConstraint(['company_id', 'site_id'], ['sites.company_id', 'sites.id'], ondelete='RESTRICT'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    site_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CostCenter(Base):
    __tablename__ = 'cost_centers'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_cost_centers_company_id_id'),
        UniqueConstraint('company_id', 'code', name='uq_cost_centers_company_code'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssetCategory(Base):
    __tablename__ = 'asset_categories'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_categories_company_id_id'),
        UniqueConstraint('company_id', 'code', name='uq_asset_categories_company_code'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssetNumberRule(Base):
    __tablename__ = 'asset_number_rules'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_number_rules_company_id_id'),
        Index(
            'uq_asset_number_rules_company_default',
            'company_id',
            unique=True,
            postgresql_where=text('category_id IS NULL'),
            sqlite_where=text('category_id IS NULL'),
        ),
        Index(
            'uq_asset_number_rules_company_category',
            'company_id',
            'category_id',
            unique=True,
            postgresql_where=text('category_id IS NOT NULL'),
            sqlite_where=text('category_id IS NOT NULL'),
        ),
        ForeignKeyConstraint(['company_id', 'category_id'], ['asset_categories.company_id', 'asset_categories.id'], ondelete='RESTRICT'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    separator: Mapped[str] = mapped_column(String(3), nullable=False, default='-')
    padding: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Asset(Base):
    __tablename__ = 'assets'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_assets_company_id_id'),
        UniqueConstraint('company_id', 'asset_number', name='uq_assets_company_asset_number'),
        UniqueConstraint('company_id', 'id', 'category_id', name='uq_assets_company_id_category'),
        ForeignKeyConstraint(['company_id', 'category_id'], ['asset_categories.company_id', 'asset_categories.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'site_id'], ['sites.company_id', 'sites.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['locations.company_id', 'locations.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'responsible_department_id'], ['departments.company_id', 'departments.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'cost_center_id'], ['cost_centers.company_id', 'cost_centers.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(
            ['company_id', 'goods_receipt_line_id'],
            ['goods_receipt_lines.company_id', 'goods_receipt_lines.id'],
            ondelete='RESTRICT',
            name='fk_assets_company_goods_receipt_line',
        ),
        Index('ix_assets_company_serial', 'company_id', 'serial_number'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    asset_number: Mapped[str] = mapped_column(String(80), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    acquisition_date: Mapped[date | None] = mapped_column(Date)
    acquisition_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='in_stock')
    site_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    responsible_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    cost_center_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    custodian_name: Mapped[str | None] = mapped_column(String(160))
    vendor_reference: Mapped[str | None] = mapped_column(String(160))
    invoice_reference: Mapped[str | None] = mapped_column(String(160))
    goods_receipt_line_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    warranty_start: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssetDepartmentUsage(Base):
    __tablename__ = 'asset_department_usages'
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'department_id'], ['departments.company_id', 'departments.id'], ondelete='RESTRICT'),
        Index(
            'uq_asset_department_usage_active',
            'asset_id',
            'department_id',
            unique=True,
            postgresql_where=text('ended_at IS NULL'),
            sqlite_where=text('ended_at IS NULL'),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    department_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    purpose: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssetHistory(Base):
    __tablename__ = 'asset_history'
    __table_args__ = (ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(80))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AssetAssignment(Base):
    __tablename__ = 'asset_assignments'
    __table_args__ = (
        CheckConstraint("status IN ('active', 'returned', 'transferred')", name='ck_asset_assignments_status'),
        CheckConstraint(
            "(status = 'active' AND ended_at IS NULL) OR (status != 'active' AND ended_at IS NOT NULL)",
            name='ck_asset_assignments_end_state',
        ),
        CheckConstraint(
            "next_asset_status IS NULL OR next_asset_status IN ('in_stock', 'maintenance')",
            name='ck_asset_assignments_next_asset_status',
        ),
        ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(
            ['company_id', 'responsible_department_id'],
            ['departments.company_id', 'departments.id'],
            ondelete='RESTRICT',
        ),
        ForeignKeyConstraint(['company_id', 'location_id'], ['locations.company_id', 'locations.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(
            ['company_id', 'recipient_id'],
            ['company_memberships.company_id', 'company_memberships.user_id'],
            ondelete='RESTRICT',
        ),
        Index(
            'uq_asset_assignments_active',
            'asset_id',
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    recipient_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    responsible_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    notes: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(160))
    handover_date: Mapped[date | None] = mapped_column(Date)
    handover_condition: Mapped[str | None] = mapped_column(String(80))
    included_items: Mapped[str | None] = mapped_column(Text)
    acknowledgement: Mapped[str | None] = mapped_column(Text)
    handover_notes: Mapped[str | None] = mapped_column(Text)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    return_date: Mapped[date | None] = mapped_column(Date)
    return_condition: Mapped[str | None] = mapped_column(String(80))
    return_notes: Mapped[str | None] = mapped_column(Text)
    issue_details: Mapped[str | None] = mapped_column(Text)
    next_asset_status: Mapped[str | None] = mapped_column(String(16))
    transfer_reason: Mapped[str | None] = mapped_column(Text)
    previous_assignment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    recipient: Mapped['User'] = relationship()

    @property
    def recipient_email(self) -> str:
        return self.recipient.email


class Supplier(Base):
    __tablename__ = 'suppliers'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_suppliers_company_id_id'),
        UniqueConstraint('company_id', 'code', name='uq_suppliers_company_code'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_purchase_orders_company_id_id'),
        UniqueConstraint('company_id', 'order_number', name='uq_purchase_orders_company_number'),
        CheckConstraint(
            "status IN ('open', 'partially_received', 'received')",
            name='ck_purchase_orders_status',
        ),
        ForeignKeyConstraint(['company_id', 'supplier_id'], ['suppliers.company_id', 'suppliers.id'], ondelete='RESTRICT'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='open')
    ordered_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PurchaseOrderLine(Base):
    __tablename__ = 'purchase_order_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'purchase_order_id', 'id', name='uq_purchase_order_lines_company_order_id'),
        CheckConstraint('quantity_ordered > 0', name='ck_purchase_order_lines_quantity'),
        CheckConstraint('unit_cost >= 0', name='ck_purchase_order_lines_unit_cost'),
        ForeignKeyConstraint(
            ['company_id', 'purchase_order_id'],
            ['purchase_orders.company_id', 'purchase_orders.id'],
            ondelete='RESTRICT',
        ),
        ForeignKeyConstraint(
            ['company_id', 'category_id'],
            ['asset_categories.company_id', 'asset_categories.id'],
            ondelete='RESTRICT',
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    purchase_order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)


class GoodsReceipt(Base):
    __tablename__ = 'goods_receipts'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_goods_receipts_company_id_id'),
        UniqueConstraint(
            'company_id', 'id', 'purchase_order_id',
            name='uq_goods_receipts_company_id_order',
        ),
        UniqueConstraint('company_id', 'receipt_number', name='uq_goods_receipts_company_number'),
        ForeignKeyConstraint(
            ['company_id', 'purchase_order_id'],
            ['purchase_orders.company_id', 'purchase_orders.id'],
            ondelete='RESTRICT',
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    purchase_order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    receipt_number: Mapped[str] = mapped_column(String(64), nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_reference: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoodsReceiptLine(Base):
    __tablename__ = 'goods_receipt_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_goods_receipt_lines_company_id_id'),
        UniqueConstraint(
            'company_id', 'goods_receipt_id', 'purchase_order_line_id',
            name='uq_goods_receipt_lines_receipt_order_line',
        ),
        CheckConstraint('quantity_received > 0', name='ck_goods_receipt_lines_received'),
        CheckConstraint(
            'quantity_rejected >= 0 AND quantity_rejected <= quantity_received',
            name='ck_goods_receipt_lines_rejected',
        ),
        ForeignKeyConstraint(
            ['company_id', 'goods_receipt_id', 'purchase_order_id'],
            ['goods_receipts.company_id', 'goods_receipts.id', 'goods_receipts.purchase_order_id'],
            ondelete='RESTRICT',
        ),
        ForeignKeyConstraint(
            ['company_id', 'purchase_order_id', 'purchase_order_line_id'],
            ['purchase_order_lines.company_id', 'purchase_order_lines.purchase_order_id', 'purchase_order_lines.id'],
            ondelete='RESTRICT',
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    goods_receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    purchase_order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    purchase_order_line_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_notes: Mapped[str | None] = mapped_column(Text)


class AssetServiceContract(Base):
    __tablename__ = 'asset_service_contracts'
    __table_args__ = (
        CheckConstraint("contract_type IN ('warranty', 'amc')", name='ck_asset_service_contracts_type'),
        CheckConstraint("status IN ('active', 'cancelled')", name='ck_asset_service_contracts_status'),
        CheckConstraint('end_date >= start_date', name='ck_asset_service_contracts_date_range'),
        ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'supplier_id'], ['suppliers.company_id', 'suppliers.id'], ondelete='RESTRICT'),
        UniqueConstraint('company_id', 'id', name='uq_asset_service_contracts_company_id'),
        UniqueConstraint(
            'company_id', 'asset_id', 'reference_number',
            name='uq_asset_service_contracts_asset_reference',
        ),
        Index('ix_asset_service_contracts_company_asset', 'company_id', 'asset_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    contract_type: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(160))
    reference_number: Mapped[str | None] = mapped_column(String(160))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_description: Mapped[str | None] = mapped_column(Text)
    support_contact: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MaintenanceRequest(Base):
    __tablename__ = 'maintenance_requests'
    __table_args__ = (
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name='ck_maintenance_requests_priority'),
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name='ck_maintenance_requests_status'),
        CheckConstraint('cost IS NULL OR cost >= 0', name='ck_maintenance_requests_cost'),
        CheckConstraint(
            "(status NOT IN ('resolved', 'closed')) OR (completed_date IS NOT NULL)",
            name='ck_maintenance_requests_completed_date',
        ),
        ForeignKeyConstraint(['company_id', 'asset_id'], ['assets.company_id', 'assets.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(
            ['company_id', 'assignee_id'],
            ['company_memberships.company_id', 'company_memberships.user_id'],
            ondelete='RESTRICT',
        ),
        UniqueConstraint('company_id', 'id', name='uq_maintenance_requests_company_id'),
        Index('ix_maintenance_requests_company_status', 'company_id', 'status'),
        Index('ix_maintenance_requests_company_asset', 'company_id', 'asset_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default='normal')
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='open')
    reported_date: Mapped[date] = mapped_column(Date, nullable=False)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    work_performed: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    completed_date: Mapped[date | None] = mapped_column(Date)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (Index('uq_users_email_lower', text('lower(email)'), unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (
        UniqueConstraint('scope', 'code', name='uq_roles_scope_code'),
        CheckConstraint("scope IN ('system', 'company')", name='ck_roles_scope'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)


class Permission(Base):
    __tablename__ = 'permissions'

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)


class CompanyMembership(Base):
    __tablename__ = 'company_memberships'
    __table_args__ = (
        UniqueConstraint('company_id', 'user_id', name='uq_company_memberships_company_user'),
        CheckConstraint("status IN ('pending', 'active', 'revoked')", name='ck_company_memberships_status'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    assigned_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SystemRoleAssignment(Base):
    __tablename__ = 'system_role_assignments'
    __table_args__ = (UniqueConstraint('user_id', 'role_id', name='uq_system_role_assignments_user_role'),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('roles.id', ondelete='RESTRICT'), nullable=False)
    assigned_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuthSession(Base):
    __tablename__ = 'auth_sessions'

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class UserInvitation(Base):
    __tablename__ = 'user_invitations'

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('company_memberships.id', ondelete='CASCADE'), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LoginThrottle(Base):
    __tablename__ = 'login_throttles'

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = 'audit_events'

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(512))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100), index=True)
    changes: Mapped[dict | None] = mapped_column(JSON)


class LoginFailure(Base):
    __tablename__ = 'login_failures'

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class VerificationCampaign(Base):
    __tablename__ = 'verification_campaigns'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_verification_campaigns_company_id_id'),
        UniqueConstraint('company_id', 'campaign_reference', name='uq_verification_campaigns_reference'),
        CheckConstraint('end_date >= start_date', name='ck_verification_campaigns_date_range'),
        CheckConstraint(
            "status IN ('draft', 'in_progress', 'under_review', 'completed', 'cancelled')",
            name='ck_verification_campaigns_status',
        ),
        ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='RESTRICT'),
        Index('ix_verification_campaigns_company_status', 'company_id', 'status'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    campaign_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='draft')
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    scope_category_ids: Mapped[list | None] = mapped_column(JSON)
    scope_location_ids: Mapped[list | None] = mapped_column(JSON)
    created_by_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class VerificationExpectedAsset(Base):
    __tablename__ = 'verification_expected_assets'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_verification_expected_assets_company_id_id'),
        UniqueConstraint('campaign_id', 'asset_id', name='uq_verification_expected_assets_campaign_asset'),
        ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
        ),
        Index('ix_verification_expected_assets_company_campaign', 'company_id', 'campaign_id'),
        Index('ix_verification_expected_assets_company_asset', 'company_id', 'asset_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    expected_site_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expected_location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expected_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expected_custodian_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expected_custodian_name: Mapped[str | None] = mapped_column(String(160))
    expected_condition: Mapped[str | None] = mapped_column(String(32))
    expected_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VerificationObservation(Base):
    __tablename__ = 'verification_observations'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_verification_observations_company_id_id'),
        UniqueConstraint('campaign_id', 'expected_asset_id', name='uq_verification_observations_campaign_expected'),
        ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        Index('ix_verification_observations_company_campaign', 'company_id', 'campaign_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    expected_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    is_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actual_site_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actual_location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actual_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actual_custodian_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    observed_condition: Mapped[str] = mapped_column(String(32), nullable=False, default='good')
    verification_date: Mapped[date] = mapped_column(Date, nullable=False)
    verified_by_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    reference_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class VerificationDiscrepancy(Base):
    __tablename__ = 'verification_discrepancies'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_verification_discrepancies_company_id_id'),
        CheckConstraint(
            "discrepancy_type IN ('missing', 'location_mismatch', 'custodian_mismatch', 'condition_mismatch', 'unregistered_asset')",
            name='ck_verification_discrepancies_type',
        ),
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name='ck_verification_discrepancies_status',
        ),
        ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        Index('ix_verification_discrepancies_company_campaign', 'company_id', 'campaign_id'),
        Index('ix_verification_discrepancies_type_status', 'company_id', 'discrepancy_type', 'status'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    observation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expected_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    discrepancy_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='open')
    expected_data: Mapped[dict | None] = mapped_column(JSON)
    observed_data: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    resolution_action: Mapped[str | None] = mapped_column(String(32))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class VerificationUnregisteredAsset(Base):
    __tablename__ = 'verification_unregistered_assets'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_verification_unregistered_assets_company_id_id'),
        CheckConstraint(
            "status IN ('pending', 'registered', 'rejected')",
            name='ck_verification_unregistered_assets_status',
        ),
        ForeignKeyConstraint(
            ['company_id', 'campaign_id'],
            ['verification_campaigns.company_id', 'verification_campaigns.id'],
            ondelete='CASCADE',
        ),
        ForeignKeyConstraint(
            ['company_id', 'category_id'],
            ['asset_categories.company_id', 'asset_categories.id'],
            ondelete='RESTRICT',
        ),
        Index('ix_verification_unregistered_assets_campaign', 'company_id', 'campaign_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    observation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    discrepancy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    serial_number: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    custodian_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    observed_condition: Mapped[str | None] = mapped_column(String(32), default='good')
    remarks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending')
    registered_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssetFinancial(Base):
    __tablename__ = 'asset_financials'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_financials_company_id_id'),
        UniqueConstraint('company_id', 'asset_id', name='uq_asset_financials_company_asset'),
        CheckConstraint('capitalised_cost >= 0', name='ck_asset_financials_capitalised_cost'),
        CheckConstraint('residual_value >= 0', name='ck_asset_financials_residual_value'),
        CheckConstraint('residual_value <= capitalised_cost', name='ck_asset_financials_residual_le_cost'),
        CheckConstraint('useful_life_months > 0', name='ck_asset_financials_useful_life_months'),
        CheckConstraint('accumulated_depreciation >= 0', name='ck_asset_financials_accum_deprec_gte_zero'),
        CheckConstraint('accumulated_depreciation <= capitalised_cost - residual_value', name='ck_asset_financials_accum_deprec_le_basis'),
        CheckConstraint('current_book_value >= residual_value', name='ck_asset_financials_book_value_gte_residual'),
        CheckConstraint(
            "financial_status IN ('draft', 'active', 'fully_depreciated', 'disposed')",
            name='ck_asset_financials_status',
        ),
        CheckConstraint(
            "depreciation_method IN ('straight_line')",
            name='ck_asset_financials_method',
        ),
        ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
        ),
        Index('ix_asset_financials_company_status', 'company_id', 'financial_status'),
        Index('ix_asset_financials_company_asset', 'company_id', 'asset_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    capitalised_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default='INR', server_default='INR')
    depreciation_method: Mapped[str] = mapped_column(String(32), nullable=False, default='straight_line')
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False)
    residual_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    depreciation_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    current_book_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    financial_status: Mapped[str] = mapped_column(String(32), nullable=False, default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AssetDepreciationEntry(Base):
    __tablename__ = 'asset_depreciation_entries'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_deprec_entries_company_id_id'),
        UniqueConstraint('company_id', 'asset_id', 'period', name='uq_asset_deprec_entries_company_asset_period'),
        CheckConstraint('depreciation_amount >= 0', name='ck_asset_deprec_entries_amount'),
        CheckConstraint('accumulated_depreciation_after >= 0', name='ck_asset_deprec_entries_accum'),
        CheckConstraint('book_value_after >= 0', name='ck_asset_deprec_entries_book_value'),
        ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
        ),
        Index('ix_asset_deprec_entries_company_period', 'company_id', 'period'),
        Index('ix_asset_deprec_entries_asset_period', 'company_id', 'asset_id', 'period'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # 'YYYY-MM'
    period_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    depreciation_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    accumulated_depreciation_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    book_value_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default='straight_line')
    posted_by_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)


class AssetDisposal(Base):
    __tablename__ = 'asset_disposals'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_disposals_company_id_id'),
        UniqueConstraint('company_id', 'asset_id', name='uq_asset_disposals_company_asset'),
        CheckConstraint(
            "disposal_reason IN ('sale', 'scrap', 'lost', 'damaged', 'obsolete', 'donated', 'trade_in', 'other')",
            name='ck_asset_disposals_reason',
        ),
        CheckConstraint(
            "disposal_method IN ('auction', 'direct_sale', 'certified_destruction', 'recycled', 'trade_in', 'written_off', 'other')",
            name='ck_asset_disposals_method',
        ),
        CheckConstraint('sale_proceeds >= 0', name='ck_asset_disposals_proceeds'),
        ForeignKeyConstraint(
            ['company_id', 'asset_id'],
            ['assets.company_id', 'assets.id'],
            ondelete='RESTRICT',
        ),
        Index('ix_asset_disposals_company_date', 'company_id', 'disposal_date'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    disposal_date: Mapped[date] = mapped_column(Date, nullable=False)
    disposal_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    disposal_method: Mapped[str] = mapped_column(String(32), nullable=False)
    sale_proceeds: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    net_book_value_at_disposal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gain_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    disposed_by_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssetAlert(Base):
    __tablename__ = 'asset_alerts'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_asset_alerts_company_id_id'),
        CheckConstraint("severity IN ('critical', 'warning', 'info')", name='ck_asset_alerts_severity'),
        CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'dismissed')", name='ck_asset_alerts_status'),
        CheckConstraint(
            "resolution_reason IS NULL OR resolution_reason IN ('source_resolved', 'manual_resolution', 'dismissed')",
            name='ck_asset_alerts_resolution_reason',
        ),
        Index(
            'uq_asset_alerts_active_entity',
            'company_id',
            'alert_type',
            'entity_type',
            'entity_id',
            unique=True,
            postgresql_where=text("status IN ('open', 'acknowledged')"),
            sqlite_where=text("status IN ('open', 'acknowledged')"),
        ),
        Index('ix_asset_alerts_company_status', 'company_id', 'status'),
        Index('ix_asset_alerts_company_severity', 'company_id', 'severity'),
        Index('ix_asset_alerts_company_type', 'company_id', 'alert_type'),
        Index('ix_asset_alerts_company_asset', 'company_id', 'asset_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default='warning')
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='open')
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_reference: Mapped[str | None] = mapped_column(String(160))
    asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    days_overdue: Mapped[int | None] = mapped_column(Integer)
    responsible_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    target_route: Mapped[str | None] = mapped_column(String(200))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    resolution_reason: Mapped[str | None] = mapped_column(String(32))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ScheduledJobExecution(Base):
    __tablename__ = 'scheduled_job_executions'
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name='ck_scheduled_job_executions_status'),
        Index('ix_scheduled_job_executions_name_started', 'job_name', 'started_at'),
        Index('ix_scheduled_job_executions_status', 'status'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='running')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    total_companies_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_auto_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    node_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (
        CheckConstraint("severity IN ('critical', 'warning', 'info')", name='ck_notifications_severity'),
        CheckConstraint("status IN ('unread', 'read', 'archived')", name='ck_notifications_status'),
        UniqueConstraint('dedup_key', name='uq_notifications_dedup_key'),
        Index('ix_notifications_recipient_status', 'recipient_user_id', 'status'),
        Index('ix_notifications_company_created', 'company_id', 'created_at'),
        Index('ix_notifications_entity', 'entity_type', 'entity_id'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey('companies.id', ondelete='CASCADE'), index=True)
    recipient_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default='info')
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_route: Mapped[str | None] = mapped_column(String(200))
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='unread')
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class NotificationDelivery(Base):
    __tablename__ = 'notification_deliveries'
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'webhook', 'sms')", name='ck_notification_deliveries_channel'),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name='ck_notification_deliveries_status'),
        Index('ix_notification_deliveries_notification_id', 'notification_id'),
        Index('ix_notification_deliveries_status', 'status'),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    notification_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default='email')
    recipient_address: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())



