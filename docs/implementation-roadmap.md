# Implementation Roadmap

## Phase 0 — Technical foundation and project scaffold

### Objective
Build the smallest runnable foundation needed to support incremental delivery of the ALCM/ITAM platform.

### Scope included
- Initialise the Angular frontend shell and application layout
- Initialise the FastAPI backend skeleton and project structure
- Configure PostgreSQL in Docker Compose
- Define environment configuration and `.env.example`
- Establish baseline API health endpoints and app startup checks
- Add backend test harness with pytest
- Add frontend build verification and common typed API service scaffolding
- Define standard module boundaries and naming conventions

### Scope deliberately excluded
- Business-specific domain logic for procurement, assets, or maintenance
- Workflow engine implementation beyond initial configuration patterns
- Final production deployment design beyond local Docker-based setup
- External integration adapters beyond interfaces and placeholder modules

### Dependencies on earlier phases
None. This is the first implementation phase.

### Expected deliverables
- Working local development stack for backend, frontend, and database
- Basic project documentation for setup and run commands
- Health-check and smoke-test coverage for key startup paths
- Standard boilerplate for structured module development

### Acceptance criteria and tests
- `docker compose up` starts PostgreSQL and the application stack without manual code patching
- Backend health endpoint responds successfully
- Angular app shell loads in development mode
- Basic backend pytest suite passes for configuration and startup checks
- Environment variables and secrets are documented without hard-coded production values

### Conditions before proceeding
- Local stack runs consistently on a clean machine
- Module boundaries are approved and remain stable
- Basic coding standards and API versioning policy are in place

## Phase 1 — Core master data and basic asset registry

### Status (2026-10-13)
The first slice is implemented and verified. Implemented: company-scoped company, department, site, location, cost centre and category data; numbering rules; asset CRUD/listing/search/filtering; department usage and asset history. Not included in this slice: employee/vendor masters, formal assignment or transfer workflows, authentication/authorization, and actor-attributed audit. Continue with the next planned phase only after these boundaries are accepted.

### Objective
Provide the foundational organisation, asset category, and asset master data needed to support later lifecycle processes.

### Scope included
- Company, site, department, cost centre, and location structures
- Asset categories and numbering conventions
- Asset master records and status model
- Effective-dated department usage and asset change history
- Initial search, filter, and listing screens and APIs

### Scope deliberately excluded
- Full procurement lifecycle and invoicing details
- Advanced maintenance scheduling and repair workflows
- Financial calculations beyond asset metadata and status tracking
- Physical verification campaigns and reconciliation logic
- Employee/vendor masters and formal assignment/transfer workflows
- Authentication, authorization, and actor-attributed audit

### Dependencies on earlier phases
Phase 0 must be complete and stable.

### Expected deliverables
- Organisation master data management screens and APIs
- Asset registry CRUD and listing endpoints
- Asset status and lifecycle metadata model
- Core asset history elements for assignment and custody change

### Acceptance criteria and tests
- Asset creation through the API produces valid records linked to organisation and category metadata
- Asset history records creation, field changes, and department usage events
- Search and filter work against core asset fields
- Validation rejects invalid references or duplicates according to defined rules

### Conditions before proceeding
- Asset master model is stable and consistent with category and organisation structure
- Duplicate and numbering rules are documented and testable

## Phase 2 — Procurement and asset acquisition flow

### Status (2026-10-16)
A bounded supplier → purchase order → goods receipt slice is implemented and under PostgreSQL/API/UI verification. It creates accepted assets and receipt-line traceability atomically, supports partial and rejected quantities, and enforces company scope. Requisitions, quotations, approvals, tax/currency accounting, and document handling are not implemented; they remain planned and require policy decisions.

### Objective
Support the requisition-to-receipt traceability chain required for accountability and lifecycle tracking.

### Scope included
- Purchase requisitions and line items
- Budget references and approval hooks
- Vendor and quotation management fundamentals
- Purchase orders and delivery tracking
- GRN and receipt handling, including partial receipts and discrepancy records
- Linking received goods to registered assets

### Scope deliberately excluded
- Deep invoice matching or accounting close processes
- Complex vendor scorecards or contract management
- Advanced tax or country-specific procurement logic

### Dependencies on earlier phases
Phase 1 must be complete.

### Expected deliverables
- Procurement module with requisition, order, receipt, and discrepancy flows
- Traceability links from requisition to asset registration
- Approval hooks for procurement-related transitions

### Acceptance criteria and tests
- A requisition can be linked to a purchase order and receipt record
- Partial receipts and rejected items can be recorded without losing traceability
- Receipt discrepancies create reviewable records rather than silent data loss
- Asset registration can be traced back to a valid purchase event

### Conditions before proceeding
- Procurement lifecycle states are stable and approval flow integration is defined
- Asset acquisition metadata is strong enough to support later deployment and finance processing

## Phase 3 — Security, configurable policy, and workflow foundation

### Status (2026-10-14)
The local identity/session, company-scoped RBAC, membership invitation, and append-only audit foundation was delivered ahead of this phase's workflow scope. Remaining work includes configurable policies, approval workflows, reason/comment history for approvals, notification infrastructure, and external identity integration decisions.

### Objective
Introduce the governance layer that makes the platform configurable across organisations without code changes.

### Scope included
- Role and permission model
- Approval workflows and permitted state transitions
- Configurable policy tables for organisation-specific rules
- Audit event capture for critical actions
- Reason and comment history for approvals and exceptions
- Basic notification infrastructure for reminders and approvals

### Scope deliberately excluded
- Full visual workflow designer
- Complex dynamic rules engine with unrestricted generic conditions
- Deep integration with external identity systems beyond abstraction points

### Dependencies on earlier phases
Phases 0-2 are required to establish the transaction history and domain objects that the workflow layer governs.

### Expected deliverables
- Policy and workflow configuration tables
- Controlled state transition logic
- Approval history and audit trail APIs
- Security and authorization enforcement across major modules

### Acceptance criteria and tests
- A workflow prevents invalid transitions without requiring source-code edits
- Role-based access restrictions apply to asset and procurement actions
- Approvals generate auditable records with timestamps and reason text
- Configuration can be changed without altering application code

### Conditions before proceeding
- Policy granularity is agreed at least at company/site/category level
- The minimum approval metadata model is finalised
- Security exceptions and override strategy are defined

## Phase 4 — Asset deployment, maintenance, and verification

### Status (2026-10-19)
The Physical Asset Verification module is fully implemented and verified against PostgreSQL. Implemented: campaign lifecycle management (`draft`, `in_progress`, `under_review`, `completed`, `cancelled`), category/location scoping with locked snapshot freezing upon start, physical observations recording, duplicate observation prevention, automatic discrepancy detection (missing, location mismatch, custodian mismatch, condition degradation), controlled discrepancy resolution workflow with mandatory notes and conditional master asset updating (`update_master`), in-field unregistered asset discovery and controlled master registration, real-time KPI metrics, operational reports (`verification-campaigns`, `verification-discrepancies`) with RFC-4180 CSV export, RBAC (`verification.read`, `verification.manage`), and audit event logging.

### Objective
Support the operational lifecycle of assets after acquisition, including assignment, maintenance, and physical verification.

### Scope included
- Deployment and assignment workflows
- Custodian and location history
- Warranty, AMC, SLA, and maintenance records
- Preventive and corrective maintenance
- Service tickets and repair cost tracking
- Audit campaign and verification process
- Exceptions handling for missing, mismatched, or incorrect assets

### Scope deliberately excluded
- Advanced downtime analytics or predictive maintenance models
- Complex maintenance planning across external workforces
- Full enterprise document management beyond attachment support

### Dependencies on earlier phases
Phases 0-3 are required for references, security, and controlled state changes.

### Expected deliverables
- Maintenance and verification modules
- Asset operational history and evidence capture
- Reconciliation workflows for discrepancies and controlled corrections

### Acceptance criteria and tests
- Asset assignment and transfer history is preserved and queryable
- Maintenance records can be linked to warranty, fault, and repair actions
- Verification campaigns generate exception records for missing or mismatched assets
- Audit evidence and discrepancy decisions are persisted for traceability

### Conditions before proceeding
- Maintenance and verification states are consistent across workflows
- Discrepancy handling strategy is documented before automation is expanded

## Phase 5 — Finance, end-of-life, and closure

### Objective
Support financial accountability, asset retirement, disposal decisions, and final closure while preserving historical records.

### Scope included
- Acquisition cost and accounting metadata
- Depreciation and useful-life policy support
- EOL review and repair-versus-replace decisions
- Return and decommissioning flows
- Data-wiping evidence and final disposal record support
- Reuse, resale, scrap, and disposal proceeds
- Final closure while preserving record integrity

### Scope deliberately excluded
- Country-specific tax rules or statutory accounting engine design
- Financial close automation beyond recorded policy-driven calculations
- Regulatory compliance beyond the general product data model

### Dependencies on earlier phases
Phases 0-4 are required, especially asset lifecycle and workflow history.

### Expected deliverables
- Finance and disposal module
- EOL workflow controls and evidence records
- Closure metadata and historical retention model

### Acceptance criteria and tests
- Depreciation and EOL calculations respect configured policy data
- Asset closure cannot occur without required disposal or evidence records
- Historical asset records remain intact after closure
- Disposal proceeds and final status transitions produce auditable records

### Conditions before proceeding
- Accounting and depreciation policy assumptions are reviewed and approved
- Closure and disposal evidence requirements are explicit

## Phase 6 — Reporting, dashboards, integrations, and operational readiness

### Status (2026-10-15)
The Executive Dashboard and first 5 prioritized operational reports (Asset Register, Asset Allocation, Warranty & AMC Expiry, Maintenance Requests, and Procurement & Receiving) along with client-side CSV export have been fully implemented and verified with PostgreSQL integration tests (42 passed) and Angular unit tests (21 passed). External integrations (ERP, HRMS, ITSM, CMDB) and server-side streaming exports remain deferred.

### Objective
Move the product from lifecycle capability to operational business value through reporting and integration boundaries.

### Scope included
- Inventory and lifecycle reporting
- Warranty, maintenance, audit, and disposal dashboards
- Data export and report formatting
- Integration boundaries for ERP, HRMS, ITSM, CMDB, and identity sources
- Versioned API contracts and adapter design

### Scope deliberately excluded
- Full enterprise integration implementation for every external system
- Real-time operational support for all external data feeds
- Advanced predictive analytics

### Dependencies on earlier phases
All previous phases should be considered prerequisite foundations.

### Expected deliverables
- Reporting module and dashboard foundation
- External integration adapter architecture
- API contract and compatibility strategy for external systems

### Acceptance criteria and tests
- Reports are generated using persisted data and not manual assumptions
- Dashboard data reflects actual transactions and lifecycle state
- Integration adapters do not bypass domain services or create tightly coupled logic
- External interfaces remain stable through versioning and clear contracts

### Conditions before proceeding
- Reporting requirements are validated against actual business use cases
- Integration boundary and API contract standards are approved

## Overall release strategy

The first usable release should focus on a practical subset of the full product scope:

- organisation master data
- asset registry and lifecycle basics
- procurement traceability
- security and approval controls
- maintenance and verification fundamentals
- finance and EOL basics for the most common asset classes

This keeps the first release manageable and gives the organisation enough operational value to validate the architecture and policy model before expanding the product footprint.
