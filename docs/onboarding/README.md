# Developer Onboarding Guide

Welcome to MetaPilot! This guide will get you from zero to a running dev environment.

---

## Prerequisites

Install these before starting:

| Tool | Version | Install |
|---|---|---|
| Python | 3.12+ | [python.org](https://python.org) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |
| Docker | 24+ | [docker.com](https://docker.com) |
| Git | 2.40+ | [git-scm.com](https://git-scm.com) |
| `uv` (optional) | latest | `pip install uv` |

---

## 1. Clone & Configure

```bash
git clone https://github.com/omghante/metapilot.git
cd metapilot

# Copy environment template
cp .env.example .env
```

Edit `.env` and fill in at minimum:
- `FERNET_KEY` — generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `OPENROUTER_API_KEY` — for AI chatbot features (optional for basic dev)

---

## 2. Option A — Docker (Recommended)

```bash
# Start everything (Postgres, Redis, API, Worker, Beat, Web)
make dev
```

Services will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/api/docs/
- **Dashboard**: http://localhost:3000
- **Django Admin**: http://localhost:8000/admin/

---

## 3. Option B — Manual (Faster iteration)

### Backend Setup

```bash
cd apps/api

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start API server
daphne -b 0.0.0.0 -p 8000 core.asgi:application
```

### Start Celery (separate terminals)

```bash
# Worker
celery -A core worker -Q celery,scheduler,jobs --loglevel=info

# Beat scheduler
celery -A core beat --scheduler django_celery_beat.schedulers:DatabaseScheduler --loglevel=info
```

### Frontend Setup

```bash
cd apps

# Install dependencies
yarn install

# Start dev server
yarn dev
```

---

## 4. First-Time Setup

After starting the API:

1. Open http://localhost:8000/admin/ and log in
2. Create an Agency record
3. Create a Tenant record under the agency
4. Add a WhatsApp Business config to the tenant

Or use the Setup Wizard at `/api/setup/`.

---

## 5. Project Structure Quick Reference

```
apps/api/         → Django backend (all Python code)
apps/ → Next.js frontend (all TypeScript code)
infra/            → Docker, K8s, Terraform configs
docs/             → All engineering documentation
tests/            → Integration, load, e2e tests
```

---

## 6. Common Commands

```bash
make test          # Run all tests
make lint          # Lint all code
make migrate       # Apply DB migrations
make shell         # Open Django shell
make logs          # Tail Docker logs
make clean         # Remove cache files
```

---

## 7. Useful API Endpoints (Dev)

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/login/` | Get JWT token |
| `GET /api/docs/` | Swagger API docs |
| `GET /health/` | Health check |
| `GET /api/dashboard/` | Dashboard stats |
| `GET /inbox/conversations/` | List conversations |

---

## 8. Getting Help

- Read [ARCHITECTURE.md](../../ARCHITECTURE.md) for system design
- Check [docs/development/](../development/) for dev guides
- Open a [GitHub Discussion](https://github.com/omghante/metapilot/discussions) for questions
