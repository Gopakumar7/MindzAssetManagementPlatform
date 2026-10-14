# Assumptions and Decisions

## 1. Decisions made from this prompt and implementation

The following decisions are explicit or strongly implied by the project brief and should be treated as the default working assumptions for the planning phase:

1. Product scope
   - The application is an enterprise Asset Life Cycle Management and IT Asset Management platform.
   - The platform covers acquisition, deployment, usage, maintenance, verification, financial management, EOL, and disposal.

2. Delivery model
   - The project will use a modular monolith architecture.
   - The backend is FastAPI with SQLAlchemy 2.x, Pydantic validation, PostgreSQL, and Alembic migrations.
   - The frontend is Angular with TypeScript and typed API access.

3. Engineering standards
   - The UI must not directly connect to the database.
   - Business logic should live in domain services, not in Angular components or route handlers.
   - `/api/v1` is the default API versioning pattern.
   - Docker Compose and environment configuration are part of the recommended local setup.

4. Configurability
   - Organisation policy and workflow rules must be configurable, not hard-coded.
   - A small, explicit policy and workflow mechanism is preferred over a fully generic rules engine in v1.

5. Auditability and security
   - Approval history, reasons, timestamps, and critical state transitions must be recorded.
   - Authorization and governance controls are required across lifecycle stages.

## 2. Business assumptions that require confirmation

The following items are practical assumptions but not confirmed business requirements:

- The initial schema uses one PostgreSQL database with company-owned records, explicit company IDs in API paths, scoped queries, and same-company composite foreign keys. A company is the data ownership boundary in the implemented slice.
- This is not a security boundary: authentication and authorization are not implemented, and company selection is not restricted to an authenticated actor. Production tenant isolation must not be claimed until identity, authorization, and access tests are delivered.
- Assets may include IT hardware, software entitlements, and other organisational assets, but a final list of asset classes is not yet defined.
- The product may be used for internal corporate assets, departmental equipment, and other operational technology, but no final legal or regulatory scope has been specified.
- A central employee or user registry may be reused by the product, but the system boundary with HR or identity systems is not yet confirmed.
- Depreciation and accounting treatment will be configurable, but the final accounting framework and country-specific constraints are intentionally deferred.
- Document storage and evidence handling will be supported, but the preferred provider and retention rules remain open.

## 3. Open questions

These questions should be tracked as unresolved design decisions and either answered later or converted into purposeful defaults before implementation:

1. Production tenancy enforcement
   - Which identity provider and authorization model will bind an authenticated actor to permitted companies? The current company-scoped schema is a data model decision, not production access control.

2. Asset class definition
   - Does the product include only IT assets, or also non-IT operational assets such as fleet, facilities, and equipment?

3. Identity and access model
   - Will the application use a full external identity provider and SSO, or a local user model with RBAC?

4. Reporting and data retention
   - What retention policies apply to audit records, disposal evidence, and attachments?

5. Policy granularity
   - Should policies be configured globally, by company, by site, by department, or by category?

6. State transition model
   - Are state transitions always driven by workflow approval, or should some transitions allow direct operational changes under role constraints?

7. Financial rules
   - What exact depreciation and useful-life logic will be accepted in the first implementation, and how do those rules vary by asset class?

8. Barcode and scanning support
   - Is barcode/QR scanning required for all devices or only a subset of workflows?

9. Document security
   - Are documents confidential and restricted to specific roles, or are all attachments at a more general access level?

10. Notification channels
   - Should notifications be in-app only, email-based, or integrated with a messaging platform?

## 4. Risks associated with unresolved decisions

The main risks in this planning stage are:

- Policy ambiguity may cause rework as workflow and approval logic evolve.
- Unclear tenancy assumptions can create major architecture and data-ownership issues.
- Asset classification uncertainty can affect schema design, categories, and lifecycle rules.
- Unresolved identity integration decisions could alter authentication design and security controls.
- Lack of explicit disposal, accounting, and retention policy decisions can delay compliance-oriented features.

## 5. Important distinctions

This document intentionally does not present assumptions as confirmed business requirements. It records the decisions made from the prompt, identifies what still needs confirmation, and highlights the risks of proceeding without a clear answer.

## 6. Recommended default position for unresolved items

When a decision cannot be made responsibly from the prompt alone, the default recommendation is:

- keep the design configurable and explicit
- avoid hard-coding a single customer rule into the domain logic
- prefer a minimal but extendable policy model
- maintain a documented “open issue” list for later confirmation from business stakeholders or product owners

## 7. Phase 1 implementation decisions

- Company IDs scope organisation and asset API paths. Company-owned foreign-key relationships are checked in services and constrained in the database where applicable.
- Company creation seeds six initial hardware categories and one default asset-number formatting rule.
- Category-specific numbering rules override only the display prefix/separator/padding. All rules share the company default rule's atomic sequence to avoid collisions across formats; candidate identifiers already used by manually entered or prior numbers are skipped.
- Asset department usage is represented separately from the asset's responsible department and location. Starting/ending usage does not silently change custody or location.
- Current history has timestamps and field/value snapshots but no actor identity or reason. This remains a governance gap for future security/workflow work.

This default keeps the design flexible without pretending the unresolved matters are already solved.
