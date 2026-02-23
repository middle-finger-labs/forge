#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Forge E2E Test Orchestrator
#
# Starts the full infrastructure stack, runs the end-to-end test suite,
# captures logs, prints a summary, and cleans up.
#
# Usage:
#   scripts/run_e2e.sh              # default: run all e2e tests
#   scripts/run_e2e.sh -k budget    # pass extra pytest flags
#   KEEP_INFRA=1 scripts/run_e2e.sh # skip docker compose down on exit
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/.e2e-logs"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# Configurable timeouts (seconds)
SERVICE_TIMEOUT="${SERVICE_TIMEOUT:-120}"
WORKER_READY_WAIT="${WORKER_READY_WAIT:-10}"
API_READY_WAIT="${API_READY_WAIT:-10}"

# PIDs to clean up
WORKER_PID=""
API_PID=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { printf "\033[1;36m[e2e]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[e2e]\033[0m %s\n" "$*"; }
error() { printf "\033[1;31m[e2e]\033[0m %s\n" "$*"; }
ok()    { printf "\033[1;32m[e2e]\033[0m %s\n" "$*"; }

wait_for_port() {
    local host="$1" port="$2" label="$3"
    local deadline=$(( $(date +%s) + SERVICE_TIMEOUT ))
    info "Waiting for $label ($host:$port)..."
    while ! nc -z "$host" "$port" 2>/dev/null; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
            error "$label did not become available within ${SERVICE_TIMEOUT}s"
            return 1
        fi
        sleep 2
    done
    ok "$label is ready"
}

wait_for_http() {
    local url="$1" label="$2"
    local deadline=$(( $(date +%s) + SERVICE_TIMEOUT ))
    info "Waiting for $label ($url)..."
    while ! curl -sf "$url" >/dev/null 2>&1; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
            error "$label did not become available within ${SERVICE_TIMEOUT}s"
            return 1
        fi
        sleep 2
    done
    ok "$label is ready"
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

cleanup() {
    local exit_code=$?
    info "Cleaning up..."

    # Stop worker
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        info "Stopping worker (PID $WORKER_PID)"
        kill "$WORKER_PID" 2>/dev/null || true
        wait "$WORKER_PID" 2>/dev/null || true
    fi

    # Stop API
    if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
        info "Stopping API server (PID $API_PID)"
        kill "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
    fi

    # Docker compose down (unless KEEP_INFRA is set)
    if [ "${KEEP_INFRA:-0}" != "1" ]; then
        info "Tearing down docker compose..."
        docker compose -f "$COMPOSE_FILE" down --timeout 10 2>/dev/null || true
    else
        warn "KEEP_INFRA=1 — leaving docker compose running"
    fi

    # Summary
    echo
    echo "============================================================"
    if [ "$exit_code" -eq 0 ]; then
        ok "E2E tests PASSED"
    else
        error "E2E tests FAILED (exit code $exit_code)"
    fi
    echo "  Logs: $LOG_DIR/"
    echo "============================================================"
    echo

    exit "$exit_code"
}

trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

cd "$PROJECT_ROOT"

# Create log directory
mkdir -p "$LOG_DIR"
info "Logs will be written to $LOG_DIR/"

# -- 1. Start docker compose -----------------------------------------------

info "Starting docker compose..."
docker compose -f "$COMPOSE_FILE" up -d 2>&1 | tee "$LOG_DIR/docker-compose.log"

# -- 2. Wait for services ---------------------------------------------------

wait_for_port localhost 5432 "PostgreSQL"
wait_for_port localhost 6379 "Redis"
wait_for_port localhost 7233 "Temporal"

# -- 3. Start worker in background ------------------------------------------

info "Starting Temporal worker..."
python -m worker > "$LOG_DIR/worker.log" 2>&1 &
WORKER_PID=$!
info "Worker started (PID $WORKER_PID)"
sleep "$WORKER_READY_WAIT"

# Verify worker is still alive
if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    error "Worker process died — check $LOG_DIR/worker.log"
    cat "$LOG_DIR/worker.log"
    exit 1
fi
ok "Worker is running"

# -- 4. Start API server in background --------------------------------------

info "Starting API server..."
python -m api.run > "$LOG_DIR/api.log" 2>&1 &
API_PID=$!
info "API server started (PID $API_PID)"

wait_for_http "http://localhost:8000/api/health" "API server"

# -- 5. Run the e2e tests ---------------------------------------------------

info "Running E2E tests..."
echo

FORGE_E2E=1 python -m pytest tests/test_e2e_production.py \
    -v \
    --timeout=600 \
    --tb=short \
    "$@" \
    2>&1 | tee "$LOG_DIR/pytest.log"

TEST_EXIT=${PIPESTATUS[0]}

# -- 6. Capture service logs -------------------------------------------------

info "Capturing service logs..."
docker compose -f "$COMPOSE_FILE" logs --no-color > "$LOG_DIR/docker-services.log" 2>&1 || true

# Copy last 100 lines of each log for the summary
echo
info "=== Worker log (last 50 lines) ==="
tail -n 50 "$LOG_DIR/worker.log" 2>/dev/null || true
echo
info "=== API log (last 50 lines) ==="
tail -n 50 "$LOG_DIR/api.log" 2>/dev/null || true
echo

exit "$TEST_EXIT"
