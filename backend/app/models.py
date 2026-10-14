from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
