# Domain Model Overview

This document records the implemented domain model and distinguishes it from future concepts. Implemented schema is represented by SQLAlchemy models and managed with Alembic; future entities below are proposals, not current application features.

## 1. Foundational entities needed early

These are the central structures without which most of the product cannot be implemented sensibly.

### Organisation and configuration

- Company
  - Represents a legal or organisational entity within the product
  - May be the top-level tenant or organisational grouping
- Site
  - Physical or logical operating site
  - Belongs to a company
- Department
  - Operational business unit within a company or site
- CostCenter
  - Financial responsibility center tied to departments or organisations
- Location
  - More granular physical location or room, often used for asset assignment
- Employee / User
  - Person with role assignment, custodian ownership, and approval authority
- Vendor
  - External party supplying goods or services
- AssetCategory
  - High-level category such as hardware, software, facility equipment, or other class
- AssetIdentifierRule
  - Numbering conventions, prefixes, or sequence definitions used for unique asset identifiers

Relationships:

- Company -> one-to-many -> Site
- Company -> one-to-many -> Department
- Company -> one-to-many -> CostCenter
- Site -> one-to-many -> Location
- Department -> one-to-many -> Employee / User
- Employee / User -> many-to-many -> Role
- AssetCategory -> one-to-many -> Asset

### Asset registry

- Asset
  - Core lifecycle entity for an individual item
  - Carries status, location, custodian, asset category, manufacturer, model, and acquisition metadata
- AssetStatus
  - Reference data for lifecycle state such as active, assigned, in repair, disposed, or closed
- AssetAssignment
  - History of assignment or custody changes over time
- AssetLocationHistory
  - History of asset location movement
- AssetTag
  - Barcode, QR code, or other identifier record associated with an asset
- Manufacturer
  - Supplier or maker of the asset
- Model
  - Product model linked to a manufacturer and category

Relationships:

- AssetCategory -> one-to-many -> Asset
- Asset -> one-to-many -> AssetAssignment
- Asset -> one-to-many -> AssetLocationHistory
- Asset -> one-to-many -> AssetTag
- Asset -> many-to-one -> Manufacturer
- Asset -> many-to-one -> Model

### Procurement and acquisition

- Supplier
  - Minimal company-scoped supplier master with code, name, and optional contact details
- PurchaseOrder
  - Company-scoped order header linked to one supplier
- PurchaseOrderLine
  - Category, description, quantity ordered, and unit cost for one order line
- GoodsReceipt
  - Dated receipt event linked to a purchase order with receipt and delivery references
- GoodsReceiptLine
  - Received and rejected quantities, discrepancy notes, and link to the order line
- Asset receipt traceability
  - Each accepted received unit creates one in-stock Asset; the Asset retains its receipt-line reference
- PurchaseRequisition
  - Request to acquire goods or services
- RequisitionLine
  - Line item within a requisition
- VendorQuotation
  - Quote received from a vendor
- PurchaseOrder
  - Formal purchase commitment
- PurchaseOrderLine
  - Line details for purchase orders
- GoodsReceiptNote
  - Goods received record and confirmation
- ReceiptLine
  - Item-level receipt detail
- DiscrepancyRecord
  - Rejected, damaged, short-supplied, or mismatched item record

Relationships:

- Supplier -> one-to-many -> PurchaseOrder
- PurchaseOrder -> one-to-many -> PurchaseOrderLine
- PurchaseOrder -> one-to-many -> GoodsReceipt
- GoodsReceipt -> one-to-many -> GoodsReceiptLine
- GoodsReceiptLine -> one-to-many -> Asset
- PurchaseRequisition -> one-to-many -> RequisitionLine
- PurchaseRequisition -> many-to-one -> Vendor
- PurchaseOrder -> one-to-many -> PurchaseOrderLine
- GoodsReceiptNote -> one-to-many -> ReceiptLine
- PurchaseRequisition -> one-to-many -> PurchaseOrder
- PurchaseOrder -> one-to-many -> GoodsReceiptNote
- Asset -> many-to-one -> GoodsReceiptNote or ReceiptLine for traceability

Current procurement implementation is deliberately narrower than the proposed future procurement model: it does not include requisitions, quotations, purchase approvals, tax/currency treatment, attachments, or supplier portals. The receipt operation is transactional: receipt headers/lines, accepted assets, asset history, and audit records persist together. Rejected units are retained as receipt discrepancies and do not become assets.

### Security and governance

- Role
  - Organisational role used for access and authorisation
- Permission
  - Action-level access rights or business permission
- ApprovalWorkflow
  - Configurable workflow definition for a business process
- ApprovalStep
  - A configured step in a workflow
- ApprovalAction
  - Specific approval, rejection, escalation, or exception decision record
- AuditEvent
  - High-level event record for critical business operations
- User
  - Local account with normalized email, Argon2id password hash, and active state
- CompanyMembership
  - User's active, pending, or revoked role assignment within one company
- AuthSession
  - Server-side record of a hashed opaque session token, CSRF-token digest, expiry, and revocation state
- UserInvitation
  - Hashed one-time token used to activate or add a user to a company membership

Relationships:

- Role -> many-to-many -> Permission
- User -> many-to-many -> Company through CompanyMembership -> Role
- User -> many-to-many -> system Role through SystemRoleAssignment
- User -> one-to-many -> AuthSession
- CompanyMembership -> one-to-many -> UserInvitation
- User / Company -> one-to-many -> AuditEvent (actor/company may be absent for unauthenticated security events)
- Employee / User -> many-to-many -> Role
- ApprovalWorkflow -> one-to-many -> ApprovalStep
- Asset / Procurement / Disposal process -> one-to-many -> ApprovalAction
- Asset / Procurement / Finance records -> one-to-many -> AuditEvent

## 2. Entities needed in later phases

These should be designed after the core lifecycle baseline is stable, but they are clearly required by the business scope.

### Maintenance and service

- WarrantyRecord
  - Warranty metadata and expiry dates
- ServiceLevelAgreement
  - SLA contract or service profile
- MaintenancePlan
  - Preventive maintenance schedule
- MaintenanceOrder
  - Planned maintenance task
- ServiceTicket
  - Repair or incident ticket record
- RepairRecord
  - Corrective work event and outcomes
- DowntimeEvent
  - Operational outage tracking linked to an asset or ticket

### Verification and audit

- AuditCampaign
  - Physical verification effort or scheduled review
- ExpectedAssetList
  - Assets expected in an audit campaign
- VerificationRecord
  - Physical verification outcome for the asset
- ExceptionRecord
  - Missing, mismatched, or discrepancy record
- ReconciliationAction
  - Controlled correction or follow-up action

### Finance and end-of-life

- DepreciationPolicy
  - Configurable policy that determines depreciation treatment
- DepreciationEntry
  - Periodic depreciation transaction or record
- EOLReview
  - End-of-life evaluation record
- DisposalDecision
  - Decision to repair, replace, reuse, scrap, resell, or dispose
- DisposalCertificate
  - Evidence or official closure record
- DataWipeCertificate
  - Proof that data was securely erased
- FinalClosureRecord
  - Closed asset record that retains historical integrity

### Reporting and integration

- ReportDefinition
  - Stored metadata for an operational report or dashboard definition
- DatasetExport
  - Export job or file snapshot of data
- IntegrationAdapter
  - External-system adapter contract definition
- IntegrationMapping
  - Transformation metadata for ERP, HRMS, ITSM, or CMDB integration

## 3. Areas where the requirement is not yet detailed enough to finalise the design

These areas must remain intentionally flexible until the product owner clarifies them.

- Future external identity integration and any finer-grained authorization below company scope
- Software entitlement and license lifecycle handling
- External identity integration and user provisioning model
- Shared asset vs. employee-owned asset semantics for non-IT assets
- Precise document retention and security policy
- Depreciation and accounting rules by organisational policy
- Integration priorities for ERP, HRMS, ITSM, CMDB, and asset discovery tools
- Whether barcode scanning is browser-only or device-integrated

## 4. Proposed relationship model by business module

### Implemented Phase 1 relationships

- Company 1..n Departments, Sites, CostCenters, AssetCategories, AssetNumberRules, and Assets
- Site 1..n Locations
- AssetCategory 1..n Assets and optional category-specific AssetNumberRules
- Asset 1..n AssetDepartmentUsages and AssetHistory records
- Related company-owned records are constrained to the same company by composite foreign keys where applicable

Asset department usage is an effective-dated relationship and does not replace the asset's responsible department, custodian, site, or location. Asset history records creation, changed fields, and usage start/end events. Actor identity and reason attribution are not yet implemented.

### Planned relationship model by business module

### Organisation module

- Company 1..n Sites
- Company 1..n Departments
- Company 1..n CostCenters
- Company 1..n Employees / Users
- Company 1..n Vendors
- Site 1..n Locations
- Company 1..n AssetCategories

### Asset module

- AssetCategory 1..n Asset
- Asset 1..n AssetAssignment
- Asset 1..n AssetLocationHistory
- Asset 1..n AssetTag
- Asset many-to-one Model
- Asset many-to-one Manufacturer

### Procurement module

- PurchaseRequisition 1..n RequisitionLine
- PurchaseRequisition many-to-one Vendor
- PurchaseRequisition 1..n PurchaseOrder
- PurchaseOrder 1..n PurchaseOrderLine
- PurchaseOrder 1..n GoodsReceiptNote
- GoodsReceiptNote 1..n ReceiptLine
- ReceiptLine 0..1 Asset (for immediate registration or traceability)

### Governance module

- Role many-to-many Permission
- Employee / User many-to-many Role
- ApprovalWorkflow 1..n ApprovalStep
- ApprovalStep 1..n ApprovalAction
- Asset / Procurement / Finance records 1..n AuditEvent

### Lifecycle modules

- Asset 1..n WarrantyRecord
- Asset 1..n MaintenanceOrder
- Asset 1..n ServiceTicket
- Asset 1..n VerificationRecord
- Asset 1..n EOLReview
- Asset 1..n FinalClosureRecord

## 5. Phase 3 asset assignment lifecycle

The organisation model has company memberships and user accounts but no employee master. Phase 3 therefore identifies recipients as active users with an active membership in the asset's company; it does not introduce an HR/employee master. Custodian assignment is distinct from asset ownership, responsible department, departments using or sharing an asset, and physical location.

Lifecycle state and transition rules:

| Record | State | Allowed transition | Effect |
| --- | --- | --- | --- |
| Asset | `in_stock` | Assign | Create an `active` assignment; set the asset status to `assigned` |
| Assignment | `active` | Handover | Record the single handover date, condition, items, acknowledgement, and notes; assignment remains active |
| Assignment | `active` | Return | Record return details and close as `returned`; set the asset status to `in_stock` or `maintenance` |
| Assignment | `active` | Transfer | Close as `transferred` and create the next `active` assignment atomically; asset remains `assigned` |
| Assignment | `returned` or `transferred` | Any lifecycle mutation | Reject; records are historical and immutable through these workflows |
| Asset | Any status other than `in_stock` | Assign | Reject; only eligible stock is assignable |

An asset may have at most one active assignment. A partial unique database index enforces that invariant even when concurrent requests race; PostgreSQL row locking serializes lifecycle mutations for one asset. All assignments belong to the same company as their asset, and recipient membership, department, and location are validated within that company. A transfer retains the prior assignment and handover/return data and records the reason on the ended record and the new assignment. Return requires an explicit next status (`in_stock` or `maintenance`). Assignment history and audit events are persisted with the asset mutation in the same transaction.

## 6. Warranty, AMC, and maintenance service records

The asset's existing `warranty_start` and `warranty_end` fields remain the basic acquisition-warranty dates. Additional `AssetServiceContract` records retain warranty and AMC references, provider/supplier, coverage, support contact, notes, and effective dates. A supplied vendor reference is matched to an active company supplier by supplier code when no supplier is selected. Contract references are unique per asset and company; contracts can be cancelled but are not deleted.

Coverage status is calculated at read time using the server's current date: `upcoming` before the start date, `expired` after the inclusive end date, `expiring_soon` when coverage is active and ends within 30 days (inclusive), `active` otherwise during the effective date range, and `cancelled` for cancelled records. The 30-day threshold is a display rule and does not send reminders.

`MaintenanceRequest` captures the asset, authenticated requester, optional active company-member support assignee, issue, priority, reported date, diagnosis, work performed, resolution notes, completion date, and optional non-negative cost. Its allowed state path is `open` → `in_progress` → `resolved` → `closed`; resolution requires a completion date on or after the report date and non-empty resolution notes. Closed records are immutable. Asset and assignee company relationships are enforced by company-scoped foreign keys, and each accepted mutation and transition is written to the existing audit log in the same transaction.

## 7. Implemented domain boundary

Implemented now: companies, departments, sites, locations, cost centres, asset categories, configurable asset-number formats, basic assets, searchable/paginated asset lists, department usage relationships, asset history, assignment/handover/return/transfer records, supplier/purchase-order/goods-receipt procurement, warranty/AMC service contracts, maintenance requests, local user accounts, system/company roles and permissions, company memberships, invitations, server-side sessions, login throttling, and append-only audit events. Companies are the ownership boundary selected for the current schema; protected API operations require database-backed membership/system permission checks.

Not implemented in this slice: separate employee/custodian master, custom fields, external identity/SSO, MFA, password recovery, email delivery, finer-grained scope below company, preventive maintenance schedules, SLA escalation, downtime analytics, physical verification, finance, and disposal. Angular permission checks are only a UX aid; FastAPI is the authorization boundary.

## 8. Design intent for the domain model

The proposed model aims to be:

- enterprise-appropriate without being over-engineered
- expressive enough for lifecycle history and auditability
- modular enough to align with the FastAPI monolith structure
- configurable at the policy and workflow layer rather than being hard-coded into the business model
- flexible enough to evolve without redesigning the core asset lifecycle structure

This model should serve as a planning-level guide for the implementation phases and should be refined as soon as product owners answer the open business questions.
