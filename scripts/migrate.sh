#!/bin/bash
set -euo pipefail

# Resolve paths relative to the repo root (works locally and in Docker)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🗄️  Running Forge database migrations..."

# Extract host/port from DATABASE_URL for pg_isready
# DATABASE_URL format: postgresql://user:pass@host:port/dbname
if [ -n "${DATABASE_URL:-}" ]; then
  DB_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:]*\):.*|\1|p')
  DB_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
  DB_USER=$(echo "$DATABASE_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')

  echo "Connecting to $DB_HOST:$DB_PORT as $DB_USER..."
  until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" 2>/dev/null; do
    echo "Waiting for PostgreSQL..."
    sleep 2
  done
else
  echo "ERROR: DATABASE_URL is not set"
  exit 1
fi

# Run base schema
echo "Running base schema..."
psql "$DATABASE_URL" -f "$REPO_ROOT/infrastructure/init-db.sql"

# Run migrations in order
for migration in "$REPO_ROOT"/infrastructure/migrations/*.sql; do
  if [ -f "$migration" ]; then
    FILENAME=$(basename "$migration")
    # Check if already applied
    APPLIED=$(psql "$DATABASE_URL" -t -c \
      "SELECT COUNT(*) FROM _migrations WHERE filename = '$FILENAME'" \
      2>/dev/null || echo "0")
    if [ "$(echo $APPLIED | tr -d ' ')" = "0" ]; then
      echo "Applying: $FILENAME"
      psql "$DATABASE_URL" -f "$migration"
      psql "$DATABASE_URL" -c \
        "INSERT INTO _migrations (filename) VALUES ('$FILENAME')"
    else
      echo "Already applied: $FILENAME (skipping)"
    fi
  fi
done

echo "✅ Migrations complete"
