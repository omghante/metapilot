#!/bin/bash
# database/scripts/migrate.sh
# Runs Django migrations inside the API service
# Usage: bash database/scripts/migrate.sh [--check]

set -euo pipefail

cd "$(dirname "$0")/../../services/api"

if [[ "${1:-}" == "--check" ]]; then
  echo "→ Checking pending migrations..."
  python manage.py migrate --check
else
  echo "→ Running migrations..."
  python manage.py migrate --no-input
  echo "✅ Migrations complete"
fi
