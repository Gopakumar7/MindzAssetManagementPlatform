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
- Delivery status
  - Phase 4 Physical Asset Verification fully implemented and verified against PostgreSQL.
  - Features: Verification campaigns with draft -> in_progress -> under_review -> completed / cancelled lifecycle, category and location scoping, frozen snapshot of expected assets upon campaign start, physical observations recording, duplicate observation prevention, automated discrepancy detection (missing, location mismatch, custodian mismatch, condition degradation), discrepancy resolution workflow (`update_master`, `keep_as_is`, `mark_missing`, `investigate`, `dismiss`) with mandatory resolution notes and conditional master asset updating, in-field unregistered asset discovery and duplicate-safe promotion to inventory, campaign KPI summaries, operational reports (`verification-campaigns`, `verification-discrepancies`) with RFC-4180 CSV export, RBAC (`verification.read`, `verification.manage`), and audit event logging.
- Principal acceptance checks
  - Physical verification campaigns freeze an immutable expected asset snapshot upon start.
  - Physical observations record presence, actual location, actual custodian, condition, and tag references; duplicate observations for the same asset are rejected with HTTP 409.
  - Discrepancies are automatically generated and preserved independently without modifying master asset records.
  - Discrepancies can be resolved with mandatory resolution notes; master records update only upon `update_master`.
  - Discovered unregistered assets can be recorded and registered into master inventory with duplicate protection (HTTP 409).
  - Campaign summary KPIs, campaign reports, and discrepancy reports export cleanly to RFC-4180 CSV.
  - All operations enforce company multi-tenant isolation, RBAC permissions, and transactional audit trails.
- Additional detail needed
  - Barcode and QR scanner hardware integration and mobile camera scanning flows (future enhancement).

## 6. Finance and end-of-life management

- Capability area
  - Acquisition cost, capitalised cost, straight-line depreciation, useful life, prospective adjustments, EOL review, retirement, disposal cutoff, gain/loss calculation, and historical integrity
- Proposed module
  - `finance`
- Delivery status
  - Phase 5 Asset Financial Lifecycle Management fully implemented and verified against PostgreSQL and Angular test suites.
  - Features: Straight-line monthly depreciation engine using Python `Decimal` and `ROUND_HALF_UP`, schedule projection, single-asset and batch row-level locked postings, unique constraint `(company_id, asset_id, period)` duplicate protection, historical integrity enforcement (direct mutation blocked after entries posted with HTTP 409), prospective financial adjustments (`/financial/adjust`), asset disposal workflow with active assignment prevention and post-disposal depreciation cutoff, authoritative gain/loss calculation (`sale_proceeds - net_book_value_at_disposal`), executive financial dashboard KPI summary card, operational reports (`asset-depreciation`, `asset-disposals`) with RFC-4180 CSV export, RBAC permissions (`finance.read`, `finance.manage`), multi-tenant company isolation, and transactional audit trails.
- Principal acceptance checks
  - Straight-line depreciation calculation and schedule generation accurately respect capitalised cost, residual value, useful life in months, and start date.
  - Final month of useful life cleanly absorbs fractional rounding residuals without dipping below residual value.
  - Concurrency control via row locks and database unique constraints prevents duplicate postings under parallel load.
  - Historical financial profile values cannot be directly mutated once entries are posted (HTTP 409).
  - Prospective adjustment updates remaining useful life and residual value from the latest posted entry forward.
  - Assets with an active custodian cannot be disposed until returned or transferred.
  - Disposing an asset locks authoritative net book value and computes gain/loss against proceeds.
  - Depreciation cannot be posted for periods after an asset's disposal date (HTTP 400).
  - Financial dashboard metrics and reports export accurately to RFC-4180 compliant CSV.
  - Company isolation, RBAC (`finance.read`, `finance.manage`), and audit logging are enforced across all financial endpoints.
- Additional detail needed
  - Country-specific statutory tax depreciation rules and multi-currency exchange rate feeds (deferred as post-MVP enhancements).

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

## 17. Physical asset verification (Phase 4)

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Campaign lifecycle | Multi-status state machine (`draft` -> `in_progress` -> `under_review` -> `completed` / `cancelled`); scope criteria frozen upon start | Backend pytest suite (`test_verification.py`), state transition guards |
| Physical observations | Verifiers record found/not-found, actual location, actual custodian, condition, tag, and remarks; duplicate observation rejection | Backend test verifies observation immutability and duplicate rejection |
| Discrepancy detection & resolution | Auto-generated discrepancies for missing, location, custodian, and condition mismatches; resolution actions (`update_master`, `keep_as_is`, `mark_missing`, `investigate`, `dismiss`) with mandatory notes; updates master records only on explicit approval | Backend tests verify all 4 discrepancy types and master asset updating |
| In-field unregistered discovery | Discover and record unlisted assets; register into master inventory with company numbering rules | Backend test verifies promotion to master asset and duplicate registration guard |
| Reporting & export | Campaign summary metrics, verification reports, and RFC-4180 CSV export with formula injection sanitization | 11 Angular unit tests passed in headless Chromium |

## 18. Asset financial lifecycle management (Phase 5)

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Asset financial profile | Capitalised cost, currency, straight-line depreciation method, useful life in months, residual value, depreciation start date, accumulated depreciation, net book value, and financial status | PostgreSQL API tests verify boundary conditions and rounding rules |
| Depreciation calculation & posting | Authoritative monthly straight-line engine with Python `Decimal` and `ROUND_HALF_UP`; full-month convention; row-level locking for single-asset and batch postings; unique constraint on `(company_id, asset_id, period)` | Multi-threaded PostgreSQL concurrency integration test verifying 0 duplicate postings |
| Historical integrity & prospective adjustments | Direct mutation of historical capitalised cost/life blocked once entries exist (HTTP 409); authorised prospective adjustments recompute forward while retaining past entries | Backend integration test verifies historical preservation and recomputed projections |
| Disposal & cutoff | Disposal workflow recording date, method, reason, sale proceeds, and notes; transactional NBV and gain/loss calculation; custodian return guard; post-disposal depreciation blocked | Backend test verifies active assignment guard, cutoff enforcement, and gain/loss |
| Financial dashboard & reports | Executive KPI metrics (capitalised cost, accumulated depreciation, current NBV, EOL count, fully depreciated count, gain/loss); filterable depreciation and disposal reports with CSV export | 8 Angular unit tests; backend pytest integration test |

## 19. Asset lifecycle alerts and action centre (Phase 6)

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Rule evaluation engine | Company-scoped backend service evaluating 8 lifecycle rules: warranty expiry, AMC expiry, maintenance overdue SLAs, verification discrepancies, campaign deadlines, fully depreciated in-use assets, approaching EOL, and overdue PO deliveries | Backend pytest suite (`test_alerts.py`), rule threshold tests |
| Missing date handling | Adheres strictly to persisted data; assignment return alerts omitted as assignments lack artificial expected return dates | Code audit and domain model inspection |
| Idempotency & uniqueness | Partial unique index on active alerts `(company_id, alert_type, entity_type, entity_id)` where `status IN ('open', 'acknowledged')` | Idempotency integration tests with repetitive sync operations |
| Auto-resolution & anti-resurrection | Auto-resolves active alerts when source conditions clear (`source_resolved`); operator-resolved and dismissed alerts are remembered to prevent resurrection | Backend lifecycle test verifies auto-resolution and anti-resurrection |
| Action Centre workspace UI | Dedicated tab with critical/warning badge, KPI cards (`open`, `acknowledged`, `resolved`), multi-field filter bar (status, severity, type, search), and direct entity routing | 10 Angular unit tests passed in headless Chromium |
| Operational action workflows | Modals for Acknowledge (with notes), Assign (to team member), Resolve (with mandatory reason and notes), and Dismiss (with acceptance reason) | Angular unit tests cover all 4 modal submission workflows |
| RBAC & company isolation | Multi-tenant company isolation; permissions `alerts.read` and `alerts.manage` mapped into existing roles; unauthorized cross-company access returns 404 | Multi-tenant isolation test verifying cross-company 404 and role gating |

## 20. Scheduled automation and durable notifications (Phase 7)

| Requirement | Implemented behavior | Verification |
| --- | --- | --- |
| Configurable scheduled evaluation | Periodic evaluation configured via `ALERT_SCHEDULE_ENABLED`, `ALERT_SCHEDULE_INTERVAL_SECONDS`, and `ALERT_SCHEDULE_STARTUP_DELAY_SECONDS` within FastAPI application lifespan | Backend test verifying configuration defaults, disable flag, and startup delay |
| Multi-instance mutual exclusion | PostgreSQL advisory lock (`SCHEDULER_ADVISORY_LOCK_ID = 882349172635412984`) held on a dedicated engine connection and released in `finally` block upon completion, failure, or cancellation | Pytest integration test verifying lock contention blocks concurrent runs and releases lock properly |
| Execution tracking & heartbeat lease recovery | Execution history recorded in `scheduled_job_executions` with start/end timestamps, duration, company counts, alert counts, node ID, and sanitized errors; orphaned or crashed runs recovered using heartbeat lease (`ALERT_JOB_LEASE_EXPIRY_SECONDS = 300`, `ALERT_JOB_HEARTBEAT_INTERVAL_SECONDS = 60`) | Concurrency test simulating crashed execution and confirming recovery of expired lease; `GET /companies/{company_id}/alerts/last-job` endpoint test |
| Durable notification persistence | Multi-tenant in-app notification records stored in `notifications` table; delivery attempts and statuses tracked in `notification_deliveries` table | Database migration at head; ORM model tests; zero schema drift via `alembic check` |
| Idempotency & anti-resurrection | Deterministic `dedup_key` unique constraint prevents duplicate notifications and delivery attempts across repeated evaluations, even after reading or archiving | Deduplication test confirming duplicate events are ignored and reading does not re-trigger notifications |
| Notification triggers & decoupling | Triggers on newly generated critical alerts, alert assignments, severity escalations, and scheduler job failures; notification and delivery failures are isolated and never roll back alert synchronization | Pytest tests verifying critical alert notifications, assignment notifications, failure notifications, and error isolation |
| Delivery channels & email capture | Pluggable delivery channels (`capture`, `console`, `smtp`); `capture` channel stores emails in an in-memory test mailbox (`CapturedEmailMailbox`) with max 3 retry attempts | Delivery test verifying captured recipient, subject, body, and status tracking |
| RBAC, user isolation & decoupled read state | Notifications scoped to recipients (`assigned_user_id` or company administrators for unassigned alerts; system admins for job failures); permissions `notifications.read` and `notifications.manage`; marking notification read is strictly decoupled from alert lifecycle | Pytest testing cross-user isolation and confirming read action leaves alert unresolved; permission checks |
| Action Centre status banner & UI feed | Live header notification bell with unread badge counter, floating flyout feed panel (filter unread/all, relative timestamps, severity stripes, mark read, mark all read, direct link navigation), and Action Centre scheduled automation status banner showing last run metrics | 8 Angular unit tests passed in headless Chromium; clean production Docker build |

