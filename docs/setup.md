# MindZen Setup Guide

## Prerequisites

- Docker Desktop or Docker Engine with Docker Compose
- Git
- Node.js 20 LTS or later only when running the Angular development server
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

Then, in a terminal with Node.js installed:

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

The PostgreSQL concurrency integration test runs only when `TEST_DATABASE_URL` is set to a suitable test database. Angular production build:

```powershell
cd frontend
npm ci
npm run build
```

## Troubleshooting

- If Compose reports that host port `4200` is already in use, stop the Angular dev server or another process using that port before starting the frontend container.
- If backend startup reports a PostgreSQL connection refusal, verify the root `.env` `DATABASE_URL` uses host `postgres`, not `localhost`, and that credentials match the Compose PostgreSQL settings.
- If `http://localhost:4200/api/v1/health/ready` returns an error, check `docker compose ps` and `docker compose logs backend postgres`.
- The backend and database are internal Compose services. Use the health paths through port `4200`; their container hostnames are only resolvable inside the Compose network.
- The stack is a local development foundation, not a production-secure deployment. Authentication and authorization are not implemented; do not treat company path scoping as tenant isolation.

## Current application scope

The initial organisation and asset registry supports company and basic organisation master data, asset registration/listing, department usage, and asset history. Procurement, formal assignment/transfer workflows, authentication/authorization, maintenance, physical verification, finance, disposal, dashboards, and reporting remain deferred.
