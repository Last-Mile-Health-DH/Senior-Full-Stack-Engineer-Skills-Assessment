#!/bin/bash
set -euo pipefail

# Bring the schema up to head before serving.
#
# Without this, a reviewer with a fresh database volume gets a backend that starts
# "successfully" and then 500s on every request, because no tables exist. Running it here
# (once, before gunicorn forks its workers) makes `docker compose up` sufficient on its own.
#
# In production this belongs in a separate one-off migration task ordered before the
# rollout, not in the app entrypoint -- see DEPLOYMENT.md. Alembic takes a lock, so
# concurrent replicas are safe, but a failed migration should fail the deploy rather than
# each container independently.
echo "Running database migrations..."
alembic upgrade head

echo "Starting API on port ${PORT:-6100}..."
exec gunicorn -k uvicorn.workers.UvicornWorker -w "${WEB_CONCURRENCY:-4}" -b "0.0.0.0:${PORT:-6100}" --preload app.main:app --timeout 120 --keep-alive 120 --log-level info
