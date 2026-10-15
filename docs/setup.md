# MindZen Setup Guide

## Prerequisites

- Docker Desktop or Docker Engine with Docker Compose
- Git
- Node.js 22.22.3+ on 22.x (recommended), 24.15.0+ on 24.x, or 26.0.0+ only when running the Angular development server
- Python 3.13+ only when running the FastAPI backend locally

## Project structure

- `backend/` — FastAPI application and database tooling
- `frontend/` — Angular application, production Dockerfile, and Nginx configuration
- `docker-compose.yml` — PostgreSQL, FastAPI, and Nginx-served Angular services
- `.env.example` — root environment template used by Docker Compose
- `backend/.env.example` — environment template for a backend process run locally
- `docs/` — architecture and operational documentation

## Configure the environment

From the project root, create the root environment file if it does not already exist:

```powershell
Copy-Item .env.example .env
```

For Docker Compose, `DATABASE_URL` must use `postgres` as its host, not `localhost`. The root template is configured this way. Keep credentials aligned with `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` if you customize the database settings. Do not use the sample credentials in a production deployment.

The Compose services read the root `.env`; the frontend image does not receive database credentials or a backend URL.
Keep `COOKIE_SECURE=false` only for local HTTP development. Set it to `true` when serving the application over HTTPS.

## Build and start the full application

From the project root:

```powershell
docker compose up --build -d
docker compose ps
```

Compose waits for PostgreSQL health, runs the existing Alembic migrations in the backend startup command, and then starts Nginx after the backend readiness check succeeds.

Open the application at **http://localhost:4200/**. The technical status page is at **http://localhost:4200/status**. Health and database-readiness checks, routed through Nginx, are:

- `http://localhost:4200/api/v1/health`
- `http://localhost:4200/api/v1/health/ready`

The frontend service publishes host port `4200` to Nginx port `80`. Nginx forwards `/api/v1` requests to the `backend` service over the Compose network, retaining the API prefix. Browser requests remain same-origin; they do not use an internal Docker hostname or a hard-coded backend address. PostgreSQL and FastAPI ports are not published on the host.

The first startup does not create a default account. After the services are healthy, provision the first system administrator interactively:

```powershell
docker compose exec backend python -m app.cli.bootstrap_admin
```

The password is entered without echo and is stored only as an Argon2id hash. The command refuses to create a second bootstrap administrator once one exists. Sign in at `http://localhost:4200/`; a system administrator can view and manage existing companies.

To invite a company user, select the intended company in the **Company scope** picker at the top of the workspace, then open **Users & Access** in the workspace navigation. Enter the user's email, select one of the roles you are authorized to grant, and choose **Create invitation**. The one-time token is shown only after creation; securely share it out of band. The recipient opens `http://localhost:4200/invite`, enters the token, and chooses a password. There is no email delivery service. The Users & Access list shows company memberships and pending invitations; a pending invitation can be revoked there.

## October 17 demo scenario

Use the existing `MINDZEN-DEMO` company and asset `MZ-000004`; do not create or delete database records just to repeat the demo. As of the Phase 3 verification on October 15, 2026, this asset is `in_stock`, has no current custodian, and retains two completed assignment records from the previous demonstration. Every repeat run appends new history.

Before the demonstration:

1. Start or verify the Compose application with `docker compose ps`. Confirm that `http://localhost:4200/`, `http://localhost:4200/status`, and `http://localhost:4200/api/v1/health/ready` load.
2. Sign in with a company administrator or asset manager who has `asset.assignment.manage`.
3. In **Users & Access**, invite two demonstration-only recipient accounts with the **Read-only User** role. The previously used `phase3-demo-recipient@example.invalid` and `phase3-demo-recipient2@example.invalid` memberships are revoked and may be re-invited; alternatively use other clearly identified test-only addresses. The recipients must accept their invitations at `/invite` before they appear as eligible custodians. Share one-time tokens out of band; do not put tokens or passwords in this guide.
4. In **Assets**, open `MZ-000004`. Confirm that it is in stock and has no current assignment. If it has an active assignment, use the normal **Record return** workflow to return it to stock; do not directly edit status/custodian data or delete assignment history.

Demonstrate the workflow from the asset detail panel:

1. Assign `MZ-000004` to the first active demonstration recipient, with an effective date, responsible department, and reference such as `PHASE3-DEMO`.
2. Record handover, condition, included items, and acknowledgement.
3. Transfer the asset to the second recipient and, if desired, another responsible department such as Information Technology. Enter a transfer reason and handover details.
4. Return the asset, selecting **In stock** as its next status.
5. Confirm the registry shows `in_stock` and no custodian. In the detail panel, confirm the current assignment is absent and all previous recipients and lifecycle details remain under **Assignment history** and **Change history**.
6. An authorized company administrator or auditor can verify persisted audit events through `GET /api/v1/security/audit?company_id=<company-id>&action=asset.assignment.created`, repeating the request with `asset.assignment.handover`, `asset.assignment.transferred`, and `asset.assignment.returned`. This endpoint enforces company-level `audit.read` permission.

**Non-destructive repeat/reset:** the known starting state is `MZ-000004` in stock with no current custodian. After a completed run it is already back in this state. Earlier assignment and audit history is deliberately retained; a repeat creates additional records rather than restoring a blank history. If a run stops mid-flow, complete it using the normal handover/transfer/return actions (or return the active assignment to stock). Re-invite revoked test recipients through **Users & Access** as needed. Do not truncate tables, edit lifecycle rows directly, reset the PostgreSQL volume, or use `docker compose down -v`. Revoke test memberships after the demonstration if appropriate; revocation does not erase assignment history.

Follow service startup or diagnose an error:

```powershell
docker compose logs -f
docker compose logs --tail=100 backend
```

## Stop, restart, and rebuild

Stop the services without deleting database data:

```powershell
docker compose down
```

The named `postgres_data` volume is retained by `docker compose down`. Start the existing stack again with:

```powershell
docker compose up -d
```

After frontend source or Nginx configuration changes, rebuild and replace the frontend container:

```powershell
docker compose build frontend
docker compose up -d frontend
```

To rebuild all images and recreate services:

```powershell
docker compose up --build -d
```

Do not use `docker compose down -v` unless you intentionally want to delete the persistent database volume.

## Run the Angular development server

The production Docker frontend and Angular development server both use host port `4200`; they cannot run on that port at the same time. Stop the production frontend before starting the dev server:

```powershell
docker compose stop frontend
```

Then, in a terminal with a Node.js version supported by Angular 22 installed:

```powershell
cd frontend
npm ci
npm start -- --proxy-config proxy.conf.json
```

The development proxy points to `http://localhost:8000`. Because Compose intentionally does not publish the backend port, this proxy is for use with a FastAPI process run locally on port `8000` (and a PostgreSQL database reachable by that process). To return to the Docker-hosted production frontend, stop the dev server with `Ctrl+C`, then run `docker compose up -d frontend`.

## Run the backend locally

For backend development outside Compose, prepare a Python environment and configure `backend/.env` for a PostgreSQL instance reachable from the host (typically `localhost:5432`):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The Compose PostgreSQL service is not published on the host; use a separately available local PostgreSQL instance for this workflow. The local API is then available at `http://localhost:8000/docs`.

## Migrations and tests

The Docker backend applies `alembic upgrade head` before starting FastAPI. The schema and migration files are preserved in the image and database volume.

Run backend tests locally:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

The PostgreSQL integration suite can run when `TEST_DATABASE_URL` points to a dedicated disposable test database. Tests create and drop tables; never point this variable at the application or any database containing data to preserve. The regular backend suite otherwise uses isolated in-memory SQLite. The Angular application is upgraded to Angular 22. Use Node.js 22.22.3+ on 22.x (recommended), 24.15.0+ on 24.x, or 26.0.0+ for local frontend development, builds, and tests:

```powershell
cd frontend
npm ci
npm run build
npm test -- --watch=false
```

## Troubleshooting

- If Compose reports that host port `4200` is already in use, stop the Angular dev server or another process using that port before starting the frontend container.
- If backend startup reports a PostgreSQL connection refusal, verify the root `.env` `DATABASE_URL` uses host `postgres`, not `localhost`, and that credentials match the Compose PostgreSQL settings.
- If `http://localhost:4200/api/v1/health/ready` returns an error, check `docker compose ps` and `docker compose logs backend postgres`.
- The backend and database are internal Compose services. Use the health paths through port `4200`; their container hostnames are only resolvable inside the Compose network.
- The frontend login depends on the bootstrap administrator or an invitation created by an authorized company administrator; no default credentials or public registration endpoint exist.
- If browser mutations return `403`, confirm cookies are enabled and the Angular app is accessed through the same origin so its CSRF token can be sent.
- The security baseline uses local accounts and manual out-of-band invitation sharing. SSO, password reset, account recovery, email delivery, HTTPS ingress, production secret management, and operational monitoring remain deployment/integration work.

## Current application scope

The current application supports authenticated company-scoped access to organisation and asset registry data, company invitations and memberships, role-based permissions, append-only audit events, the asset assignment lifecycle, supplier/purchase-order/goods-receipt procurement, warranty/AMC contracts, and maintenance requests.

Assignment lifecycle APIs are under `/api/v1/companies/{company_id}/assets/{asset_id}/assignments`: list history, create an assignment, and post to an assignment's `/handover`, `/return`, or `/transfer` endpoint. The scoped `/api/v1/companies/{company_id}/assets/assignment-recipients` endpoint returns eligible custodians to users with `asset.assignment.manage`. The Docker backend runs Alembic migrations, including `20261015_assignment` and `20261016_procurement`, before starting.

### Procurement demonstration

Use a company with an active asset category and a user with `procurement.manage`. From the **Procurement** tab:

1. Add a clearly labelled demo supplier (for example, code `DEMO-SUP-<unique suffix>`).
2. Create a purchase order with a unique demo order number, the active category, description, quantity, and unit cost.
3. Record a goods receipt against the order. Enter the physically received and rejected quantities, discrepancy notes when applicable, and optional comma-separated serial numbers for accepted items.
4. Confirm the receipt summary lists the created asset numbers, then open **Assets** and verify they appear in stock.
5. Review the purchase order and goods-receipt history to confirm the receipt, rejected quantities, and asset traceability remain recorded.

For a repeat demonstration, create a new supplier/order/receipt using unique demo identifiers. These records are retained for traceability; do not delete them or reset the PostgreSQL volume. This process intentionally creates additional labelled demonstration records and does not restore an earlier database snapshot. Use an isolated demo company if repeated runs must not add records to a business company. A rejected unit is recorded as a discrepancy and does not create an asset.

The procurement API is under `/api/v1/companies/{company_id}`: `GET/POST /suppliers`, `GET/POST /purchase-orders`, `GET /goods-receipts`, and `POST /purchase-orders/{purchase_order_id}/goods-receipts`. Accepted units and their receipt-line links, asset history, and audit events are committed in the same transaction.

### Warranty and maintenance demonstration

Use a company with an asset and a user with `maintenance.manage`. Open **Assets**, select the asset, then record a warranty or AMC with its date range, provider, reference and coverage. If the asset's procurement vendor reference matches an active supplier code, the API links that supplier and fills the provider name when omitted. Coverage status is derived on reads; an active contract ending within 30 days is labelled `expiring soon`. The **Warranty & Maintenance** view lists service requests and provides asset/status filters.

1. Create a maintenance request against an existing asset; set priority, reported date, and optionally assign an active company support user.
2. Open request details and move it through `open` → `in progress` → `resolved` → `closed`. To resolve it, provide a completion date and resolution notes; diagnosis, work performed, and cost are optional.
3. Open **Asset history** from the request list or the asset detail's **Maintenance history** button to review associated requests. Contract cancellation and request status changes require confirmation; closed requests and contract history are retained.

The API is under `/api/v1/companies/{company_id}`: `GET/POST /assets/{asset_id}/service-contracts`, `PATCH /service-contracts/{contract_id}/cancel`, `GET /maintenance-users`, and `GET/POST /maintenance-requests`, plus `PATCH /maintenance-requests/{request_id}`. All endpoints enforce company authorization; `maintenance.read` grants read access and `maintenance.manage` grants writes. Alembic revision `20261017_service_management` adds contract/request tables and deployed-role permission grants.

The live demonstration uses existing `MINDZEN-DEMO` / `MZ-000005` and retains AMC reference `DEMO-AMC-PHASE3-20261015-01` and maintenance request title `DEMO-MNT-PHASE3-20261015-01`. The request was completed through `open` → `in_progress` → `resolved` → `closed`; its audit history is retained. For another run, use a new contract reference and clearly labelled request title. These workflows append history; do not delete records or reset the database. The verified company currently has no active company-member support user, so the demonstration request is unassigned; invite and activate an appropriate support user if that step is to be demonstrated.

Requisitions, quotations, approvals, multi-currency/tax accounting, attachments, separate employee/HR masters, external identity integration, password recovery, preventive maintenance schedules, SLA escalation/reminders, physical verification, depreciation, disposal, dashboards, and reporting remain deferred.

A data-derived asset overview (counts and recent lifecycle activity) is deferred; it is not required for the October 17 registry-based demonstration.
