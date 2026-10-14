# Domain Model Overview

This document records the planned domain model and distinguishes the Phase 1 entities that are implemented from future concepts. The implemented schema is represented by SQLAlchemy models and managed with Alembic; the remaining entities below are proposals, not current application features.

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

- PurchaseRequisition -> one-to-many -> RequisitionLine
- PurchaseRequisition -> many-to-one -> Vendor
- PurchaseOrder -> one-to-many -> PurchaseOrderLine
- GoodsReceiptNote -> one-to-many -> ReceiptLine
- PurchaseRequisition -> one-to-many -> PurchaseOrder
- PurchaseOrder -> one-to-many -> GoodsReceiptNote
- Asset -> many-to-one -> GoodsReceiptNote or ReceiptLine for traceability

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

Relationships:

- Role -> many-to-many -> Permission
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

- Production authorization and tenant enforcement for the implemented company ownership model
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

## 5. Phase 1 implementation boundary

Implemented now: companies, departments, sites, locations, cost centres, asset categories, configurable asset-number formats, basic assets, searchable/paginated asset lists, department usage relationships, and asset history. Companies are the ownership boundary selected for the current schema; company IDs are explicit in API paths.

Not implemented in this slice: employee/user/custodian and vendor masters, formal assignment/transfer workflows, custom fields, authentication/authorization, actor-attributed audit, procurement, maintenance, physical verification, finance, and disposal. Do not treat company scoping as security isolation until authentication and authorization are added.

## 6. Design intent for the domain model

The proposed model aims to be:

- enterprise-appropriate without being over-engineered
- expressive enough for lifecycle history and auditability
- modular enough to align with the FastAPI monolith structure
- configurable at the policy and workflow layer rather than being hard-coded into the business model
- flexible enough to evolve without redesigning the core asset lifecycle structure

This model should serve as a planning-level guide for the implementation phases and should be refined as soon as product owners answer the open business questions.
