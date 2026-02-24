#!/bin/bash
set -euo pipefail

echo "🗄️  Running Forge database migrations..."

# Wait for PostgreSQL
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER"; do
  echo "Waiting for PostgreSQL..."
  sleep 2
done

# Run base schema
echo "Running base schema..."
psql "$DATABASE_URL" -f /app/infrastructure/init-db.sql

# Run migrations in order
for migration in /app/infrastructure/migrations/*.sql; do
  if [ -f "$migration" ]; then
    FILENAME=$(basename "$migration")
    # Check if already applied
    APPLIED=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM _migrations WHERE filename = '$FILENAME'" 2>/dev/null || echo "0")
    if [ "$(echo $APPLIED | tr -d ' ')" = "0" ]; then
      echo "Applying: $FILENAME"
      psql "$DATABASE_URL" -f "$migration"
      psql "$DATABASE_URL" -c "INSERT INTO _migrations (filename) VALUES ('$FILENAME')"
    else
      echo "Already applied: $FILENAME (skipping)"
    fi
  fi
done

echo "✅ Migrations complete"
