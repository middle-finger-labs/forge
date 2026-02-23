#!/usr/bin/env bash
set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[1;32m'
RED='\033[1;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[forge]${NC} $*"; }
warn()  { echo -e "${YELLOW}[forge]${NC} $*"; }
error() { echo -e "${RED}[forge]${NC} $*"; exit 1; }

cd "$(dirname "$0")"

# --- .env ---
if [ ! -f .env ]; then
    info "Creating .env from .env.example"
    cp .env.example .env
    warn "Edit .env to add your ANTHROPIC_API_KEY before running agents"
fi

# --- Docker ---
info "Starting Docker Compose services..."
docker compose up -d

info "Waiting for PostgreSQL to be healthy..."
until docker compose exec -T postgres pg_isready -U forge -d temporal > /dev/null 2>&1; do
    sleep 2
done
info "PostgreSQL is ready."

info "Waiting for Temporal server to be healthy..."
MAX_ATTEMPTS=30
ATTEMPT=0
until docker compose exec -T temporal tctl --address temporal:7233 cluster health 2>/dev/null | grep -q SERVING; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
        error "Temporal did not become healthy after ${MAX_ATTEMPTS} attempts."
    fi
    sleep 5
done
info "Temporal is ready."

# --- Python venv ---
if [ ! -d .venv ]; then
    info "Creating Python 3.12 virtual environment..."
    python3.12 -m venv .venv
fi

info "Installing dependencies..."
.venv/bin/pip install --upgrade pip > /dev/null
.venv/bin/pip install -e ".[dev]" > /dev/null

# --- Done ---
echo ""
info "========================================="
info "  Forge is ready!"
info "========================================="
echo ""
info "Activate the venv:        source .venv/bin/activate"
info "Temporal UI:              http://localhost:8088"
info "PostgreSQL:               localhost:5432  (forge / forge_dev_password)"
info "Redis:                    localhost:6379"
echo ""
info "Run tests:                pytest"
info "Start a worker:           python -m workflows.worker"
info "Stop services:            docker compose down"
echo ""
warn "Don't forget to set ANTHROPIC_API_KEY in .env"
