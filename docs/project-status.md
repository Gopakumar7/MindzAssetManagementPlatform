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
