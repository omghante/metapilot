#!/bin/bash
# scripts/backend.sh
# Start the Django API server and all background services for local dev
# Usage: bash scripts/backend.sh [--worker-only | --beat-only]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/services/api"

cd "$API_DIR"

# Activate venv if it exists
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

case "${1:-all}" in
  --worker-only)
    echo "→ Starting Celery worker..."
    celery -A core worker -Q celery,scheduler,jobs --loglevel=info --concurrency=4
    ;;
  --beat-only)
    echo "→ Starting Celery beat..."
    celery -A core beat \
      --scheduler django_celery_beat.schedulers:DatabaseScheduler \
      --loglevel=info
    ;;
  all)
    echo "→ Running migrations..."
    python manage.py migrate --no-input

    echo "→ Starting Daphne ASGI server on :8000..."
    daphne -b 0.0.0.0 -p 8000 core.asgi:application
    ;;
esac
