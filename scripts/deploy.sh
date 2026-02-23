#!/usr/bin/env bash
# =============================================================================
# Forge — Deploy / update script for VPS
# =============================================================================
# Pulls latest code, rebuilds containers, runs migrations, health-checks.
#
# Usage:
#   ./scripts/deploy.sh                    # standard deploy
#   ./scripts/deploy.sh --skip-migrations  # skip DB migrations
set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[1;32m'
RED='\033[1;31m'
CYAN='\033[1;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn()  { echo -e "${YELLOW}[deploy]${NC} $*"; }
error() { echo -e "${RED}[deploy]${NC} $*"; exit 1; }
header(){ echo -e "\n${CYAN}═══ $* ═══${NC}"; }

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

SKIP_MIGRATIONS=false
[[ "${1:-}" == "--skip-migrations" ]] && SKIP_MIGRATIONS=true

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
header "Pre-flight Checks"

[ -f .env ] || error ".env file not found — run scripts/setup.sh first"

command -v docker >/dev/null 2>&1 || error "docker not found"
docker compose version >/dev/null 2>&1 || error "docker compose not found"

set -a
source .env
set +a

info "Environment loaded"

# ---------------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------------
header "Pulling Latest Code"

if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    info "Current branch: $CURRENT_BRANCH"

    BEFORE=$(git rev-parse HEAD)
    git pull --ff-only 2>/dev/null || warn "git pull failed — deploying current state"
    AFTER=$(git rev-parse HEAD)

    if [ "$BEFORE" != "$AFTER" ]; then
        info "Updated: $(git log --oneline "$BEFORE".."$AFTER" | wc -l | tr -d ' ') new commit(s)"
        git log --oneline "$BEFORE".."$AFTER" | head -5
    else
        info "Already up to date"
    fi
else
    warn "Not a git repository — skipping pull"
fi

# ---------------------------------------------------------------------------
# 2. Build images
# ---------------------------------------------------------------------------
header "Building Images"

info "Building forge-api..."
docker compose build forge-api --quiet

info "Building forge-worker..."
docker compose build forge-worker --quiet

info "Building forge-dashboard..."
docker compose build forge-dashboard --quiet

info "Building forge-auth..."
docker compose build forge-auth --quiet

info "All images built"

# ---------------------------------------------------------------------------
# 3. Rolling restart
# ---------------------------------------------------------------------------
header "Deploying Services"

# Bring up infrastructure first (no-op if already running)
info "Ensuring infrastructure is up..."
docker compose up -d postgres redis temporal temporal-ui

# Wait for postgres
ATTEMPTS=0
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-forge}" > /dev/null 2>&1; do
    ATTEMPTS=$((ATTEMPTS + 1))
    [ "$ATTEMPTS" -ge 20 ] && error "PostgreSQL not healthy"
    sleep 2
done
info "PostgreSQL ready"

# ---------------------------------------------------------------------------
# 4. Run migrations (if not skipped)
# ---------------------------------------------------------------------------
if [ "$SKIP_MIGRATIONS" = false ]; then
    header "Database Migrations"

    PG_CONN="postgresql://${POSTGRES_USER:-forge}:${POSTGRES_PASSWORD:-forge_dev_password}@localhost:5432/forge_app"
    MIGRATION_DIR="${PROJECT_ROOT}/infrastructure/migrations"

    if [ -d "$MIGRATION_DIR" ]; then
        for migration in $(ls "$MIGRATION_DIR"/*.sql 2>/dev/null | sort); do
            fname=$(basename "$migration")
            info "Applying: $fname"
            docker compose exec -T postgres psql "$PG_CONN" -f "/dev/stdin" < "$migration" 2>/dev/null || true
        done
        info "Migrations complete"
    fi
else
    info "Skipping migrations (--skip-migrations)"
fi

# ---------------------------------------------------------------------------
# 5. Restart application services
# ---------------------------------------------------------------------------
header "Restarting Application Services"

info "Restarting forge-auth..."
docker compose up -d forge-auth
sleep 3

info "Restarting forge-api..."
docker compose up -d forge-api
sleep 3

info "Restarting forge-worker..."
docker compose up -d forge-worker

info "Restarting forge-dashboard..."
docker compose up -d forge-dashboard

# ---------------------------------------------------------------------------
# 6. Health checks
# ---------------------------------------------------------------------------
header "Health Checks"

wait_for_health() {
    local name=$1 url=$2 max=${3:-20}
    local attempt=0
    while ! curl -sf "$url" > /dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge "$max" ]; then
            echo -e "  ${RED}✗${NC} $name (timeout after ${max} attempts)"
            return 1
        fi
        sleep 3
    done
    echo -e "  ${GREEN}✓${NC} $name"
}

ALL_OK=true

wait_for_health "Auth Service"  "http://localhost:3100/health"   15 || ALL_OK=false
wait_for_health "API Server"    "http://localhost:8000/api/health" 15 || ALL_OK=false
wait_for_health "Dashboard"     "http://localhost:3000"           10 || ALL_OK=false
wait_for_health "Temporal UI"   "http://localhost:8088"           10 || ALL_OK=false

# Check worker is running (no HTTP endpoint, check container status)
if docker compose ps forge-worker --format '{{.State}}' 2>/dev/null | grep -q running; then
    echo -e "  ${GREEN}✓${NC} Worker"
else
    echo -e "  ${RED}✗${NC} Worker"
    ALL_OK=false
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
if [ "$ALL_OK" = true ]; then
    header "Deploy Complete"
    info "All services healthy"
    info "Dashboard: http://localhost:3000"
else
    header "Deploy Finished with Warnings"
    warn "Some services failed health checks — check logs:"
    warn "  docker compose logs <service-name>"
fi
echo ""
