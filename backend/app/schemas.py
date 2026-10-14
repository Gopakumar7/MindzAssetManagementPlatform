from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class DatabaseHealthResponse(BaseModel):
    available: bool
    message: str


class ReadinessResponse(BaseModel):
    status: str
    database: DatabaseHealthResponse


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=160)
    is_active: bool = True
    number_prefix: str = Field(default='AST', min_length=1, max_length=24, pattern=r'^[A-Za-z0-9]+$')
    number_separator: str = Field(default='-', max_length=3)
    number_padding: int = Field(default=6, ge=1, le=12)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None


class CompanyRead(Record):
    id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MasterCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=160)
    is_active: bool = True


class DepartmentCreate(MasterCreate):
    pass


class DepartmentRead(Record):
    id: UUID
    company_id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None


class SiteCreate(MasterCreate):
    address: str | None = None


class SiteRead(Record):
    id: UUID
    company_id: UUID
    code: str
    name: str
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = None
    is_active: bool | None = None


class LocationCreate(MasterCreate):
    details: str | None = None


class LocationRead(Record):
    id: UUID
    company_id: UUID
    site_id: UUID
    code: str
    name: str
    details: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    details: str | None = None
    is_active: bool | None = None


class CostCenterCreate(MasterCreate):
    pass


class CostCenterRead(Record):
    id: UUID
    company_id: UUID
    code: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CostCenterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None


class CategoryCreate(MasterCreate):
    description: str | None = None


class CategoryRead(Record):
    id: UUID
    company_id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class NumberRuleWrite(BaseModel):
    prefix: str = Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9]+$')
    separator: str = Field(default='-', max_length=3)
    padding: int = Field(default=6, ge=1, le=12)


class NumberRuleRead(Record):
    id: UUID
    company_id: UUID
    category_id: UUID | None
    prefix: str
    separator: str
    padding: int
    updated_at: datetime


class AssetCreate(BaseModel):
    category_id: UUID
    asset_number: str | None = Field(default=None, min_length=1, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    acquisition_date: date | None = None
    acquisition_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    status: str = Field(default='in_stock', pattern=r'^[a-z][a-z0-9_]{1,31}$')
    site_id: UUID | None = None
    location_id: UUID | None = None
    responsible_department_id: UUID | None = None
    cost_center_id: UUID | None = None
    custodian_name: str | None = Field(default=None, max_length=160)
    vendor_reference: str | None = Field(default=None, max_length=160)
    invoice_reference: str | None = Field(default=None, max_length=160)
    warranty_start: date | None = None
    warranty_end: date | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def validate_warranty_range(self):
        if self.warranty_start and self.warranty_end and self.warranty_end < self.warranty_start:
            raise ValueError('warranty_end must be on or after warranty_start')
        if self.location_id and not self.site_id:
            raise ValueError('site_id is required when location_id is supplied')
        return self


class AssetUpdate(BaseModel):
    category_id: UUID | None = None
    serial_number: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    acquisition_date: date | None = None
    acquisition_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    status: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9_]{1,31}$')
    site_id: UUID | None = None
    location_id: UUID | None = None
    responsible_department_id: UUID | None = None
    cost_center_id: UUID | None = None
    custodian_name: str | None = Field(default=None, max_length=160)
    vendor_reference: str | None = Field(default=None, max_length=160)
    invoice_reference: str | None = Field(default=None, max_length=160)
    warranty_start: date | None = None
    warranty_end: date | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def validate_warranty_range(self):
        if self.warranty_start and self.warranty_end and self.warranty_end < self.warranty_start:
            raise ValueError('warranty_end must be on or after warranty_start')
        return self


class AssetRead(Record):
    id: UUID
    company_id: UUID
    category_id: UUID
    asset_number: str
    serial_number: str | None
    manufacturer: str | None
    model: str | None
    acquisition_date: date | None
    acquisition_cost: Decimal | None
    status: str
    site_id: UUID | None
    location_id: UUID | None
    responsible_department_id: UUID | None
    cost_center_id: UUID | None
    custodian_name: str | None
    vendor_reference: str | None
    invoice_reference: str | None
    warranty_start: date | None
    warranty_end: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class UsageCreate(BaseModel):
    department_id: UUID
    purpose: str | None = Field(default=None, max_length=300)


class UsageRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    department_id: UUID
    purpose: str | None
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime


class HistoryRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    event_type: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    occurred_at: datetime


T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
