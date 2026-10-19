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
  - Future external identity integration and any authorization granularity below company scope
  - Whether custom fields will be category-scoped, organisation-scoped, or both
  - Employee/custodian and vendor master requirements
  - Status: foundation slice and local session/RBAC company enforcement implemented; custom fields and employee/vendor masters remain out of scope

## 2. Procurement and asset acquisition

- Capability area
  - Suppliers, purchase orders, receipt lines, discrepancy capture, and asset traceability
- Proposed module
  - `procurement`
- Delivery status
  - Multi-line purchase order support and line-level goods receipt workflow implemented; single PO supports multiple line items with distinct asset categories, dynamic calculation of authoritative totals, reopening/editing open POs, partial deliveries per line, and remaining quantity enforcement; requisitions, quotations, approval routing, and formal inspections remain deferred
- Principal acceptance checks
  - Company-scoped suppliers, multi-line purchase orders, and line items can be created, read, and edited while open
  - Multiple asset categories can be configured in the same purchase order
  - Authoritative PO totals (total quantity, subtotal, discount, tax, final amount) and line totals are validated and calculated with decimal safety
  - Partial receipts against individual PO lines and rejected quantities/discrepancy notes are retained
  - Accepted received quantities create in-stock assets atomically, with receipt-line traceability
  - Over-receipt and cross-company supplier/category references are rejected
- Additional detail needed
  - Approval threshold model for procurement
  - Whether procurement is enterprise-wide or limited to certain asset classes
  - Multi-currency, tax, freight allocation, replacement handling for rejected units, and approval workflow policy

## 3. Asset registry and deployment

- Capability area
  - Asset master, serial numbers, status, assignment, custody history, deployment, transfers, and locations
- Proposed module
  - `assets`
- Planned implementation phase
  - Phase 1 registry and Phase 3 assignment lifecycle
- Principal acceptance checks
  - Asset master records are unique, complete, and linked to organisation metadata
  - Custody and assignment changes are recorded with traceable history
  - Assets can be transferred or re-assigned without losing lifecycle context
- Additional detail needed
  - Final asset-type taxonomy
  - Barcode/QR scanning requirements and supported device flows
  - Status: basic registry, numbering, search/filter, department usage, history, assignment, handover, return, and transfer are implemented in Phase 3

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
  - Phase 2 foundation; configurable lifecycle approvals remain deferred
- Principal acceptance checks
  - Invalid transitions are rejected by policy and workflow rules
  - Role and permission checks enforce authorised actions on protected company and asset APIs
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
| Company authorization | Local session, persisted role/permission, membership scope, and API permission checks | Backend security tests include unauthenticated access, cross-company scope, restricted roles, and immediate membership revocation |

## 12. Phase 2 security foundation

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Account lifecycle | Argon2id local accounts, interactive first administrator bootstrap, one-time company invitations, invitation acceptance, login throttling, session revocation | Backend auth/invitation tests and disposable PostgreSQL suite |
| Session and browser protections | Hashed opaque server-side sessions, HttpOnly cookie, session-bound CSRF cookie/header, Angular login/logout/guard/interceptor | Angular production Docker build and 4 Angular unit tests passed under Node.js 22.22.3 with headless Chromium |
| Company-scoped RBAC | Persistent system/company roles, permission checks on existing protected APIs, role-grant subset restriction, immediate membership/status checks | PostgreSQL-backed security API tests; cross-company paths return not found |
| Audit integrity | Same-transaction ORM audit capture, explicit security events, safe field allowlist, ORM append-only guard and PostgreSQL update/delete/truncate triggers | Atomicity/ORM immutability tests and direct PostgreSQL trigger checks |
| Migration preservation | Additive migrations after `b7b05462a977`; no prior migration changed | Isolated PostgreSQL upgrade and existing Compose upgrade completed to `20261014_audit_truncate`; company/category/asset counts were unchanged |

## 13. Phase 3 assignment lifecycle

| Requirement | Implemented behavior and verification |
| --- | --- |
| Custodian record | Use active company users/memberships; do not create an employee/HR master without an existing employee model |
| Assignment | Only `in_stock` assets; one active assignment; recipient, effective date, responsible department, physical location, notes, and reference |
| Handover | Record a single handover with date, condition, included items, acknowledgement, and notes; retain the record |
| Return | Close the active record as `returned`; require a return date and explicit next asset status (`in_stock` or `maintenance`); retain condition and notes/issues when provided |
| Transfer | End the previous record as `transferred` and create the next assignment atomically; retain both custodians and capture reason and destination |
| Isolation and concurrency | Enforce the company scope for asset, recipient, department, and location; use asset row locking and a partial unique active-assignment index |
| Authorization and audit | Gate all lifecycle writes with `asset.assignment.manage`; persist explicit audit and asset-history events in the same transaction |
| UI workflow | Open asset details in the existing registry to view the current assignment and history and perform authorized lifecycle actions | Angular production Docker build and 9 Angular tests passed |

## 14. Bounded procurement and receiving workflow

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Supplier master | Company-scoped supplier codes/names and optional contact data; backend read/write permissions | PostgreSQL API tests cover create/read and role restrictions |
| Purchase orders | Company-scoped order headers and multiple categorized quantity/cost lines; order number unique within company | PostgreSQL API tests create and read orders |
| Goods receipts | Multiple partial receipt records, received/rejected quantities, delivery references, and discrepancy notes | PostgreSQL tests cover successful partial receipt, rejection details, and over-receipt rejection |
| Asset registration and traceability | Each accepted unit is created as an `in_stock` asset in the receipt transaction; asset retains receipt-line link, supplier code, delivery reference, acquisition date/cost, and optional serial | PostgreSQL test confirms linked asset and audit records; transaction rollback is covered by rejection test |
| Isolation and concurrency | Composite company foreign keys, company-scoped APIs, permission checks, order-row locking, and unique company receipt/order identifiers | Disposable PostgreSQL migration and API/concurrency tests |
| Angular workflow | Permission-gated Procurement tab with supplier, single-line order, receipt forms, validation, loading/errors, confirmation, and persisted receipt/asset history | 15 Angular tests passed; clean production Docker build |
| Deferred procurement scope | Requisitions, quotations, approvals, multi-currency/tax, attachment storage, and supplier portal are not implemented | Explicitly out of current sprint scope |

## 15. Warranty, AMC, and maintenance workflow

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Warranty / AMC record | Company-scoped asset service-contract history with provider/supplier, reference, coverage, support contact, dates, notes, active/cancelled state; vendor supplier can be inferred from asset procurement reference | PostgreSQL API tests cover supplier linking, reads, date validation, and derived coverage status |
| Coverage status | `upcoming`, `active`, `expiring_soon` (within 30 days inclusive), `expired`, or `cancelled`, calculated at read time | Date-boundary tests |
| Maintenance request | Record asset, authenticated requester, optional active company-member assignee, issue, priority, and reported date | PostgreSQL API test covers create and history retrieval |
| Service workflow | Enforce `open` → `in_progress` → `resolved` → `closed`; resolution requires dated completion and resolution notes; closed records are immutable | PostgreSQL tests cover accepted and rejected transitions, completion data, and audit retention |
| Isolation / integrity | Active-company authorization, company-scoped asset and supplier checks, FK/check/unique constraints, row-locked service-contract cancellation and maintenance updates | PostgreSQL-backed API tests cover cross-company asset/assignee checks and database constraints |
| Permissions / audit | `maintenance.read` and `maintenance.manage`; system administrators, company administrators, asset managers, and IT support can manage; auditors/read-only can read. Contracts and requests create same-transaction audit events | PostgreSQL tests verify read-only denial and service audit events |
| Angular workflow | Permission-gated Warranty & Maintenance tab, asset-level contracts and maintenance-history link, request filters/details, work/resolution entry, loading/empty/error feedback and confirmation on status/contract cancellation | Angular unit tests and production build (run for current delivery; results recorded in project status) |
| Deferred maintenance scope | Preventive schedules, SLA escalation/reminders, external providers, and downtime analytics are not included | Explicitly deferred for the October 17 demo |

## 16. Executive dashboard and operational reports (Phase 5)

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Executive Dashboard | Responsive overview with KPI summary cards (total assets, in-stock/assigned, 30-day contract expirations, open/in-progress maintenance, PO/GRN volume), status breakdown, category distribution, site/department allocation, upcoming expirations list, and recent audit activity timeline | Backend PostgreSQL test suite (`test_reports.py`), empty company genuine-zero checks, and live UI verification |
| Asset register report | Filterable inventory table with asset number, name, category, status, site, department, custodian, acquisition date/cost, and active warranty/AMC coverage details | SQLite/PostgreSQL tests for search, status/category/site/dept filters; Angular unit test |
| Asset allocation report | Tracks all currently assigned assets (`status = 'assigned'`) with custodian, responsible department, site, location, and assignment date; supports Phase 3 assignments and legacy assigned assets | Backend test verifies assigned asset retrieval; Angular unit test |
| Warranty & AMC expiry report | Comprehensive contract list with contract type, asset reference, provider, start/end dates, days remaining, and computed coverage status | Backend date-boundary tests (exact 30d boundary, 31d exclusion, expired/cancelled exclusion); Angular unit test |
| Maintenance request report | Service requests with reference, asset number, priority, status, requester, assignee, reported date, completion date, repair cost, and diagnosis/resolution notes | Backend filter and aggregation tests; Angular unit test |
| Procurement & receiving report | Purchase order tracking with supplier, order number, status, ordered/received/rejected/outstanding quantities, and linked goods receipt notes | Backend tests verify line calculations and GRN references; Angular unit test |
| CSV export & client interactions | Client-side RFC-4180 CSV export for all operational reports, loading/empty/error states, retry controls, and tenant isolation | 21 Angular unit tests passed in headless Chromium; live container verification |
