# Project Status

## Current delivery

**Phase 0 technical foundation: complete. Phase 1 organisation master data and basic asset registry: implemented and verified within the scope below.**

Workspace: `c:\Users\krgop\Documents\Projects\MindzAssetManagementPlatform`

## Containerized local application (verified 2026-10-14)

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
- Alembic current revision: **`b7b05462a977 (head)`**; `alembic check`: **passed**, no new upgrade operations detected.
- Backend tests: **8 passed, 1 skipped**. The PostgreSQL concurrency test is skipped unless `TEST_DATABASE_URL` is configured.
- Local Angular production build after a clean `npm ci`: **passed**.
- `npm install --package-lock-only` was required to correct a pre-existing mismatch between `package.json` and `package-lock.json`. npm reported 64 dependency audit findings (7 low, 16 moderate, 39 high, 2 critical); dependency upgrades were not part of this containerization task.

## Phase 1 implementation

### Backend

- SQLAlchemy models and Alembic migration `b7b05462a977` add companies, departments, sites, locations, cost centres, categories, numbering rules, assets, department usages, and asset history.
- Versioned API routes provide company/master-data CRUD, numbering-rule configuration, asset create/update/list/read, paging/search/filtering, usage start/end/list, and asset history.
- Company-owned relationships are scoped and constrained to their company. Company path IDs are not an authorization boundary because authentication and authorization are not implemented.
- Company creation seeds six initial IT categories and a default asset-number format.
- Category rules override identifier formatting. A company-wide atomic sequence is shared across formats; already-used identifiers are skipped. Manual identifiers are serialized with the allocator and duplicates return a conflict.

### Frontend

- Angular registry UI is available at `/`; the technical health view remains at `/status`.
- Typed registry API client and management flows cover company selection/creation, master-data records, asset registration and listing, department usage, and history.
- The UI clearly warns that authentication/company authorization is not implemented.

### Important files

- Backend foundation: `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/services.py`
- API routes: `backend/app/api/v1/routes/organization.py`, `backend/app/api/v1/routes/assets.py`
- Migration: `backend/alembic/versions/b7b05462a977_organisation_and_asset_registry.py`
- Tests: `backend/tests/test_organization_assets.py`, `backend/tests/test_postgres_concurrency.py`
- Frontend: `frontend/src/app/components/registry/`, `frontend/src/app/services/registry.service.ts`
- Frontend container: `frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/nginx.conf`
- Compose stack: `docker-compose.yml`
- Setup: `docs/setup.md`

## API and migration

All routes are under `/api/v1`.

- Health: `GET /api/v1/health`; readiness: `GET /api/v1/health/ready`
- Organisation: `/api/v1/companies` and `/api/v1/companies/{company_id}/{departments|sites|cost-centers|categories|numbering-rules}`
- Assets: `/api/v1/companies/{company_id}/assets`, with asset `usages` and `history` subresources
- Migration head: `b7b05462a977`; clean-database migration chain was applied successfully; `alembic check` reports no new upgrade operations

## Verification results

The latest checks for the numbering changes and existing registry:

- PostgreSQL-enabled pytest: **9 passed**, with one upstream Starlette/AnyIO deprecation warning.
- `alembic check`: **passed** — no new upgrade operations detected.
- Angular `npm run build`: **passed**.
- PostgreSQL migration chain on a clean temporary database: **passed** (temporary database was dropped after verification).
- PostgreSQL concurrent asset-number allocation test: **passed** as part of the 9-test run.
- API and browser smoke flows: company/master creation, asset registration, department usage and history succeeded. The exact browser-created verification company `UIQA10131809` and its dependent records were removed.
- The default counter is stored in PostgreSQL, and manual/generated identifiers are checked against existing company asset numbers.
- Current Dockerized-stack verification is recorded above; the database was restarted without deleting its volume or records.

## Scope limitations and known issues

- Authentication, authorization, and actor identity/audit attribution are not implemented. Company scoping is not production-grade tenant isolation.
- Employee/custodian and vendor masters, formal assignment/transfer workflows, custom fields, procurement, maintenance, physical verification, finance, disposal, dashboards, and reports are not implemented.
- The standard pytest run without `TEST_DATABASE_URL` skips the PostgreSQL-only concurrency test; set that variable to execute it against PostgreSQL.
- The Angular development server and production frontend container both require host port `4200`; stop one before starting the other. The development proxy expects a locally running backend on port `8000`.
- The Compose stack is a local deployment baseline, not production security hardening. HTTPS/domain ingress, secret management, authentication, authorization, and production tenant isolation remain deployment tasks.

## Recommended next task

Confirm the Phase 1 scope and security boundary, then implement the authentication and authorization design (company access enforcement and actor attribution) before production use. Do not infer or claim that the present company path scoping provides security isolation.
