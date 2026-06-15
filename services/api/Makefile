# ============================================================
# apps/api — Makefile (backend-specific commands)
# ============================================================
.PHONY: setup dev test lint format migrate shell seed worker beat

PYTHON := python
CELERY := celery -A core

# ── Setup ────────────────────────────────────────────────────
setup:
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo "✅ Backend setup complete. Activate with: source .venv/bin/activate"

# ── Development ──────────────────────────────────────────────
dev:
	daphne -b 0.0.0.0 -p 8000 core.asgi:application

worker:
	$(CELERY) worker -Q celery,scheduler,jobs --loglevel=info --concurrency=4

beat:
	$(CELERY) beat --scheduler django_celery_beat.schedulers:DatabaseScheduler --loglevel=info

shell:
	$(PYTHON) manage.py shell

# ── Database ─────────────────────────────────────────────────
migrate:
	$(PYTHON) manage.py migrate --no-input

makemigrations:
	$(PYTHON) manage.py makemigrations

seed:
	$(PYTHON) manage.py seed_dev_data 2>/dev/null || echo "No seed command found"

# ── Testing ──────────────────────────────────────────────────
test:
	pytest --cov=. --cov-report=term-missing -v

test-unit:
	pytest -m unit -v

test-integration:
	pytest -m integration -v

# ── Code Quality ─────────────────────────────────────────────
lint:
	ruff check .
	mypy . --ignore-missing-imports 2>/dev/null || true

format:
	ruff format .
	ruff check --fix .
