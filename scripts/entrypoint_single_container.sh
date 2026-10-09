#!/usr/bin/env bash
set -euo pipefail

# Wait for Postgres to be ready
echo "[entrypoint] waiting for postgres..."
until pg_isready -h postgres -U "${DB_USER:-postgres}" -d NexusQuantDB; do
  echo "[entrypoint] postgres is unavailable - sleeping"
  sleep 2
done
echo "[entrypoint] postgres is up - executing schema check"

# Explicitly run the schema script as a fallback
# (In case the volume was already initialized and docker-entrypoint-initdb.d skipped)
export PGPASSWORD="${DB_PASSWORD:-postgres}"
psql -h postgres -U "${DB_USER:-postgres}" -d NexusQuantDB -f ./scripts/init_schema.sql
psql -h postgres -U "${DB_USER:-postgres}" -d NexusQuantDB -f ./scripts/migration_add_notifications.sql

PIDS=()

start_process() {
  local name="$1"
  shift

  echo "[entrypoint] starting ${name}: $*"
  "$@" &
  local pid=$!
  PIDS+=("${pid}")
  echo "[entrypoint] ${name} pid=${pid}"
}

shutdown() {
  echo "[entrypoint] shutting down child processes"
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  wait || true
}

trap shutdown SIGINT SIGTERM

start_process "uvicorn-api" uvicorn Main:App --host 0.0.0.0 --port 8000
start_process "ingestion-worker" celery -A shared.infrastructure.CeleryApp worker -Q ingestion -c 2 --loglevel=info
start_process "beat-scheduler" celery -A shared.infrastructure.CeleryApp beat --loglevel=info
start_process "options-subscriber" python -m domains.analytics.infrastructure.options_subscriber

set +e
wait -n
exit_code=$?
set -e

echo "[entrypoint] a child process exited with code ${exit_code}; stopping remaining processes"
shutdown
exit "${exit_code}"
