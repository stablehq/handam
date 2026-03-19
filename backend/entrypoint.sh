#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head 2>/dev/null || echo "Alembic migration skipped (not initialized or no migrations)"

echo "Starting gunicorn..."
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w "${GUNICORN_WORKERS:-1}" \
    -b 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
