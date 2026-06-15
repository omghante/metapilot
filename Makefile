# ============================================================
# MetaPilot Monorepo — Makefile
# ============================================================
.PHONY: help setup dev stop test lint format build clean logs

# Default target
help:
	@echo ""
	@echo "  MetaPilot Monorepo"
	@echo "  ─────────────────────────────────────────"
	@echo "  make setup       Bootstrap all services"
	@echo "  make dev         Start all services (dev)"
	@echo "  make stop        Stop all services"
	@echo "  make test        Run all tests"
	@echo "  make lint        Lint all code"
	@echo "  make format      Auto-format all code"
	@echo "  make build       Build production images"
	@echo "  make logs        Tail all service logs"
	@echo "  make clean       Remove generated artifacts"
	@echo "  make migrate     Run Django migrations"
	@echo "  make seed        Seed development database"
	@echo "  make shell       Open Django shell"
	@echo "  make worker      Start Celery worker only"
	@echo "  make beat        Start Celery beat only"
	@echo ""

# ── Bootstrap ────────────────────────────────────────────────

setup:
	@echo "→ Setting up MetaPilot development environment..."
	cp -n .env.example .env || true
	$(MAKE) -C services/api setup
	$(MAKE) -C apps setup
	@echo "✅ Setup complete. Run 'make dev' to start."

# ── Development ──────────────────────────────────────────────

dev:
	docker compose -f infrastructure/docker/development/docker-compose.yml up --build

dev-api:
	$(MAKE) -C services/api dev

dev-web:
	$(MAKE) -C apps dev

stop:
	docker compose -f infrastructure/docker/development/docker-compose.yml down

worker:
	$(MAKE) -C services/api worker

beat:
	$(MAKE) -C services/api beat

shell:
	$(MAKE) -C services/api shell

# ── Database ─────────────────────────────────────────────────

migrate:
	$(MAKE) -C services/api migrate

makemigrations:
	$(MAKE) -C services/api makemigrations

seed:
	$(MAKE) -C services/api seed

# ── Testing ──────────────────────────────────────────────────

test:
	$(MAKE) test-api
	$(MAKE) test-web
	$(MAKE) test-integration

test-api:
	$(MAKE) -C services/api test

test-web:
	$(MAKE) -C apps test

test-integration:
	cd tests/integration && python -m pytest -v

test-load:
	cd tests/load && python -m pytest -v

test-e2e:
	cd tests/e2e && npx playwright test

# ── Code Quality ─────────────────────────────────────────────

lint:
	$(MAKE) -C services/api lint
	$(MAKE) -C apps lint

format:
	$(MAKE) -C services/api format
	$(MAKE) -C apps format

typecheck:
	$(MAKE) -C apps typecheck

# ── Build ────────────────────────────────────────────────────

build:
	docker compose -f infrastructure/docker/production/docker-compose.yml build

build-api:
	docker build -t metapilot-api:latest services/api/

build-web:
	docker build -t metapilot-web:latest apps/

# ── Observability ────────────────────────────────────────────

logs:
	docker compose -f infrastructure/docker/development/docker-compose.yml logs -f

logs-api:
	docker compose -f infrastructure/docker/development/docker-compose.yml logs -f api

logs-worker:
	docker compose -f infrastructure/docker/development/docker-compose.yml logs -f worker

# ── Cleanup ──────────────────────────────────────────────────

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".ruff_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".mypy_cache" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name ".next" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "node_modules" -type d -prune 2>/dev/null | head -5
	@echo "✅ Clean complete"
