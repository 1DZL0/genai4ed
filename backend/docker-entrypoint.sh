#!/bin/sh
set -e

# The schema is owned by Alembic, so bring the database to head before serving.
# Idempotent: on an already-current database this is a no-op.
echo "applying migrations..."
uv run alembic upgrade head

echo "starting api on :8000"
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
