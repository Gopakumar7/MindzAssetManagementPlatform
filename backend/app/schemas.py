from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    password: str = Field(min_length=1, max_length=128)


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    role_code: str = Field(min_length=1, max_length=64)


class InvitationCreateResponse(BaseModel):
    email: str
    company_id: UUID
    role_code: str
    token: str
    expires_at: datetime


class CurrentMembershipRead(BaseModel):
    company_id: UUID
    company_code: str
    company_name: str
    role_code: str
    role_name: str
    permissions: list[str]


class CurrentUserRead(BaseModel):
    id: UUID
    email: str
    system_permissions: list[str]
    memberships: list[CurrentMembershipRead]


class MemberRead(BaseModel):
    id: UUID
    email: str
    membership_id: UUID
    status: str
    role_code: str
    role_name: str
    created_at: datetime


class MembershipUpdateRequest(BaseModel):
    role_code: str | None = Field(default=None, min_length=1, max_length=64)
    status: str | None = Field(default=None, pattern=r'^revoked$')


class RoleRead(BaseModel):
    code: str
    name: str
    scope: str
    permissions: list[str]


class RolePermissionsUpdateRequest(BaseModel):
    permissions: list[str]


class AuditEventRead(Record):
    id: UUID
    occurred_at: datetime
    actor_id: UUID | None
    company_id: UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    outcome: str
    request_id: str | None
    changes: dict | None


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


class SupplierCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    phone: str | None = Field(default=None, max_length=64)
    notes: str | None = None


class SupplierRead(Record):
    id: UUID
    company_id: UUID
    code: str
    name: str
    email: str | None
    phone: str | None
    notes: str | None
    is_active: bool
    created_at: datetime


class PurchaseOrderLineCreate(BaseModel):
    category_id: UUID
    description: str = Field(min_length=1, max_length=300)
    quantity_ordered: int = Field(gt=0, le=10000)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    discount: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=14, decimal_places=2)
    tax_rate: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=6, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=14, decimal_places=2)


class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    order_number: str = Field(min_length=1, max_length=64)
    ordered_date: date
    expected_date: date | None = None
    notes: str | None = None
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_expected_date(self):
        if self.expected_date and self.expected_date < self.ordered_date:
            raise ValueError('expected_date must be on or after ordered_date')
        return self


class PurchaseOrderUpdate(BaseModel):
    supplier_id: UUID | None = None
    order_number: str | None = Field(default=None, min_length=1, max_length=64)
    ordered_date: date | None = None
    expected_date: date | None = None
    notes: str | None = None
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_expected_date(self):
        if self.expected_date and self.ordered_date and self.expected_date < self.ordered_date:
            raise ValueError('expected_date must be on or after ordered_date')
        return self


class PurchaseOrderLineRead(Record):
    id: UUID
    company_id: UUID
    purchase_order_id: UUID
    category_id: UUID
    description: str
    quantity_ordered: int
    unit_cost: Decimal
    discount: Decimal = Decimal('0.00')
    tax_rate: Decimal = Decimal('0.00')
    tax_amount: Decimal = Decimal('0.00')
    line_subtotal: Decimal | None = None
    line_total: Decimal | None = None
    quantity_received: int = 0
    quantity_remaining: int = 0

    @model_validator(mode='after')
    def compute_line_totals(self):
        cost = Decimal(str(self.unit_cost)).quantize(Decimal('0.01'))
        if self.line_subtotal is None:
            self.line_subtotal = (cost * self.quantity_ordered).quantize(Decimal('0.01'))
        if self.line_total is None:
            disc = Decimal(str(self.discount or Decimal('0.00'))).quantize(Decimal('0.01'))
            tax = Decimal(str(self.tax_amount or Decimal('0.00'))).quantize(Decimal('0.01'))
            self.line_total = max(Decimal('0.00'), (self.line_subtotal - disc + tax).quantize(Decimal('0.01')))
        if self.quantity_remaining == 0 and self.quantity_received == 0:
            self.quantity_remaining = self.quantity_ordered
        return self


class PurchaseOrderRead(Record):
    id: UUID
    company_id: UUID
    supplier_id: UUID
    order_number: str
    status: str
    ordered_date: date
    expected_date: date | None = None
    notes: str | None = None
    created_at: datetime
    lines: list[PurchaseOrderLineRead]
    total_quantity: int = 0
    subtotal: Decimal = Decimal('0.00')
    total_discount: Decimal = Decimal('0.00')
    total_tax: Decimal = Decimal('0.00')
    total_amount: Decimal = Decimal('0.00')

    @model_validator(mode='after')
    def compute_po_totals(self):
        if self.lines:
            self.total_quantity = sum(line.quantity_ordered for line in self.lines)
            self.subtotal = sum(line.line_subtotal or Decimal('0.00') for line in self.lines).quantize(Decimal('0.01'))
            self.total_discount = sum(line.discount or Decimal('0.00') for line in self.lines).quantize(Decimal('0.01'))
            self.total_tax = sum(line.tax_amount or Decimal('0.00') for line in self.lines).quantize(Decimal('0.01'))
            self.total_amount = max(Decimal('0.00'), (self.subtotal - self.total_discount + self.total_tax).quantize(Decimal('0.01')))
        return self


class GoodsReceiptLineCreate(BaseModel):
    purchase_order_line_id: UUID
    quantity_received: int = Field(gt=0, le=10000)
    quantity_rejected: int = Field(default=0, ge=0, le=10000)
    serial_numbers: list[str | None] = Field(default_factory=list, max_length=10000)
    discrepancy_notes: str | None = None

    @model_validator(mode='after')
    def validate_rejected_quantity(self):
        if self.quantity_rejected > self.quantity_received:
            raise ValueError('quantity_rejected cannot exceed quantity_received')
        if self.serial_numbers and len(self.serial_numbers) != self.quantity_received - self.quantity_rejected:
            raise ValueError('serial_numbers must match the accepted quantity when provided')
        return self


class GoodsReceiptCreate(BaseModel):
    receipt_number: str = Field(min_length=1, max_length=64)
    received_date: date
    delivery_reference: str | None = Field(default=None, max_length=160)
    notes: str | None = None
    lines: list[GoodsReceiptLineCreate] = Field(min_length=1, max_length=100)


class ReceivedAssetRead(BaseModel):
    id: UUID
    asset_number: str
    serial_number: str | None
    status: str


class GoodsReceiptLineRead(BaseModel):
    id: UUID
    purchase_order_line_id: UUID
    quantity_received: int
    quantity_rejected: int
    discrepancy_notes: str | None
    assets: list[ReceivedAssetRead]


class GoodsReceiptRead(Record):
    id: UUID
    company_id: UUID
    purchase_order_id: UUID
    receipt_number: str
    received_date: date
    delivery_reference: str | None
    notes: str | None
    created_at: datetime
    lines: list[GoodsReceiptLineRead]


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


class AssignmentCreate(BaseModel):
    recipient_id: UUID
    effective_date: date
    responsible_department_id: UUID | None = None
    location_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    reference: str | None = Field(default=None, max_length=160)


class HandoverCreate(BaseModel):
    handover_date: date
    condition: str | None = Field(default=None, max_length=80)
    included_items: str | None = Field(default=None, max_length=4000)
    acknowledgement: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


class ReturnCreate(BaseModel):
    return_date: date
    condition: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)
    issue_details: str | None = Field(default=None, max_length=4000)
    next_asset_status: str = Field(pattern=r'^(in_stock|maintenance)$')


class TransferCreate(BaseModel):
    recipient_id: UUID
    effective_date: date
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    responsible_department_id: UUID | None = None
    location_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=160)
    condition: str | None = Field(default=None, max_length=80)
    included_items: str | None = Field(default=None, max_length=4000)
    acknowledgement: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


class AssignmentRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    recipient_id: UUID
    recipient_email: str
    responsible_department_id: UUID | None
    location_id: UUID | None
    effective_date: date
    status: str
    notes: str | None
    reference: str | None
    handover_date: date | None
    handover_condition: str | None
    included_items: str | None
    acknowledgement: str | None
    handover_notes: str | None
    ended_at: datetime | None
    return_date: date | None
    return_condition: str | None
    return_notes: str | None
    issue_details: str | None
    next_asset_status: str | None
    transfer_reason: str | None
    previous_assignment_id: UUID | None
    created_at: datetime


class AssignmentRecipientRead(BaseModel):
    id: UUID
    email: str


class AssetServiceContractCreate(BaseModel):
    contract_type: str = Field(pattern=r'^(warranty|amc)$')
    supplier_id: UUID | None = None
    provider_name: str | None = Field(default=None, max_length=160)
    reference_number: str | None = Field(default=None, max_length=160)
    start_date: date
    end_date: date
    coverage_description: str | None = Field(default=None, max_length=4000)
    support_contact: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode='after')
    def validate_contract_dates(self):
        if self.end_date < self.start_date:
            raise ValueError('end_date must be on or after start_date')
        return self


class AssetServiceContractRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    supplier_id: UUID | None
    contract_type: str
    provider_name: str | None
    reference_number: str | None
    start_date: date
    end_date: date
    coverage_description: str | None
    support_contact: str | None
    notes: str | None
    status: str
    coverage_status: str
    created_at: datetime


class MaintenanceRequestCreate(BaseModel):
    asset_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    issue_description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    priority: str = Field(default='normal', pattern=r'^(low|normal|high|urgent)$')
    reported_date: date
    assignee_id: UUID | None = None


class MaintenanceRequestUpdate(BaseModel):
    status: str | None = Field(default=None, pattern=r'^(open|in_progress|resolved|closed)$')
    assignee_id: UUID | None = None
    diagnosis: str | None = Field(default=None, max_length=8000)
    work_performed: str | None = Field(default=None, max_length=8000)
    resolution_notes: str | None = Field(default=None, max_length=8000)
    completed_date: date | None = None
    cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode='after')
    def validate_completion(self):
        if self.status == 'resolved' and self.completed_date is None:
            raise ValueError('completed_date is required when resolving a request')
        return self


class MaintenanceRequestRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    asset_number: str
    requester_id: UUID
    requester_email: str
    assignee_id: UUID | None
    assignee_email: str | None
    title: str
    issue_description: str
    priority: str
    status: str
    reported_date: date
    diagnosis: str | None
    work_performed: str | None
    resolution_notes: str | None
    completed_date: date | None
    cost: Decimal | None
    created_at: datetime
    updated_at: datetime


T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class CategoryMetric(BaseModel):
    category_id: UUID
    category_name: str
    count: int


class SiteMetric(BaseModel):
    site_id: UUID | None
    site_name: str
    count: int


class DepartmentMetric(BaseModel):
    department_id: UUID | None
    department_name: str
    count: int


class ExpiringContractMetric(BaseModel):
    id: UUID
    contract_type: str
    reference_number: str | None
    provider_name: str | None
    asset_id: UUID
    asset_number: str
    end_date: date
    days_remaining: int


class MaintenanceSummaryMetric(BaseModel):
    open: int
    in_progress: int
    resolved: int
    closed: int
    total_open_and_in_progress: int


class ProcurementSummaryMetric(BaseModel):
    total_purchase_orders: int
    orders_by_status: dict[str, int]
    total_goods_receipts: int
    total_items_received: int
    total_items_rejected: int


class RecentActivityMetric(BaseModel):
    id: UUID
    action: str
    entity_type: str
    entity_id: str | None
    actor_id: UUID | None
    actor_email: str | None = None
    outcome: str
    occurred_at: datetime


class DashboardResponse(BaseModel):
    total_assets: int
    assets_by_status: dict[str, int]
    assets_by_category: list[CategoryMetric]
    assets_by_site: list[SiteMetric]
    assets_by_department: list[DepartmentMetric]
    expiring_contracts_count: int
    expiring_contracts: list[ExpiringContractMetric]
    maintenance_summary: MaintenanceSummaryMetric
    procurement_summary: ProcurementSummaryMetric
    recent_activity: list[RecentActivityMetric]


class AssetRegisterReportItem(BaseModel):
    id: UUID
    asset_number: str
    category_id: UUID
    category_name: str
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    status: str
    site_id: UUID | None
    site_name: str | None
    department_id: UUID | None
    department_name: str | None
    custodian_name: str | None
    acquisition_date: date | None
    acquisition_cost: Decimal | None
    warranty_start: date | None
    warranty_end: date | None


class AssetAllocationReportItem(BaseModel):
    assignment_id: UUID | None
    asset_id: UUID
    asset_number: str
    model: str | None
    category_name: str
    recipient_id: UUID | None
    recipient_email: str | None
    department_id: UUID | None
    department_name: str | None
    site_id: UUID | None
    site_name: str | None
    location_id: UUID | None
    location_name: str | None
    effective_date: date | None
    status: str
    reference: str | None


class WarrantyExpiryReportItem(BaseModel):
    id: UUID
    contract_type: str
    reference_number: str | None
    provider_name: str | None
    supplier_name: str | None
    asset_id: UUID
    asset_number: str
    asset_model: str | None
    start_date: date
    end_date: date
    days_remaining: int
    status: str
    coverage_status: str
    support_contact: str | None


class MaintenanceReportItem(BaseModel):
    id: UUID
    title: str
    asset_id: UUID
    asset_number: str
    priority: str
    status: str
    requester_email: str
    assignee_email: str | None
    reported_date: date
    completed_date: date | None
    cost: Decimal | None
    diagnosis: str | None
    work_performed: str | None
    resolution_notes: str | None


class ProcurementReportLineItem(BaseModel):
    line_id: UUID
    category_id: UUID
    category_name: str
    description: str
    quantity_ordered: int
    quantity_received: int
    quantity_rejected: int
    quantity_outstanding: int
    unit_cost: Decimal


class ProcurementReportItem(BaseModel):
    order_id: UUID
    order_number: str
    supplier_id: UUID
    supplier_name: str
    ordered_date: date
    expected_date: date | None
    order_status: str
    total_ordered_quantity: int
    total_received_quantity: int
    total_outstanding_quantity: int
    lines: list[ProcurementReportLineItem]
    receipt_numbers: list[str]


class VerificationCampaignCreate(BaseModel):
    campaign_reference: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    start_date: date
    end_date: date
    scope_category_ids: list[UUID] | None = None
    scope_location_ids: list[UUID] | None = None


class VerificationCampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    scope_category_ids: list[UUID] | None = None
    scope_location_ids: list[UUID] | None = None


class VerificationCampaignStatusTransition(BaseModel):
    status: str = Field(pattern=r'^(in_progress|under_review|completed|cancelled)$')
    notes: str | None = None


class VerificationCampaignRead(Record):
    id: UUID
    company_id: UUID
    campaign_reference: str
    name: str
    description: str | None = None
    status: str
    start_date: date
    end_date: date
    scope_category_ids: list[UUID] | None = None
    scope_location_ids: list[UUID] | None = None
    created_by_id: UUID
    created_by_name: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    closed_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    total_expected: int = 0
    total_verified: int = 0
    total_unverified: int = 0
    total_missing: int = 0
    total_discrepancies: int = 0
    total_unregistered: int = 0
    completion_percentage: float = 0.0


class VerificationExpectedAssetRead(Record):
    id: UUID
    company_id: UUID
    campaign_id: UUID
    asset_id: UUID
    asset_number: str
    category_id: UUID
    category_name: str | None = None
    serial_number: str | None = None
    model: str | None = None
    manufacturer: str | None = None
    expected_site_id: UUID | None = None
    site_name: str | None = None
    expected_location_id: UUID | None = None
    location_name: str | None = None
    expected_department_id: UUID | None = None
    department_name: str | None = None
    expected_custodian_id: UUID | None = None
    expected_custodian_name: str | None = None
    expected_condition: str | None = None
    expected_status: str
    is_verified: bool = False
    observation_id: UUID | None = None
    observation_found: bool | None = None
    has_discrepancy: bool = False
    discrepancy_types: list[str] = Field(default_factory=list)
    created_at: datetime


class VerificationObservationCreate(BaseModel):
    is_found: bool = True
    actual_location_id: UUID | None = None
    actual_custodian_id: UUID | None = None
    observed_condition: str = Field(default='good', max_length=32)
    verification_date: date | None = None
    remarks: str | None = None
    reference_notes: str | None = None


class VerificationObservationRead(Record):
    id: UUID
    company_id: UUID
    campaign_id: UUID
    expected_asset_id: UUID | None = None
    asset_id: UUID | None = None
    asset_number: str | None = None
    is_found: bool
    actual_site_id: UUID | None = None
    actual_site_name: str | None = None
    actual_location_id: UUID | None = None
    actual_location_name: str | None = None
    actual_department_id: UUID | None = None
    actual_custodian_id: UUID | None = None
    actual_custodian_name: str | None = None
    observed_condition: str
    verification_date: date
    verified_by_id: UUID
    verified_by_name: str | None = None
    remarks: str | None = None
    reference_notes: str | None = None
    created_at: datetime


class VerificationDiscrepancyResolveRequest(BaseModel):
    resolution_action: str = Field(pattern=r'^(update_master|register_asset|mark_missing|dismiss|no_change)$')
    resolution_notes: str = Field(min_length=1, max_length=500)


class VerificationDiscrepancyRead(Record):
    id: UUID
    company_id: UUID
    campaign_id: UUID
    campaign_reference: str | None = None
    observation_id: UUID | None = None
    expected_asset_id: UUID | None = None
    asset_id: UUID | None = None
    asset_number: str | None = None
    discrepancy_type: str
    status: str
    expected_data: dict | None = None
    observed_data: dict | None = None
    notes: str | None = None
    resolution_action: str | None = None
    resolution_notes: str | None = None
    resolved_by_id: UUID | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class VerificationUnregisteredAssetCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    category_id: UUID
    serial_number: str | None = None
    site_id: UUID | None = None
    location_id: UUID | None = None
    custodian_id: UUID | None = None
    observed_condition: str | None = 'good'
    remarks: str | None = None


class VerificationUnregisteredAssetRegister(BaseModel):
    asset_number: str | None = None
    cost_center_id: UUID | None = None
    responsible_department_id: UUID | None = None
    acquisition_cost: Decimal | None = None
    acquisition_date: date | None = None
    resolution_notes: str = Field(default='Registered from verification finding', min_length=1)


class VerificationUnregisteredAssetRead(Record):
    id: UUID
    company_id: UUID
    campaign_id: UUID
    observation_id: UUID | None = None
    discrepancy_id: UUID | None = None
    serial_number: str | None = None
    description: str
    category_id: UUID
    category_name: str | None = None
    site_id: UUID | None = None
    site_name: str | None = None
    location_id: UUID | None = None
    location_name: str | None = None
    custodian_id: UUID | None = None
    custodian_name: str | None = None
    observed_condition: str | None = None
    remarks: str | None = None
    status: str
    registered_asset_id: UUID | None = None
    registered_asset_number: str | None = None
    created_at: datetime


class VerificationDashboardSummary(BaseModel):
    campaign_id: UUID
    campaign_reference: str
    campaign_name: str
    status: str
    start_date: date
    end_date: date
    total_expected: int
    total_verified: int
    total_unverified: int
    total_missing: int
    completion_percentage: float
    discrepancies_by_type: dict[str, int]
    unregistered_count: int
    pending_resolutions: int
    resolved_resolutions: int


class VerificationCampaignReportItem(BaseModel):
    campaign_id: UUID
    campaign_reference: str
    campaign_name: str
    status: str
    start_date: date
    end_date: date
    total_expected: int
    total_verified: int
    total_missing: int
    discrepancy_count: int
    unregistered_count: int
    completion_percentage: float
    created_at: datetime
    completed_at: datetime | None = None


class VerificationDiscrepancyReportItem(BaseModel):
    discrepancy_id: UUID
    campaign_reference: str
    campaign_name: str
    asset_number: str | None = None
    discrepancy_type: str
    status: str
    expected_summary: str | None = None
    observed_summary: str | None = None
    notes: str | None = None
    resolution_action: str | None = None
    resolution_notes: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class AssetFinancialCreate(BaseModel):
    capitalised_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default='USD', min_length=3, max_length=3)
    depreciation_method: str = Field(default='straight_line')
    useful_life_months: int = Field(ge=1, le=1200)
    residual_value: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=14, decimal_places=2)
    depreciation_start_date: date

    @model_validator(mode='after')
    def validate_residual_le_cost(self):
        if self.residual_value > self.capitalised_cost:
            raise ValueError('residual_value cannot exceed capitalised_cost')
        return self


class AssetFinancialUpdate(BaseModel):
    capitalised_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    depreciation_method: str | None = Field(default=None)
    useful_life_months: int | None = Field(default=None, ge=1, le=1200)
    residual_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    depreciation_start_date: date | None = None

    @model_validator(mode='after')
    def validate_residual_le_cost(self):
        if self.capitalised_cost is not None and self.residual_value is not None:
            if self.residual_value > self.capitalised_cost:
                raise ValueError('residual_value cannot exceed capitalised_cost')
        return self


class AssetFinancialAdjust(BaseModel):
    useful_life_months: int | None = Field(default=None, ge=1, le=1200)
    residual_value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    notes: str | None = None


class AssetFinancialRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    capitalised_cost: Decimal
    currency: str
    depreciation_method: str
    useful_life_months: int
    residual_value: Decimal
    depreciation_start_date: date
    accumulated_depreciation: Decimal
    current_book_value: Decimal
    financial_status: str
    created_at: datetime
    updated_at: datetime


class DepreciationScheduleItem(BaseModel):
    period: str
    period_start_date: date
    period_end_date: date
    depreciation_amount: Decimal
    accumulated_depreciation: Decimal
    book_value: Decimal
    status: str  # 'posted', 'pending', 'skipped'


class DepreciationPostRequest(BaseModel):
    period: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    notes: str | None = None


class BatchDepreciationRequest(BaseModel):
    period: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    notes: str | None = None


class BatchDepreciationResult(BaseModel):
    period: str
    processed_count: int
    posted_count: int
    skipped_count: int
    total_depreciation_posted: Decimal
    posted_asset_ids: list[UUID]
    skipped: list[dict]


class AssetDepreciationEntryRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    period: str
    period_start_date: date
    period_end_date: date
    depreciation_amount: Decimal
    accumulated_depreciation_after: Decimal
    book_value_after: Decimal
    method: str
    posted_by_id: UUID
    posted_at: datetime
    notes: str | None


class AssetDisposalCreate(BaseModel):
    disposal_date: date
    disposal_reason: str = Field(min_length=1, max_length=32)
    disposal_method: str = Field(min_length=1, max_length=32)
    sale_proceeds: Decimal = Field(default=Decimal('0.00'), ge=0, max_digits=14, decimal_places=2)
    notes: str | None = None


class AssetDisposalRead(Record):
    id: UUID
    company_id: UUID
    asset_id: UUID
    disposal_date: date
    disposal_reason: str
    disposal_method: str
    sale_proceeds: Decimal
    net_book_value_at_disposal: Decimal
    gain_loss: Decimal
    notes: str | None
    disposed_by_id: UUID
    created_at: datetime


class AssetDepreciationReportItem(BaseModel):
    asset_id: UUID
    asset_number: str
    asset_name: str
    category_name: str
    site_name: str | None = None
    location_name: str | None = None
    acquisition_date: date | None = None
    capitalised_cost: Decimal
    currency: str
    depreciation_method: str
    useful_life_months: int
    residual_value: Decimal
    depreciation_start_date: date
    accumulated_depreciation: Decimal
    current_book_value: Decimal
    financial_status: str


class AssetDisposalReportItem(BaseModel):
    asset_id: UUID
    asset_number: str
    asset_name: str
    category_name: str
    acquisition_date: date | None = None
    acquisition_cost: Decimal | None = None
    disposal_date: date
    disposal_reason: str
    disposal_method: str
    sale_proceeds: Decimal
    net_book_value_at_disposal: Decimal
    gain_loss: Decimal
    disposed_by_email: str | None = None
    notes: str | None = None


class FinancialDashboardMetric(BaseModel):
    total_capitalised_cost: Decimal
    total_accumulated_depreciation: Decimal
    total_net_book_value: Decimal
    approaching_eol_count: int
    fully_depreciated_active_count: int
    disposed_count: int
    total_disposal_proceeds: Decimal
    total_disposal_gain_loss: Decimal


class AssetAlertRead(Record):
    id: UUID
    company_id: UUID
    alert_type: str
    severity: str
    status: str
    title: str
    description: str | None = None
    entity_type: str
    entity_id: UUID
    entity_reference: str | None = None
    asset_id: UUID | None = None
    due_date: date | None = None
    days_overdue: int | None = None
    responsible_user_id: UUID | None = None
    responsible_user_email: str | None = None
    target_route: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_id: UUID | None = None
    acknowledged_by_email: str | None = None
    resolved_at: datetime | None = None
    resolved_by_id: UUID | None = None
    resolved_by_email: str | None = None
    resolution_reason: str | None = None
    resolution_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class AssetAlertSummary(BaseModel):
    total_open: int
    total_acknowledged: int
    total_resolved: int
    total_dismissed: int
    critical_count: int
    warning_count: int
    info_count: int
    by_type: dict[str, int]


class AlertAcknowledgeRequest(BaseModel):
    notes: str | None = None


class AlertAssignRequest(BaseModel):
    responsible_user_id: UUID


class AlertResolveRequest(BaseModel):
    resolution_reason: str = Field(default='manual_resolution', pattern=r'^(manual_resolution|source_resolved)$')
    resolution_notes: str | None = None


class AlertDismissRequest(BaseModel):
    resolution_notes: str | None = None


class AlertSyncResponse(BaseModel):
    synced: bool
    created_count: int
    updated_count: int
    auto_resolved_count: int
    active_count: int


class ScheduledJobExecutionRead(BaseModel):
    id: UUID
    job_name: str
    status: str
    started_at: datetime
    last_heartbeat_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    total_companies_processed: int = 0
    alerts_created: int = 0
    alerts_updated: int = 0
    alerts_auto_resolved: int = 0
    error_message: str | None = None
    node_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationRead(BaseModel):
    id: UUID
    company_id: UUID | None = None
    recipient_user_id: UUID
    notification_type: str
    title: str
    message: str
    severity: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    target_route: str | None = None
    status: str
    read_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationUnreadCount(BaseModel):
    unread_count: int


class NotificationDeliveryRead(BaseModel):
    id: UUID
    notification_id: UUID
    channel: str
    recipient_address: str
    status: str
    attempts: int
    last_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)




