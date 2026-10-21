#!/usr/bin/env bash
# MindZen ALCM/ITAM — Safe & Repeatable Sample Data Seeding Script
#
# Usage:
#   ./scripts/seed_demo_data.sh [OPTIONS]
#
# Options:
#   --company-code <code>   Target company code (e.g. DEMO-CORP)
#   --company-id <id>       Target company UUID
#   --create-company        Create company if not already existing
#   --dry-run               Simulate and display planned changes without modifying database
#   -y, --yes               Proceed without interactive confirmation prompt
#   -h, --help              Show usage help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# 1. Verify expected repository structure
if [ ! -f "docker-compose.yml" ] || [ ! -d "backend" ]; then
    echo "Error: Must be executed from the MindZen application repository root." >&2
    exit 1
fi

# 2. Detect Docker Compose and running backend container
USE_DOCKER=0
DOCKER_CMD=""

if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        DOCKER_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        DOCKER_CMD="docker-compose"
    fi

    if [ -n "${DOCKER_CMD}" ]; then
        if ${DOCKER_CMD} ps --services --filter "status=running" 2>/dev/null | grep -q "^backend$"; then
            USE_DOCKER=1
        fi
    fi
fi

# 3. Execution routing
if [ "${USE_DOCKER}" -eq 1 ]; then
    echo "Running seeder via Docker Compose ('mindzen-backend' container)..."
    TTY_FLAG="-T"
    if [ -t 0 ] && [ -t 1 ]; then
        TTY_FLAG=""
    fi
    exec ${DOCKER_CMD} exec ${TTY_FLAG} backend python -m app.cli.seed_demo_data "$@"
else
    echo "Docker backend container not detected; checking local Python environment..."
    PYTHON_BIN=""
    if [ -f "backend/.venv/bin/python" ]; then
        PYTHON_BIN="backend/.venv/bin/python"
    elif [ -f "backend/.venv/Scripts/python.exe" ]; then
        PYTHON_BIN="backend/.venv/Scripts/python.exe"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    fi

    if [ -z "${PYTHON_BIN}" ]; then
        echo "Error: Neither a running Docker Compose backend container nor Python was found." >&2
        echo "On EC2, ensure the stack is running with: docker compose up -d" >&2
        exit 1
    fi

    export PYTHONPATH="backend:${PYTHONPATH:-}"
    exec "${PYTHON_BIN}" -m app.cli.seed_demo_data "$@"
fi

