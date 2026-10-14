# Requirements Traceability

This document maps the prompt's major capability areas to the proposed module structure, planned delivery phase, and principal acceptance checks.

## 1. Organisation and configuration

- Capability area
  - Companies, organisational units, sites, locations, departments, cost centres, and master data
- Proposed module
  - `organization`
- Planned implementation phase
  - Phase 1
- Principal acceptance checks
  - Company, department, site, location, and cost-centre records can be created and maintained through scoped APIs
  - Asset records can reference valid same-company organisation and category data
  - Company-scoped asset categories and numbering formats can be configured
- Additional detail needed
  - Production identity and authorization rules for company access
  - Whether custom fields will be category-scoped, organisation-scoped, or both
  - Employee/custodian and vendor master requirements
  - Status: foundation slice implemented; authentication, custom fields, and employee/vendor masters remain out of scope

## 2. Procurement and asset acquisition

- Capability area
  - Purchase requisitions, quotations, orders, GRNs, inspections, rejects, and traceability
- Proposed module
  - `procurement`
- Planned implementation phase
  - Phase 2
- Principal acceptance checks
  - Requisition, order, receipt, and asset registration records can be linked
  - Partial receipts and discrepancies are tracked and reviewable
  - Material movement and receiving exceptions are governed by policy rules
- Additional detail needed
  - Approval threshold model for procurement
  - Whether procurement is enterprise-wide or limited to certain asset classes

## 3. Asset registry and deployment

- Capability area
  - Asset master, serial numbers, status, assignment, custody history, deployment, transfers, and locations
- Proposed module
  - `assets`
- Planned implementation phase
  - Phase 1 and Phase 4
- Principal acceptance checks
  - Asset master records are unique, complete, and linked to organisation metadata
  - Custody and assignment changes are recorded with traceable history
  - Assets can be transferred or re-assigned without losing lifecycle context
- Additional detail needed
  - Final asset-type taxonomy
  - Barcode/QR scanning requirements and supported device flows
  - Status: basic registry, numbering, search/filter, department usage, and history implemented; formal assignment/transfer workflow deferred

## 4. Warranty and maintenance

- Capability area
  - Warranty, AMC, SLA, preventive and corrective maintenance, service tickets, repair costs, and downtime
- Proposed module
  - `maintenance`
- Planned implementation phase
  - Phase 4
- Principal acceptance checks
  - Warranty and maintenance records remain linked to the correct asset
  - Tickets generate auditable service history and cost tracking
  - Preventive actions and corrective maintenance are tracked independently where required
- Additional detail needed
  - Standard maintenance workflow and escalation rules
  - Quantity and cost modelling for service events

## 5. Physical verification and audit

- Capability area
  - Audit campaigns, expected asset lists, verification outcomes, evidence, exceptions, and reconciliation
- Proposed module
  - `verification`
- Planned implementation phase
  - Phase 4
- Principal acceptance checks
  - Physical verification can be executed against expected asset records
  - Exceptions for missing, mismatched, or incorrect assets are captured with evidence
  - Corrective actions and reconciliation status are reviewable and auditable
- Additional detail needed
  - Recommended evidence format and retention requirements
  - Whether verification exclusions are category- or location-specific

## 6. Finance and end-of-life management

- Capability area
  - Acquisition cost, depreciation, useful life, EOL review, repair-vs-replace decisions, closure, disposal, and evidence
- Proposed module
  - `finance`
- Planned implementation phase
  - Phase 5
- Principal acceptance checks
  - Financial metadata and depreciation policy are applied correctly
  - EOL decisions can be tracked and approved
  - Disposal and closure records preserve historical integrity
- Additional detail needed
  - Final accounting rules and depreciation assumptions
  - Disposal evidence requirements and retention rules

## 7. Workflow, security, and auditability

- Capability area
  - Configurable approval workflows, permission-based access, comments, reasoning, and audit trails
- Proposed module
  - `security` / `governance`
- Planned implementation phase
  - Phase 3
- Principal acceptance checks
  - Invalid transitions are rejected by policy and workflow rules
  - Role and permission checks enforce authorised actions
  - Approval and rejection history are recorded with timestamps and reasons
- Additional detail needed
  - Exact approval hierarchy and delegation model
  - Role model and scope boundaries by site, department, or asset category

## 8. Reporting and integration

- Capability area
  - Inventory, lifecycle, maintenance, audit, EOL, disposal, dashboards, exports, and external integrations
- Proposed module
  - `reporting` and `integrations`
- Planned implementation phase
  - Phase 6
- Principal acceptance checks
  - Operational reports reflect persisted transactional data rather than manual assumptions
  - External integration boundaries remain versioned and decoupled from lifecycle logic
  - Dashboard and export generation remains consistent with source-of-truth data
- Additional detail needed
  - Which external systems will be integrated first and in what order
  - Data-sync strategy for ERP, HRMS, ITSM, CMDB, and identity providers

## 9. High-level requirement priorities

The most urgent requirements to confirm before implementation begin in earnest are:

1. Authentication and authorization enforcement for company/org scope
2. Asset taxonomy and numbering conventions
3. AuthN/AuthZ strategy and enterprise identity integration
4. Policy definition model for workflows and approvals
5. Accounting and depreciation assumptions
6. Evidence, retention, and document storage rules

## 10. Requirements that need more detail before reliable implementation

The following requirements are important but currently too open to implement reliably without stakeholder clarification:

- final organisation and asset taxonomy scope
- exact workflow and approval authority model
- disposal and closure evidence expectations
- exact document storage and retention approach
- financial policy assumptions for depreciation and EOL decisions
- external integration priorities and interfaces

These items should be treated as open questions until clarified, not as assumptions that are considered final business requirements.

## 11. Phase 1 verified scope

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Company-scoped organisation data | Company, department, site, location, cost-centre, category CRUD and scoped relationships | Backend organisation/asset pytest coverage |
| Asset registry | Create, update, list, search, filter, pagination, category and organisation references | Backend pytest and API/UI smoke flows |
| Asset numbering | Category format precedence, shared atomic company sequence, unique numbers, occupied-candidate skipping | Regression tests, including same prefixes and manual identifiers; PostgreSQL concurrency test |
| Department usage and history | Effective-dated usage relationships and asset field/event history | Backend pytest and live UI/API flow |
| Company authorization | Not implemented; company path scopes data only | Explicit limitation; must be addressed before production use |
