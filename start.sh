#!/usr/bin/env bash
set -euo pipefail

echo "== LetzIT start =="
echo "PWD: $(pwd)"
echo "Listing root:"
ls -la

echo "Running alembic upgrade head..."
alembic -c alembic.ini upgrade head

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
