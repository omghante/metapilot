#!/bin/bash
# scripts/setup.sh
# Bootstrap MetaPilot development environment from scratch
# Usage: bash scripts/setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "  MetaPilot — Dev Environment Setup"
echo "  ──────────────────────────────────"
echo ""

# Copy root env
if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "✅ Created .env from .env.example"
  echo "   ⚠️  Edit .env and set FERNET_KEY before starting"
else
  echo "✓  .env already exists"
fi

# Copy API env
if [ ! -f "$ROOT/services/api/.env" ]; then
  cp "$ROOT/services/api/.env.example" "$ROOT/services/api/.env"
  echo "✅ Created services/api/.env"
fi

# Copy Web env
if [ ! -f "$ROOT/apps/.env.local" ]; then
  cp "$ROOT/apps/.env.example" "$ROOT/apps/.env.local"
  echo "✅ Created apps/.env.local"
fi

# Backend Python env
echo ""
echo "→ Setting up Python virtual environment..."
cd "$ROOT/services/api"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Python dependencies installed"

# Frontend Node env
echo ""
echo "→ Installing Node dependencies..."
cd "$ROOT/apps"
yarn install --frozen-lockfile -s
echo "✅ Node dependencies installed"

echo ""
echo "✅ Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Fill in FERNET_KEY in services/api/.env"
echo "  2. Run: make dev"
echo ""
