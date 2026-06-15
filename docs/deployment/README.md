# Deployment Guide

## Overview

MetaPilot supports multiple deployment targets:

| Target | Use Case |
|---|---|
| Docker Compose (dev) | Local development |
| Railway | Quick cloud deployment |
| Dokploy + VPS | Self-hosted production |
| Kubernetes | Large-scale production |

---

## Railway Deployment

Railway is the fastest way to deploy MetaPilot to production.

### 1. Install Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### 2. Create Services

```bash
# Create project
railway init

# Deploy API
railway up --service api --dir apps/api/

# Deploy Web
railway up --service dashboard-web --dir apps/
```

### 3. Required Environment Variables (API)

Set these in Railway dashboard → Variables:

```
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(50))">
DATABASE_URL=<PostgreSQL URL — Railway provides this>
CELERY_BROKER_URL=<Redis URL — Railway provides this>
CELERY_RESULT_BACKEND=<same Redis URL>
CHANNEL_REDIS_URL=<same Redis URL>
FERNET_KEY=<generate with Fernet>
ALLOWED_HOSTS=<your-domain.railway.app>
DEBUG=False
OPENROUTER_API_KEY=<your key>
META_GRAPH_API_VERSION=v22.0
WEBHOOK_BASE_URL=https://your-domain.railway.app
```

### 4. Required Environment Variables (Web)

```
NEXT_PUBLIC_API_URL=https://your-api-domain.railway.app
NEXT_PUBLIC_WS_URL=wss://your-api-domain.railway.app
```

---

## Dokploy / Self-Hosted VPS

### Prerequisites
- Ubuntu 22.04+ VPS
- Docker + Docker Compose installed
- Domain with DNS pointing to server

### Steps

```bash
# 1. Clone repo on server
git clone https://github.com/omghante/metapilot.git
cd metapilot

# 2. Configure environment
cp .env.example .env
nano .env  # Fill in production values

# 3. Start production stack
docker compose -f infra/docker/production/docker-compose.yml up -d

# 4. Run migrations
docker exec metapilot-api python manage.py migrate

# 5. Create superuser
docker exec -it metapilot-api python manage.py createsuperuser
```

---

## Health Checks

```bash
# API health
curl https://your-domain.com/health/
# Expected: {"status": "healthy", "version": "1.0.0"}

# WebSocket health
wscat -c wss://your-domain.com/ws/inbox/test/?token=<jwt>
```

---

## Scaling Workers

```bash
# Start multiple Celery workers
docker compose -f infra/docker/production/docker-compose.yml up -d --scale worker=4
```

See [docs/scaling/](../scaling/) for full horizontal scaling guide.
