# Project Status

## Current delivery

**Phase 0 technical foundation, Phase 1 organisation/asset registry, Phase 2 local security foundation, Phase 3 asset assignment lifecycle, multi-line purchase orders and line-item receiving, warranty/AMC/maintenance requests, Phase 4 physical asset verification campaigns, and Phase 5 executive dashboard and operational reports: implemented.** Verification status and remaining integration limitations are recorded below.

Workspace: `c:\Users\krgop\Documents\Projects\MindzAssetManagementPlatform`

## Physical asset verification (2026-10-19)

- Implemented a complete Physical Asset Verification module enabling organisations to verify the physical existence, location, custodian, and condition of registered assets through controlled campaigns.
- Campaign management and lifecycle:
  - Models added: `VerificationCampaign`, `VerificationExpectedAsset`, `VerificationObservation`, `VerificationDiscrepancy`, and `VerificationUnregisteredAsset`.
  - Campaign reference, name, description, verification period (`start_date`, `end_date`), and multi-category / multi-location scoping.
  - Lifecycle state machine: `draft` -> `in_progress` -> `under_review` -> `completed` (with `cancelled` permitted from non-completed states, and reopening permitted from review).
  - Campaign start locks scope and captures a frozen snapshot of expected assets matching the campaign criteria, preventing scope manipulation after verification begins.
- Physical observations and discrepancy detection:
  - Verifiers record observed presence (`found`, `not_found`), actual location, actual custodian, condition (`excellent`, `good`, `fair`, `poor`, `damaged`), tag/barcode reference, and remarks.
  - Duplicate observation protection prevents multiple conflicting entries for the same expected asset (HTTP 409).
  - Automatic discrepancy generation for missing assets, location mismatches, custodian mismatches, and condition degradations without modifying master asset records.
- Discrepancy resolution workflow:
  - Controlled resolution actions: `update_master`, `keep_as_is`, `mark_missing`, `investigate`, `dismiss`.
  - Resolution notes are strictly mandatory.
  - Asset master records (location, custodian, condition, status) are updated ONLY upon explicit `update_master` resolution action.
- In-field unregistered asset discovery:
  - Verifiers can record previously unlisted physical assets discovered in the field (serial number, description, category, location, custodian, condition, remarks).
  - Controlled registration action automatically promotes discovered assets into master asset inventory using company asset numbering rules, linking the asset to the campaign and preventing duplicate registrations (HTTP 409).
- Reports, dashboard metrics, and CSV exports:
  - Real-time campaign summary KPI metrics: expected count, verified count, unverified count, missing count, completion percentage, discrepancies by type, and unregistered asset count.
  - Verification Campaigns report (`GET /reports/verification-campaigns`) with CSV export (`format=csv`).
  - Verification Discrepancies report (`GET /reports/verification-discrepancies`) with CSV export (`format=csv`) and RFC-4180 formula injection sanitization.
- RBAC, company multi-tenancy & audit logging:
  - Added permissions `verification.read` and `verification.manage` seeded into `company_admin`, `asset_manager`, `technician`, `auditor`, and `read_only` roles.
  - Strict company multi-tenancy with composite foreign keys and database check constraints.
  - Comprehensive audit event logging (`verification_campaign_created`, `verification_campaign_started`, `verification_observation_recorded`, `verification_discrepancy_resolved`, `verification_unregistered_asset_recorded`, `verification_unregistered_asset_registered`, etc.).
- Verification & Test Coverage:
  - PostgreSQL backend pytest suite: **69 passed, 0 failed, 1 warning** in 71.71s (5 dedicated verification tests covering lifecycle transitions, snapshot freezing, observation duplicate protection, all discrepancy types, master asset updating on resolution, unregistered asset registration, reports, and RBAC / multi-tenant isolation).
  - Frontend Angular Karma suite: **61 passed, 0 failed** (11 dedicated verification tests covering navigation, permission gating, campaign creation/selection, status transitions, observation recording, discrepancy resolution, unregistered asset discovery/registration, and report generation/CSV export).
  - Alembic migration `20261019_physical_asset_verification.py` verified with `alembic upgrade head`, `alembic downgrade -1`, and `alembic check` (**zero schema drift**).
  - Production build: `ng build` succeeded cleanly with **0 errors**.

## Multi-line purchase orders and line-item goods receipt (2026-10-19)

- Enhanced procurement module to support multiple line items per Purchase Order (PO), supporting distinct asset categories per line item.
- Authoritative backend monetary calculations:
  - Validated line item fields: description, category ID, positive quantity, non-negative unit cost, optional discount, tax rate, and tax amount.
  - Authoritative calculation of `line_subtotal` and `line_total` per line item, and aggregate `total_quantity`, `subtotal`, `total_discount`, `total_tax`, and `total_amount` for the purchase order using decimal-safe arithmetic.
  - Endpoints added: `GET /companies/{company_id}/purchase-orders/{purchase_order_id}` and `PUT` / `PATCH` update endpoints for open purchase orders.
  - Modification guards: only open purchase orders without existing goods receipts may be edited. Atomic line item update with `purchase_order_updated` audit logging.
- Line-item goods receipt workflow:
  - Supported partial and multi-line receipts against individual PO lines with remaining quantity tracking (`quantity_ordered - quantity_received`).
  - Strict prevention of over-receipt per line item (HTTP 422).
  - Purchase order status updates atomically from `open` to `partially_received` and only transitions to `received` once all lines are fully received.
  - Preserved links between individual goods receipt lines, purchase order lines, and generated in-stock asset records with vendor references and serial numbers.
- Angular user experience:
  - Dynamic multi-line purchase order form allowing users to add, edit, and remove line items before saving.
  - Real-time client-side calculation of line totals and purchase order summary card (Total Quantity, Subtotal, Total Discount, Total Tax, and Order Total).
  - Support for reopening existing open POs into edit mode with full line item preservation, cancel edit action, and in-place updates.
  - Goods receipt dropdown automatically selects remaining quantity for the chosen line item and prevents over-receipt submission.
- Verification & Test Coverage:
  - Backend pytest suite: **60 passed, 3 skipped** (PostgreSQL concurrency tests skip on SQLite). All 6 procurement tests passing, covering multi-line creation with 3 different categories, authoritative totals, line additions/removals/edits, partial deliveries across multiple receipts, remaining quantities, and over-receipt rejection.
  - Frontend Angular Karma suite: **50 passed, 0 failed** (increased from 42 tests), covering line additions, deletions, line item validation errors, live calculated totals, multi-category creation, reopening open POs for edit, and line-level receipt auto-fill and over-receipt prevention.
  - Production build: `ng build` succeeded cleanly with 0 errors.

## Executive dashboard and operational reports (2026-10-15)

- Implemented a responsive Executive Dashboard and prioritized operational reports using real, authenticated APIs, strict company-scoped access control, explicit loading/empty/error states, genuine zeroes without fallback falsification, and client-side CSV exports.
- Executive Dashboard metrics:
  - Total registered assets, count by status (in-stock, assigned, maintenance, disposed), count by category, and distribution by site and department.
  - Active warranty and AMC service contracts expiring within 30 days inclusive (`today <= end_date <= today + 30 days`). Expired or cancelled contracts are strictly excluded.
  - Open and in-progress maintenance request breakdown.
  - Procurement purchase order status summary (draft, ordered, partially_received, received, cancelled) and goods receipt volume (total receipts, items received, items rejected).
  - Recent company activity timeline derived directly from `AuditLog` entries.
- Five prioritized operational reports:
  1. Asset register: asset number, name, category, status, site, department, custodian, acquisition date/cost, and active warranty/AMC coverage details. Supports search and filters by status, category, site, and department.
  2. Asset allocation: currently assigned assets with custodian, department, site, location, and assignment date. Supports legacy assigned assets and Phase 3 assignment records.
  3. Warranty and AMC expiry: contract type, asset reference, provider/supplier, start date, end date, computed coverage status, and days remaining.
  4. Maintenance requests: request reference, asset number, priority, status, requester, support assignee, reported date, completion date, cost, and resolution diagnosis/notes.
  5. Procurement and receiving: supplier, PO number, status, ordered quantity, received quantity, rejected quantity, outstanding quantity, and linked goods receipt notes.
- Backend API endpoints added under `/api/v1/companies/{company_id}`:
  - `GET /dashboard` (permission: `asset.read`)
  - `GET /reports/asset-register` (permission: `asset.read`)
  - `GET /reports/asset-allocation` (permission: `asset.read`)
  - `GET /reports/warranty-expiry` (permission: `maintenance.read`)
  - `GET /reports/maintenance` (permission: `maintenance.read`)
  - `GET /reports/procurement` (permission: `procurement.read`)
- Backend test suite:
  - `backend/tests/test_reports.py` added with 14 comprehensive tests.
  - Standard backend suite (SQLite): **39 passed, 3 skipped** (PostgreSQL-specific concurrency and table trigger tests skipped as expected).
  - PostgreSQL test suite (`mindzen_test`): **42 passed, 0 skipped, 0 failed** in 18.23s.
  - Verification includes genuine zero handling for empty companies, exact 30-day date boundary logic (testing 0d, 15d, exact 30d boundary, 31d exclusion, past-expired exclusion, cancelled exclusion), cross-company tenant isolation, role authorization checks (`asset.read`, `maintenance.read`, `procurement.read`), and report filtering.
- Frontend test suite & production build:
  - Added unit test coverage for dashboard metrics, operational reports loading/switching/filtering, CSV export generation, and error recovery in `frontend/src/app/components/registry/registry.component.spec.ts`.
  - Headless Chromium containerized Karma test suite: **21 passed, 0 failed**.
  - Production Angular bundle build: **passed cleanly** under Node.js 22.22.3 within initial bundle budgets (`538.72 kB` initial total, `125.50 kB` estimated transfer).
- Deployment and demo data preservation:
  - Rebuilt and restarted `mindzen-backend` and `mindzen-frontend` containers in Docker Compose.
  - Verified `alembic check`: **passed** with zero schema drift against deployed PostgreSQL.
  - Health checks `/`, `/status`, `/api/v1/health`, and `/api/v1/health/ready` returned HTTP 200.
  - Preserved PostgreSQL volume `postgres_data` and all existing demo data: 1 company (`MINDZEN-DEMO`), 11 categories, 5 assets (`MZ-000001` through `MZ-000005`), assignment history, supplier, purchase order, goods receipt, service contract, maintenance request, and audit logs.
  - Live API verification confirmed correct live metrics: 5 total assets (4 in-stock, 1 assigned), 0 expiring contracts within 30 days (genuine zero), 0 open maintenance requests (1 closed), 1 PO (received), 1 GRN (1 received), and 10 recent audit entries.

## Warranty, AMC, and maintenance (2026-10-15)

- Added company-scoped `AssetServiceContract` and `MaintenanceRequest` records in additive Alembic revision `20261017_service_management`. Existing `assets.warranty_start` / `warranty_end` fields remain intact.
- Contracts retain warranty/AMC type, service provider/supplier, reference, dates, coverage, contact and notes. A missing supplier is inferred from a matching active procurement supplier code on the asset. Coverage is calculated on read (`upcoming`, `active`, `expiring_soon` within 30 days inclusive, `expired`, or `cancelled`); contracts can be cancelled but not deleted.
- Maintenance requests record asset, requester, optional active company support assignee, priority, issue, diagnosis, work performed, resolution, completion date and cost. The validated path is `open` → `in_progress` → `resolved` → `closed`; resolving requires completion date and resolution notes, and closed requests are immutable.
- Added `/api/v1/companies/{company_id}/assets/{asset_id}/service-contracts`, `/service-contracts/{contract_id}/cancel`, `/maintenance-users`, and `/maintenance-requests` read/create/update APIs. `maintenance.read` and `maintenance.manage` backend permissions are seeded and migrated to deployed roles. Asset, supplier and assignee scope is checked in the API and reinforced by database constraints; mutations and audit events share a transaction.
- Added asset-detail contract coverage/history and a permission-gated **Warranty & Maintenance** workspace with asset/status filters, request creation/details, support assignment, lifecycle updates, work/cost fields and confirmation for significant actions.
- Backend suite against isolated PostgreSQL: **33 passed**. Disposable and live PostgreSQL migration checks: **passed**, with no schema drift. Angular headless Chromium tests: **17 passed**. Backend and Angular production Docker images built successfully.
- Deployed Alembic revision `20261017_service_management` to the existing Compose database without removing or resetting `postgres_data`; all three services are healthy. `/`, `/status`, `/api/v1/health`, and `/api/v1/health/ready` returned HTTP 200.
- Completed the live browser workflow against `MINDZEN-DEMO` and existing asset `MZ-000005`: recorded AMC `DEMO-AMC-PHASE3-20261015-01` (supplier auto-linked from procurement), created request `DEMO-MNT-PHASE3-20261015-01`, and advanced it through `open` → `in_progress` → `resolved` → `closed`. The asset detail/history view shows the retained contract and request; the request retains completion date and resolution notes. Eight related audit events (contract create, request create, and three audited request updates) are persisted.
- Live counts before migration/workflow were **1 company / 11 categories / 5 assets / 2 assignments / 39 audit events**. After the demo they are **1 / 11 / 5 / 2 / 47**, plus **1 service contract / 1 maintenance request**. Supplier, purchase-order, and goods-receipt counts remain **1 / 1 / 1**. Existing company, category, asset, assignment, procurement and audit records remain intact.
- The existing demo company has no active company-member support user available in the support selector, so the verified request remained unassigned. Support assignment is supported when an active company member is available.
- Deferred: preventive maintenance schedules, SLA escalation/reminders, external service integrations, and downtime analytics. This maintenance slice uses the existing company user/membership model; no employee master was added.

## Procurement sprint (2026-10-16)

- Implemented company-scoped supplier, purchase order, purchase-order line, goods receipt, and receipt-line records.
- A goods receipt records received/rejected quantities and discrepancies. Accepted units create in-stock assets with receipt-line traceability, supplier and delivery references, acquisition date/cost, optional serial numbers, asset history, and audit events in one transaction.
- Added read/manage procurement permissions, including additive grants to deployed administrator/asset-manager roles and read-only/auditor roles. PostgreSQL row locks serialize receipts per order; company-scoped composite foreign keys and unique receipt/order identifiers protect relationships and duplicate writes.
- Added `/api/v1/companies/{company_id}/suppliers`, `/purchase-orders`, `/goods-receipts`, and purchase-order goods-receipt APIs. Added a permission-gated Procurement tab for supplier creation, a single-line order form, goods receipt entry, and order/receipt/asset history.
- Alembic revision `20261016_procurement` was applied to a clean disposable PostgreSQL database; `alembic check` reported no model/schema drift. Complete backend PostgreSQL suite: **30 passed** (including receipt over-receipt and concurrency coverage).
- Angular tests under Node.js 22.22.3 and headless Chromium: **15 passed**. A clean production Angular Docker build completed successfully.
- The updated backend and Angular application were deployed to the existing Compose stack without removing or resetting `postgres_data`. `/`, `/status`, `/api/v1/health`, and `/api/v1/health/ready` returned HTTP 200; all three services were healthy and Alembic was at `20261016_procurement`.
- Completed a live Procurement-tab workflow using the existing `MINDZEN-DEMO` company and normal application forms. Retained supplier `DEMO-SUP-SPRINT-20261016`, order `DEMO-PO-SPRINT-20261016-01`, receipt `DEMO-GRN-SPRINT-20261016-01`, and zero-cost in-stock asset `MZ-000005` (`DEMO-SPRINT-20261016-001`). The asset detail and database confirm its receipt, order, supplier, acquisition cost, and vendor reference.
- Live data before procurement was **1 company / 11 categories / 4 assets / 2 assignments / 35 audit events**; after the demonstration it was **1 / 11 / 5 / 2 / 39**. The receipt's `goods_received` audit event is retained. No existing company, category, asset, assignment, or audit record was deleted or reset.
- The current demo company has no active recipient available for a new assignment; the receipt-created asset is therefore verified as in stock, not assigned. The assignment lifecycle was separately demonstrated and documented above using `MZ-000004`.
- npm reported **6 high-severity development/test dependency advisories**; dependency changes were not included in this delivery.
- Limits: Angular order entry currently creates one line at a time, while the API/model support multiple lines. Requisitions, quotations, approvals, tax/currency accounting, attachments, replacement handling, and supplier portals remain deferred. Use a demo company and unique `DEMO-` identifiers for repeat runs; records are retained, not reset or deleted.

## Demo readiness (verified 2026-10-15)

- Repeated the full lifecycle in the running application using `MZ-000004`: assign, handover, transfer to another recipient and department, return, and inspect history. The asset is back to `in_stock` with no custodian. Both assignments and all four assignment audit entries remain persisted.
- Current demo baseline is the existing `MINDZEN-DEMO` company and `MZ-000004`; company/category/asset counts remain **1 / 11 / 4**. Two test recipient memberships were revoked after the run, without deleting user, assignment, or audit history. Re-invitation and non-destructive repeat steps are in the [setup guide](./setup.md).
- Improved the assignment panel's required-field labels and no-active-recipient guidance, and expanded previous assignment history to show persisted handover, transfer, return, acknowledgement, and issue details.
- Backend PostgreSQL tests: **26 passed**. Angular tests on Node.js 22.22.3 and headless Chromium: **11 passed**. Backend tests cover duplicate assignment, invalid transitions, company isolation, insufficient permissions, concurrency, and transaction rollback.
- Compose endpoints `/`, `/status`, and `/api/v1/health/ready` returned HTTP 200; backend and frontend containers were healthy. Alembic is at `20261015_assignment`; `alembic check` reported no model/schema drift.
- The optional data-derived overview was deferred; it is not needed for the registry-led demo. npm reported **6 high severity dependency advisories** during the frontend test install; dependency upgrades were not part of this stabilization pass.

## Phase 3 asset assignment lifecycle (verified 2026-10-15)

- The assignment lifecycle uses active company users as recipients; no separate employee/HR master exists or was added.
- Asset state transitions are `in_stock` → `assigned` → `in_stock` or `maintenance` on return. Assignment records remain `active` until closed as `returned` or `transferred`.
- Handover is a single dated record on an active assignment. Transfer closes the previous assignment and creates the next, with both recipient records, the reason, destination, and transfer handover preserved.
- Added company-scoped assignment, recipient, handover, return, transfer, and assignment-history APIs under `/api/v1/companies/{company_id}/assets/...`. Writes require `asset.assignment.manage`; active assignment uniqueness is enforced by a partial database index, and PostgreSQL mutations lock the asset row.
- Added assignment controls and history to the existing asset detail panel, including role-gated actions, typed clients, required form validation, loading/error messaging, and confirmation for assignment, transfer, and return.
- Alembic revision `20261015_assignment` adds `asset_assignments`, its composite company-scoped foreign keys and active-assignment index, seeds the assignment permission to system/company administrators and asset managers, and widens audit entity IDs for nested action paths.
- Backend tests on disposable PostgreSQL: **26 passed**, including assignment concurrency, migration-chain execution, and atomic rollback when audit persistence fails. Angular unit tests under Node.js 22.22.3 and headless Chromium: **11 passed**. Production Angular Docker image: **built successfully**.
- Compose backend was rebuilt and restarted without volume removal. Alembic is at `20261015_assignment`; health/readiness, `/`, and `/status` returned HTTP 200. Company/category/asset counts remained **1 / 11 / 4**.
- Authenticated live browser demonstration completed on existing asset **MZ-000004**: assignment, handover, transfer to a second recipient and Information Technology, return to `in_stock`, and review of both historical assignments and lifecycle audit events. Two clearly labeled, read-only test recipients were invited and activated through the normal flow, then their company memberships were revoked after the demonstration; no assignment history or existing demo data was removed.
- Deferred by design: employee master/HR integration, electronic signatures, workflow approvals, procurement, maintenance, physical verification, finance, disposal, reporting, and integrations.

## Containerized local application (verified 2026-10-15)

- Docker Compose now runs PostgreSQL, the FastAPI backend, and the Angular production build served by Nginx.
- The frontend is available at `http://localhost:4200/` (`4200:80`); `/status` also loads on direct navigation and refresh.
- Nginx forwards same-origin `/api/v1/` requests to the backend service on the internal Compose network. The browser does not need a backend hostname or URL.
- Only the frontend port is published to the host. Backend port `8000` and PostgreSQL port `5432` are internal to Compose.
- The frontend uses a Node build stage and a lightweight Nginx runtime stage; Node is absent from the final image. Fingerprinted JS/CSS assets use immutable caching and `index.html` is not cached.
- The root `.env.example` uses the Compose service name `postgres` for the database host. Compose migrations run before the backend starts. The existing `postgres_data` volume is retained.

### Container verification

- Frontend production Docker image: **built successfully** with `npm ci` and Angular production build.
- Compose services: **PostgreSQL healthy, backend healthy, frontend healthy**.
- `http://localhost:4200/`: **HTTP 200**; directly refreshed `/status`: **HTTP 200** and Angular app loaded.
- Hashed JS/CSS assets: **HTTP 200**, served with `public, max-age=31536000, immutable`; `index.html` has `no-cache, no-store, must-revalidate`.
- Same-origin `/api/v1/health` and `/api/v1/health/ready`: **passed**; readiness reported PostgreSQL available.
- Frontend-container request to `http://backend:8000/api/v1/health/ready`: **passed**.
- Published ports: frontend `4200:80`; backend and PostgreSQL: **none**.
- PostgreSQL restart without removing its volume: **passed**. The existing `MINDZEN-DEMO` company, 11 categories, and the same 4 assets remained available afterward.
- Alembic current revision: **`20261015_assignment (head)`**; `alembic check`: **passed**, no new upgrade operations detected.
- Backend tests on disposable PostgreSQL: **26 passed**, including the PostgreSQL concurrency test.
- Local Angular production build after a clean `npm ci`: **passed**.
- `npm install --package-lock-only` was required to correct a pre-existing mismatch between `package.json` and `package-lock.json`. npm reported 64 dependency audit findings (7 low, 16 moderate, 39 high, 2 critical); dependency upgrades were not part of this containerization task.

## Angular 22 upgrade and security reassessment (verified 2026-10-14)

- Migrated one major at a time with Angular CLI schematics: 18 → 19 → 20 → 21 → 22.2.2. Each intermediate version built and passed the frontend tests before advancing.
- Baseline versions were Angular framework 18.2.14, CLI/build 18.2.21, compiler CLI 18.2.14, TypeScript 5.5.4, RxJS 7.8.2, and Zone.js 0.14.10; the host toolchain was Node.js 20.17.0 with npm 11.0.0.
- Final framework, CLI, compiler, and build package versions are **22.2.2**; TypeScript is **6.0.3**, RxJS **7.8.2**, and Zone.js **0.15.1**.
- Migrated the workspace to Angular's `@angular/build` builders. The production Docker build uses Node.js **22.22.3** with npm **10.9.8**; its runtime stage remains Nginx-only. Angular 22 requires a compatible Node.js version; the machine's default Node.js 20.17.0 is below the minimum, so local Angular commands were run with a temporary Node.js 22.22.3 runtime.
- Replaced the obsolete root-component starter test with router-root and `/status` API behavior tests. The final frontend production build passed and **2 frontend tests passed**. The Angular 19, 20, and 21 production builds and tests also passed during staged migration.
- Backend tests: **8 passed, 1 skipped**. The PostgreSQL concurrency test requires `TEST_DATABASE_URL`.
- Final Docker image build passed. The running frontend returned HTTP 200 for `/`, `/status`, and fingerprinted assets; the rendered `/status` page reported the backend and database ready. Same-origin health and readiness requests succeeded through Nginx. The backend and PostgreSQL ports remain unpublished.
- Database verification found the existing `MINDZEN-DEMO` company, 11 categories, and 4 assets. Alembic remains at `b7b05462a977 (head)`; `alembic check` found no schema changes.

### Audit results

- Before the migration, `npm audit` reported **64 findings**: 7 low, 16 moderate, 39 high, and 2 critical. The Angular production dependency tree contained vulnerable Angular runtime packages.
- After the migration, the full audit reports **6 high, 0 critical**, with no low or moderate findings. `npm audit --omit=dev` reports **0 production vulnerabilities**.
- The remaining findings are development/test tooling only. They trace to `braces@3.0.3` (GHSA-vfj7-8cjw-p6xm), used by `chokidar@3.6.0` and `karma@6.4.4`, and propagate through Karma's Angular build/test peer and Jasmine adapters. No patched `braces` 3.x release is available; npm's suggested fixes downgrade Karma and its adapters across major versions and do not satisfy the Angular 22 builder's Karma peer requirements. Those changes were not applied. Angular documents migration of existing Karma projects to Vitest as experimental, so the existing supported Karma test runner was retained rather than changing test semantics as part of this security upgrade.
- npm reports an upstream deprecation warning for Angular's animations package, which is still pulled in through `@angular/platform-browser`; the application does not import or use its legacy animation APIs.

## Phase 2 authentication, authorization, and audit foundation (verified 2026-10-14)

- Added local user accounts with Argon2id password hashes, opaque eight-hour server-side sessions, HttpOnly session cookies, per-session CSRF protection, login throttling, and a one-time interactive system-administrator bootstrap. No default credentials or public registration path are provided.
- Added persistent system/company roles and permissions, company memberships, invitation acceptance, immediate membership/session revocation checks, and per-company authorization on the existing organization and asset APIs. Angular now has login, invitation acceptance, sign-out, current-user state, a route guard, a CSRF interceptor, and permission-aware registry/member controls. Authorized administrators manage invitations and memberships from the clearly labelled **Users & Access** workspace section after selecting a company. `/status` and operational health endpoints remain public.
- Added an append-only audit table and PostgreSQL update/delete trigger. Business-change audit records are written in the same transaction as the associated database mutation; authentication and authorization outcomes are recorded explicitly.
- Added Alembic revisions `20261014_security` and `20261014_audit_truncate`, after the existing `b7b05462a977` revision. The full chain successfully migrated a separate disposable PostgreSQL 16 database to head; database checks confirmed audit update, delete, and truncate operations are rejected. No existing migrations were modified.
- Local backend suite after the invitation workflow fix: **18 passed, 1 skipped**. PostgreSQL-backed suite on a dedicated disposable database previously passed **17 tests** (including the existing concurrency integration test and security cases).
- Angular production Docker image rebuilt successfully with the auth/RBAC UI. The host has Node.js 20.17.0, below Angular 22's minimum, so direct host `npm run build` is not a valid verification command; the supported Node.js 22.22.3 Docker build passed.
- Angular unit suite after the invitation workflow fix: **7 passed** using Node.js 22.22.3 and headless Chromium.
- Rebuilt and restarted the Compose backend/frontend without deleting or recreating the PostgreSQL volume. The live database advanced from `b7b05462a977` to `20261014_audit_truncate`; counts remained at **1 company, 11 categories, and 4 assets**. PostgreSQL, backend, and frontend all report healthy.
- Live checks confirmed `/`, `/login`, `/invite`, `/status`, and `/api/v1/health/ready` return HTTP 200 through Nginx. Unauthenticated company and membership API requests return HTTP 401 as intended. The operator has provisioned the first system administrator; no password or other credentials are recorded in this status document. The current database retains 1 company, 11 categories, and 4 assets.
- Local-account limitations: invitation tokens must be shared securely out of band; there is no email delivery, password reset, account recovery, SSO/OIDC, MFA, or HTTPS ingress configuration.

## Phase 1 implementation

### Backend

- SQLAlchemy models and Alembic migration `b7b05462a977` add companies, departments, sites, locations, cost centres, categories, numbering rules, assets, department usages, and asset history.
- Versioned API routes provide company/master-data CRUD, numbering-rule configuration, asset create/update/list/read, paging/search/filtering, usage start/end/list, and asset history.
- Company-owned relationships are scoped and constrained to their company. Protected API access requires a valid server-side session, an active company membership or system permission, and the action-specific permission.
- Company creation seeds six initial IT categories and a default asset-number format.
- Category rules override identifier formatting. A company-wide atomic sequence is shared across formats; already-used identifiers are skipped. Manual identifiers are serialized with the allocator and duplicates return a conflict.

### Frontend

- Angular registry UI is available at `/`; the technical health view remains at `/status`.
- Typed registry API client and management flows cover company selection/creation, master-data records, asset registration and listing, department usage, and history.
- Login, invitation acceptance, logout, permission-aware navigation, and company member invitation/revocation are integrated with the protected backend APIs. Invitation tokens are returned only by creation, never by company member list responses; revoking a pending membership also revokes its outstanding token.

### Important files

- Backend foundation: `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/services.py`
- API routes: `backend/app/api/v1/routes/organization.py`, `backend/app/api/v1/routes/assets.py`
- Migration: `backend/alembic/versions/b7b05462a977_organisation_and_asset_registry.py`
- Security: `backend/app/security.py`, `backend/app/authentication.py`, `backend/app/audit.py`, `backend/app/api/v1/routes/auth.py`, `backend/app/api/v1/routes/security_admin.py`
- Security migration/tests: `backend/alembic/versions/20261014_security_foundation.py`, `backend/tests/test_security.py`
- Tests: `backend/tests/test_organization_assets.py`, `backend/tests/test_postgres_concurrency.py`
- Frontend: `frontend/src/app/auth/`, `frontend/src/app/components/auth/`, `frontend/src/app/components/registry/`, `frontend/src/app/services/auth.service.ts`
- Frontend container: `frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/nginx.conf`
- Compose stack: `docker-compose.yml`
- Setup: `docs/setup.md`

## API and migration

All routes are under `/api/v1`.

- Health: `GET /api/v1/health`; readiness: `GET /api/v1/health/ready`
- Organisation: `/api/v1/companies` and `/api/v1/companies/{company_id}/{departments|sites|cost-centers|categories|numbering-rules}`
- Assets: `/api/v1/companies/{company_id}/assets`, with asset `usages`, `history`, `assignments`, and `service-contracts`
- Authentication: `/api/v1/auth/{login,me,logout,invitations/accept}`
- Security administration: `/api/v1/security/companies/{company_id}/...`, `/api/v1/security/system-administrators/...`, `/api/v1/security/users/...`, `/api/v1/security/roles`, and `/api/v1/security/audit`
- Procurement: `/api/v1/companies/{company_id}/suppliers`, `/purchase-orders`, `/goods-receipts`
- Maintenance: `/api/v1/companies/{company_id}/maintenance-users`, `/maintenance-requests`, `/service-contracts/{contract_id}/cancel`
- Dashboard & Reports: `/api/v1/companies/{company_id}/dashboard`, `/reports/asset-register`, `/reports/asset-allocation`, `/reports/warranty-expiry`, `/reports/maintenance`, `/reports/procurement`
- Current deployed migration head: `20261017_service_management (head)`

## Verification results

The latest checks for Phase 5 Executive Dashboard and Operational Reports:

- PostgreSQL-enabled pytest (`mindzen_test`): **42 passed, 0 skipped, 0 failed** in 18.23s.
- Standard backend suite (SQLite): **39 passed, 3 skipped** (PostgreSQL-specific concurrency and table triggers skipped as expected).
- `alembic check`: **passed** — zero schema drift detected.
- Angular headless Chromium test suite: **21 passed, 0 failed**.
- Angular production build: **passed** within performance budgets (`538.72 kB` bundle).
- Docker Compose stack: **PostgreSQL healthy, backend healthy, frontend healthy**.
- Database volume `postgres_data` preserved with all existing demo entities intact.

## Scope limitations and known issues

- Executive dashboard and operational reports use transactional database queries with company tenant isolation. Very large enterprise datasets may eventually benefit from pre-aggregated read models or database indexes on `(company_id, status)` / `(company_id, end_date)`.
- Client-side CSV export generates clean RFC-4180 compliant CSV files directly in the browser; server-side streaming export is deferred.
- Separate employee/custodian and vendor masters, custom fields, physical verification, and financial depreciation remain out of scope for Phase 5.
- Compose stack remains a local deployment baseline. HTTPS ingress, production secret management, SSO/OIDC, and external notifications remain deployment tasks.

## Recommended next task

Proceed with the next planned roadmap milestone according to stakeholder priorities. Keep local commits on the feature branch without pushing to the remote repository.
