#!/bin/bash
# scripts/dashboard.sh
# Start the Next.js dashboard for local development
# Usage: bash scripts/dashboard.sh [--build | --start]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="$ROOT/apps"

cd "$WEB_DIR"

case "${1:-dev}" in
  --build)
    echo "→ Building Next.js for production..."
    yarn build
    ;;
  --start)
    echo "→ Starting Next.js in production mode..."
    yarn start
    ;;
  dev)
    echo "→ Starting Next.js dev server on :3000..."
    yarn dev
    ;;
esac
