# MindZen ALCM / ITAM Architecture

## 1. Workspace baseline

The workspace began as a greenfield project. The Phase 0 technical foundation and the Phase 1 organisation-master/basic-asset-registry slice are now implemented. This document describes both the implemented foundation and the intended architecture for later lifecycle modules.

## 2. Product architecture overview

MindZen will be implemented as a modular monolith with three primary runtime layers:

- Frontend: Angular + TypeScript single-page application
- Backend: Python FastAPI service exposing versioned REST APIs under `/api/v1`
- Data layer: PostgreSQL, managed through SQLAlchemy 2.x and Alembic migrations

This keeps deployment simple while preserving boundaries that can be maintained independently and later extracted into services if genuine scale or ownership constraints emerge.

The application should be structured as a single deployable service with clear domain modules, not as a collection of tightly coupled route handlers. Each module owns its business logic, validation, persistence, and domain service layer. API routes remain thin orchestration layers that validate input and delegate to services.

Implemented backend domains currently include shared health/foundation code, organisation master data, and a basic asset registry. These are modules inside one FastAPI application, not separate services. Company ownership is represented in the schema and checked by company-scoped API routes and composite foreign keys. Authentication and actor authorization are not implemented; therefore these checks are application-level data scoping, not a secure tenant boundary.

## 3. Angular-to-FastAPI communication

The frontend must never connect to PostgreSQL directly. Angular will interact with the backend exclusively through REST/JSON endpoints.

### Implemented local container topology

Docker Compose runs PostgreSQL, FastAPI, and the Angular production build served by Nginx. Nginx is published on host port `4200` (container port `80`) and proxies the same-origin `/api/v1/` path to FastAPI on the internal Compose network. The browser does not need an API host configuration, and neither the backend nor PostgreSQL port is published by the standard Compose setup. Angular's development server can be used separately on port `4200`, but must not run at the same time as the frontend container on that port.

Recommended interaction model:

- Angular app calls typed API services that wrap backend endpoints
- Backend exposes `/api/v1/...` resource endpoints with consistent naming and pagination
- Requests and responses use typed Pydantic models
- UI state handles loading, validation, and server error states in a standard way
- Authentication is handled through token-based sessions or an identity provider integration behind the API boundary

Recommended conventions:

- Use versioned API paths: `/api/v1/assets`, `/api/v1/procurements`, `/api/v1/approvals`
- Use resource-oriented nouns with explicit actions only where needed (`/api/v1/assets/{id}/assign` or `/api/v1/assets/{id}/handover`)
- Return consistent payloads for success and error states
- Use DTOs at API boundaries rather than exposing raw persistence models
- Keep frontend components focused on rendering and user interaction, not business rules

## 4. Backend module boundaries and responsibilities

The FastAPI application should be divided into business modules with a shared foundation layer. Suggested initial module structure:

### Shared foundation

- `core` / `common`
  - configuration and environment loading
  - shared DTOs and enums
  - common validation utilities
  - base audit fields and paging metadata
  - health checks and status endpoints

### Organisation and master data

- `organization`
  - companies, organisational units, sites, departments, cost centres
  - users, employees, custodians, vendors, and generic master data
  - category and custom-field metadata
  - numbering conventions and configuration

### Procurement

- `procurement`
  - requisitions and line items
  - budget references and approval workflow hooks
  - quotations and vendor comparisons
  - purchase orders and receipt tracking
  - GRNs, inspections, discrepancies, rejections, and receipts

### Asset registry and lifecycle

- `assets`
  - asset master records
  - serial, model, manufacturer, category, and acquisition data
  - deployment state and assignment history
  - location, department, and custodian history
  - asset status and lifecycle state transitions

### Maintenance and service

- `maintenance`
  - warranty, AMC, SLA records
  - maintenance plans and work orders
  - service tickets and repair records
  - downtime tracking and repair cost data

### Verification and audit

- `verification`
  - audit campaigns and expected asset lists
  - physical verification outcomes
  - exceptions, discrepancies and reconciliation actions
  - evidence and documentation tracking

### Finance and end-of-life

- `finance`
  - acquisition cost and accounting metadata
  - depreciation records and policies
  - EOL review and replacement decisions
  - disposal, resale, scrap, and closure workflows

### Security, workflows and governance

- `security` / `governance`
  - roles, permissions, and policy enforcement
  - approval workflows and state transition rules
  - reason and comment history
  - audit log aggregation and security event review

### Integrations and reporting

- `integrations`
  - ERP, HRMS, ITSM, CMDB, identity, and external adapters
  - data import/export contracts and mapping layers
  - versioned external interfaces with backend abstraction

- `reporting`
  - inventory, lifecycle, maintenance, warranty, audit, and disposal reports
  - dashboards driven by persisted data
  - export preparation and report metadata

## 5. Proposed database design approach

The primary persistence layer will be PostgreSQL. The schema should be designed around a shared business model with additional tables for policy, workflow, and audit metadata. The implementation should separate data ownership by business module while keeping the application as a single database service.

Suggested design principles:

- One PostgreSQL database for the monolith, with schemas or modules used to keep logical separation clear
- Domains manage their own tables but reference shared keys and metadata with consistent conventions
- Use foreign keys and explicit status enums or lookup tables for lifecycle-driven states
- Persist history where business events matter more than current state, especially for custody, assignment, approvals, and disposal
- Separate configurable metadata (policies, workflows, organisation rules) from transactional data
- Add effective-dated records when policy or organisational rules may change over time

Core data patterns:

- `company`, `site`, `department`, `cost_center`, `employee`, `vendor`, `asset_category`
- `asset` as the central lifecycle record, linked to category, organisation, status, custodians, and acquisitions
- `purchase_requisition`, `purchase_order`, `goods_receipt_note`, `asset_register` as operational traceability chain
- `maintenance_order`, `service_ticket`, `audit_campaign`, `verification_record` as event-oriented records
- `approval_workflow`, `approval_step`, `approval_action`, and `audit_event` for governance and traceability

A schema-first design approach is used, with SQLAlchemy models and Alembic migrations as the source of persisted schema changes. The implemented Phase 1 schema covers companies, departments, sites, locations, cost centres, categories, numbering rules, assets, department usage, and asset history. Later domain areas below remain planned rather than implemented.

Asset numbers are unique within a company. Category-specific rules select a display format, while the company-default rule supplies one shared, atomically allocated sequence across all category formats. The allocator skips already-used candidates, including identifiers entered manually.

## 6. Authentication, authorization and audit strategy

### Authentication

Recommended baseline for the initial product:

- Use a secure, standards-based authentication method such as OAuth2/OIDC or a JWT-based token strategy behind the FastAPI API boundary
- Keep the identity integration configurable so an implementation can use enterprise identity providers without code changes to the application core
- Do not hard-code a single auth vendor into module logic

### Authorization

Use role-based access control (RBAC) combined with permission checks on domain actions. Example dimensions:

- Organisations and sites
- Departments / cost centres
- Asset categories or ownership scopes
- Approval roles and workflow responsibilities

A practical initial strategy is a permission matrix and role assignments, not a fully dynamic policy engine. Role membership and permission evaluation should be driven from persisted configuration tables and evaluated in domain services.

### Auditability

Business critical actions must be traceable.

Audit requirements for initial implementation should cover:

- creation and change history for asset, procurement, and approval records
- who performed an action and when
- reason, comment, or evidence reference for key status changes
- approval and rejection history
- disposal or closure events
- physical verification and discrepancy reconciliation

The audit model should be append-only or event-driven where practical, rather than relying solely on current-state snapshots.

## 7. Configuration and policy approach

Configuration is a core product requirement. The architecture should support business rules without forcing source-code changes for each customer.

Recommended design:

- Persist policy definitions in tables rather than code constants
- Store effective dates and validity windows for changes to policy and workflow records
- Keep the first release policy model small, explicit, and testable
- Avoid a generic visual rules engine in v1 unless a requirement emerges that clearly needs it

Initial policy areas:

- useful life and depreciation policy
- EOL review timing
- physical verification frequency
- required evidence for actions and closures
- approver thresholds and transition rules
- allowed state transitions and exceptions

The architecture should support a simple policy engine that reads configuration records from the database and applies validation in domain services. The policy layer should remain generic enough for future expansion without turning into a fully dynamic workflow designer.

## 8. API conventions and error handling

### API conventions

- All API routes under `/api/v1`
- Resource-based naming and versioning
- Consistent use of HTTP methods and status codes
- Standard pagination for list responses
- Search, filter, and sort parameters supported where needed
- Use Pydantic models for request validation and response serialization

### Error handling

- Validation errors should return structured 400 responses
- Authorization failures should return 401 or 403 as appropriate
- Resource not found should return 404
- Domain-level validation failures should return clear, business-readable messages
- Unexpected errors should be logged and returned with generic-safe results

Recommended approach:

- `FastAPI` exception handlers for consistent response formatting
- Domain service exceptions converted to API-safe errors
- Logging and correlation IDs to support support and audit review

## 9. Background jobs and document storage

The initial architecture should support non-blocking workflows without introducing unnecessary complexity.

### Background jobs

For v1, use a simple background processing pattern such as:

- FastAPI task scheduling or a lightweight worker process inside the monolith
- Jobs for reminders, warranty expiry notifications, and periodic audit notices
- Job metadata stored in database tables for traceability and retryability

It is acceptable to defer more advanced asynchronous patterns until the business process is better understood. The design should remain compatible with later enhancement.

### Document storage

The system needs evidence and attachment support, but the exact document storage requirement is not fully specified in the prompt.

Recommended baseline:

- Store metadata for documents in the database: file name, owner, type, uploaded by, upload timestamp, and relation to a business record
- Keep actual file storage behind an abstraction so the app can use local storage, cloud object storage, or enterprise document repositories as needed
- Treat document retention and security classification as configuration-driven concerns

This is an area that should remain intentionally modular and not tightly coupled to the business processes.

## 10. Local development and deployment approach

### Local development

Use Docker Compose to manage local dependencies:

- PostgreSQL database
- Backend application container
- Angular frontend development server
- Optional support services if later needed (for example, a local object storage emulator or mail catcher)

Environment-specific configuration should be driven by `.env` files, with `.env.example` committed as a template. Configuration values must never contain production credentials or secrets.

### Deployment model

For the first release, a single deployable environment is recommended:

- One FastAPI application instance serving all modules
- One PostgreSQL database or a managed PostgreSQL service
- Angular application served through a web server or reverse proxy
- Separate environment configuration for dev, test, and production

This meets the requirement for a modular monolith while keeping deployment and operational complexity manageable.

## 11. Key architecture decisions to keep stable

- Modular monolith, not microservices
- Angular communicates only through APIs
- FastAPI handles validation, orchestration, and domain services
- PostgreSQL is the source of truth for transactional data
- Policy and workflow data remain configurable and effective-dated
- Auditability is treated as a first-class requirement, not an add-on
- Business logic stays in domain services and not in Angular components or API route handlers

## 12. Deferred items and open design boundaries

The following items should be deferred or explicitly confirmed later:

- exact identity provider and SSO integration model
- exact document storage provider and retention policy
- whether multi-company tenancy will be isolated at database, schema, or application level
- whether depreciation rules will be calculated centrally or through configurable policy services
- whether QR/barcode scanning will be supported via browser-only flow or device integrations
- whether an external notification service will be integrated early or handled inside the monolith

These are not blockers for initial architecture, but they should be tracked as open questions.

## 13. Recommended implementation stance for v1

The initial delivery should be deliberately pragmatic:

- Build a runnable technical foundation
- Add core organisation, asset, and procurement processes
- Add basic workflow and governance controls
- Add verification, maintenance, finance, and EOL support in later phases
- Keep the architecture modular enough for future extraction when the business justifies it

This is the correct balance between enterprise ambition and sensible delivery discipline for a complex lifecycle platform.
