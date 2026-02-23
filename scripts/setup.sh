#!/usr/bin/env bash
# =============================================================================
# Forge — First-run setup script
# =============================================================================
# Brings up the full multiplayer stack, runs migrations, seeds the database.
#
# Usage:
#   ./scripts/setup.sh            # interactive (prompts for missing secrets)
#   ./scripts/setup.sh --ci       # non-interactive (auto-generates everything)
set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[1;32m'
RED='\033[1;31m'
CYAN='\033[1;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[forge]${NC} $*"; }
warn()  { echo -e "${YELLOW}[forge]${NC} $*"; }
error() { echo -e "${RED}[forge]${NC} $*"; exit 1; }
header(){ echo -e "\n${CYAN}═══ $* ═══${NC}"; }

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

CI_MODE=false
[[ "${1:-}" == "--ci" ]] && CI_MODE=true

# ---------------------------------------------------------------------------
# 1. Create .env from template
# ---------------------------------------------------------------------------
header "Environment Configuration"

if [ ! -f .env ]; then
    info "Creating .env from .env.example"
    cp .env.example .env
fi

# Source existing .env
set -a
source .env
set +a

# Auto-generate BETTER_AUTH_SECRET if not set
if [ -z "${BETTER_AUTH_SECRET:-}" ]; then
    BETTER_AUTH_SECRET=$(openssl rand -base64 32)
    sed -i.bak "s|^BETTER_AUTH_SECRET=.*|BETTER_AUTH_SECRET=${BETTER_AUTH_SECRET}|" .env
    rm -f .env.bak
    info "Generated BETTER_AUTH_SECRET"
fi

# Auto-generate FORGE_ENCRYPTION_KEY if not set
if [ -z "${FORGE_ENCRYPTION_KEY:-}" ]; then
    FORGE_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32)
    sed -i.bak "s|^FORGE_ENCRYPTION_KEY=.*|FORGE_ENCRYPTION_KEY=${FORGE_ENCRYPTION_KEY}|" .env
    rm -f .env.bak
    info "Generated FORGE_ENCRYPTION_KEY"
fi

# Warn about API key
if [ -z "${ANTHROPIC_API_KEY:-}" ] || [[ "${ANTHROPIC_API_KEY}" == sk-ant-... ]]; then
    warn "ANTHROPIC_API_KEY is not set — edit .env before running pipelines"
fi

# ---------------------------------------------------------------------------
# 2. Start Docker Compose services
# ---------------------------------------------------------------------------
header "Starting Docker Services"

info "Pulling images..."
docker compose pull --quiet 2>/dev/null || true

info "Building application images..."
docker compose build

info "Starting services..."
docker compose up -d

# ---------------------------------------------------------------------------
# 3. Wait for PostgreSQL
# ---------------------------------------------------------------------------
header "Waiting for Services"

info "Waiting for PostgreSQL..."
ATTEMPTS=0
MAX_ATTEMPTS=30
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-forge}" > /dev/null 2>&1; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
        error "PostgreSQL did not become healthy after ${MAX_ATTEMPTS} attempts"
    fi
    sleep 2
done
info "PostgreSQL is ready"

# ---------------------------------------------------------------------------
# 4. Run database migrations
# ---------------------------------------------------------------------------
header "Database Migrations"

PG_CONN="postgresql://${POSTGRES_USER:-forge}:${POSTGRES_PASSWORD:-forge_dev_password}@localhost:5432/forge_app"

# Run numbered migration files in order
MIGRATION_DIR="${PROJECT_ROOT}/infrastructure/migrations"
if [ -d "$MIGRATION_DIR" ]; then
    for migration in $(ls "$MIGRATION_DIR"/*.sql 2>/dev/null | sort); do
        fname=$(basename "$migration")
        info "Applying migration: $fname"
        docker compose exec -T postgres psql "$PG_CONN" -f "/dev/stdin" < "$migration" 2>/dev/null || true
    done
    info "Migrations complete"
else
    info "No migration directory found — skipping"
fi

# ---------------------------------------------------------------------------
# 5. Wait for Temporal
# ---------------------------------------------------------------------------
info "Waiting for Temporal..."
ATTEMPTS=0
MAX_ATTEMPTS=30
until docker compose exec -T temporal tctl --address temporal:7233 cluster health 2>/dev/null | grep -q SERVING; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
        error "Temporal did not become healthy after ${MAX_ATTEMPTS} attempts"
    fi
    sleep 5
done
info "Temporal is ready"

# ---------------------------------------------------------------------------
# 6. Wait for auth service and run schema generation + seed
# ---------------------------------------------------------------------------
header "Auth Setup"

info "Waiting for forge-auth..."
ATTEMPTS=0
MAX_ATTEMPTS=20
until curl -sf http://localhost:3100/health > /dev/null 2>&1; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
        error "forge-auth did not become healthy after ${MAX_ATTEMPTS} attempts"
    fi
    sleep 3
done
info "forge-auth is ready"

# Run Better Auth schema migration inside the auth container
info "Running Better Auth schema migration..."
docker compose exec -T forge-auth npx @better-auth/cli migrate --config ./server.ts -y 2>/dev/null || \
    warn "Better Auth migration returned non-zero (may already be applied)"

# Seed the default org and admin user
info "Seeding default organization and admin user..."
docker compose exec -T \
    -e FORGE_ADMIN_EMAIL="${FORGE_ADMIN_EMAIL:-admin@example.com}" \
    -e FORGE_ADMIN_PASSWORD="${FORGE_ADMIN_PASSWORD:-changeme123}" \
    forge-auth npx tsx seed.ts

# ---------------------------------------------------------------------------
# 7. Health check
# ---------------------------------------------------------------------------
header "Health Check"

check_service() {
    local name=$1 url=$2
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name"
    else
        echo -e "  ${RED}✗${NC} $name"
    fi
}

check_service "PostgreSQL"   "http://localhost:5432" 2>/dev/null || \
    docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-forge}" > /dev/null 2>&1 && \
    echo -e "  ${GREEN}✓${NC} PostgreSQL" || echo -e "  ${RED}✗${NC} PostgreSQL"
check_service "Auth Service"  "http://localhost:3100/health"
check_service "API Server"    "http://localhost:8000/api/health"
check_service "Dashboard"     "http://localhost:3000"
check_service "Temporal UI"   "http://localhost:8088"

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
header "Forge is Ready!"

echo ""
info "Dashboard:        http://localhost:3000"
info "API Server:       http://localhost:8000"
info "Auth Service:     http://localhost:3100"
info "Temporal UI:      http://localhost:8088"
echo ""
info "Login credentials:"
info "  Email:    ${FORGE_ADMIN_EMAIL:-admin@example.com}"
info "  Password: ${FORGE_ADMIN_PASSWORD:-changeme123}"
echo ""
warn "Don't forget to set ANTHROPIC_API_KEY in .env before running pipelines"
info "Stop services: docker compose down"
echo ""
