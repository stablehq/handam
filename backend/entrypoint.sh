#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head || echo "WARNING: Alembic migration failed"

echo "Starting gunicorn..."
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w "${GUNICORN_WORKERS:-1}" \
    -b 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
