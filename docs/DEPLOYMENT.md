# Deployment Guide

> How to run MetaPilot locally, in Docker, and in production.

---

## Local Development (No Docker)

### Prerequisites

- Python 3.11+
- PostgreSQL 16
- Redis 7
- Node.js 20+ (for dashboard)

### Step 1: Clone and Configure

```bash
git clone https://github.com/omghante/metapilot.git
cd metapilot

# Copy environment file
cp .env.example .env
# Edit .env with your database credentials, Redis URL, and Fernet key
```

### Step 2: Set Up the API

```bash
cd services/api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create super admin
python manage.py shell -c "
from users.models import User
User.objects.create_superuser(
    email='admin@example.com',
    password='admin123',
    role='SUPER_ADMIN'
)
"
```

### Step 3: Start Services

You need **4 terminal windows**:

```bash
# Terminal 1: API Server (HTTP + WebSocket)
daphne -b 0.0.0.0 -p 8000 core.asgi:application

# Terminal 2: Celery Worker (background tasks)
celery -A core worker -l info --concurrency=4

# Terminal 3: Celery Beat (periodic tasks — scheduler heartbeat)
celery -A core beat -l info

# Terminal 4: Dashboard (optional)
cd apps/dashboard
npm install
npm run dev
```

### Using the Makefile

The Makefile provides shortcuts for common tasks:

```bash
# Start everything
make dev

# Run API only
make api

# Run Celery worker
make worker

# Run Celery Beat
make beat

# Run migrations
make migrate

# Create migrations
make migrations

# Run tests
make test

# Run linter
make lint

# Open Django shell
make shell

# View API logs
make logs
```

---

## Docker Development

### Prerequisites

- Docker 24+
- Docker Compose v2

### Quick Start

```bash
# Start all services
make docker-up
# or
docker compose -f infrastructure/docker/development/docker-compose.yml up -d

# View logs
docker compose -f infrastructure/docker/development/docker-compose.yml logs -f

# Stop
make docker-down
```

### Docker Compose Services

```yaml
services:
  # PostgreSQL 16 — Primary database
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: metapilot
      POSTGRES_USER: metapilot
      POSTGRES_PASSWORD: metapilot
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Redis 7 — Message broker + Channel layer + Rate limiter
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # Django API (Daphne ASGI — handles HTTP + WebSocket)
  api:
    build:
      context: ../../..
      dockerfile: infrastructure/docker/development/Dockerfile.api
    command: daphne -b 0.0.0.0 -p 8000 core.asgi:application
    ports:
      - "8000:8000"
    volumes:
      - ./services/api:/app
    depends_on:
      - db
      - redis
    env_file:
      - .env

  # Celery Worker — Background job processing
  celery-worker:
    build: ...
    command: celery -A core worker -l info --concurrency=4
    depends_on:
      - db
      - redis

  # Celery Beat — Periodic task scheduler
  celery-beat:
    build: ...
    command: celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    depends_on:
      - db
      - redis

  # Dashboard (Next.js)
  dashboard:
    build:
      context: apps/dashboard
    command: npm run dev
    ports:
      - "3000:3000"
    depends_on:
      - api
```

### Why Daphne Instead of Gunicorn?

MetaPilot uses **Daphne** (ASGI) instead of the more common **Gunicorn** (WSGI) because:

1. **WebSocket support** — Gunicorn can't handle WebSocket connections. Daphne handles both HTTP and WebSocket on the same port.
2. **Django Channels** — The inbox system requires ASGI for real-time communication.
3. **Single port** — No need to run a separate WebSocket server.

```
# Gunicorn (WSGI) — can NOT do this:
ws://localhost:8000/ws/inbox/123/  ← Would fail

# Daphne (ASGI) — handles both:
http://localhost:8000/api/contacts/  ← HTTP works
ws://localhost:8000/ws/inbox/123/    ← WebSocket works
```

---

## Production Deployment

### Architecture

```
                    ┌─────────────────┐
                    │   Cloudflare    │
                    │   (CDN + WAF)   │
                    └────────┬────────┘
                             │ HTTPS
                    ┌────────▼────────┐
                    │     Nginx       │
                    │  (Reverse Proxy)│
                    │  Port 80/443    │
                    └───┬─────────┬───┘
                        │         │
               HTTP     │         │  WebSocket
               /api/*   │         │  /ws/*
                        │         │
                    ┌───▼─────────▼───┐
                    │    Daphne       │
                    │   ASGI Server   │
                    │   Port 8000     │
                    └───┬─────────┬───┘
                        │         │
              ┌─────────▼──┐  ┌──▼──────────┐
              │ PostgreSQL  │  │   Redis     │
              │ (Managed)   │  │  (Managed)  │
              └─────────────┘  └─────────────┘
```

### Nginx Configuration

```nginx
upstream daphne {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name api.metapilot.io;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.metapilot.io;

    ssl_certificate /etc/letsencrypt/live/api.metapilot.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.metapilot.io/privkey.pem;

    # HTTP requests → Daphne
    location /api/ {
        proxy_pass http://daphne;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket requests → Daphne
    location /ws/ {
        proxy_pass http://daphne;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;  # 24 hours for long-lived connections
    }

    # Webhook endpoint (public, no auth)
    location /api/webhooks/ {
        proxy_pass http://daphne;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Static files
    location /static/ {
        alias /app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Production Checklist

```bash
# 1. Environment
DEBUG=False
SECRET_KEY=<64-char-random-string>
ALLOWED_HOSTS=api.metapilot.io
FERNET_KEY=<generate-new-key>

# 2. Database
DATABASE_URL=postgresql://user:pass@db-host:5432/metapilot

# 3. Redis
CELERY_BROKER_URL=redis://redis-host:6379/0
CHANNEL_REDIS_URL=redis://redis-host:6379/1

# 4. Collect static files
python manage.py collectstatic --noinput

# 5. Run migrations
python manage.py migrate --noinput

# 6. Start services
daphne -b 0.0.0.0 -p 8000 core.asgi:application
celery -A core worker -l warning --concurrency=8
celery -A core beat -l warning
```

### Systemd Service Files

```ini
# /etc/systemd/system/metapilot-api.service
[Unit]
Description=MetaPilot API (Daphne)
After=network.target postgresql.service redis.service

[Service]
User=metapilot
WorkingDirectory=/opt/metapilot/services/api
Environment="PATH=/opt/metapilot/venv/bin"
ExecStart=/opt/metapilot/venv/bin/daphne -b 0.0.0.0 -p 8000 core.asgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/metapilot-worker.service
[Unit]
Description=MetaPilot Celery Worker
After=network.target postgresql.service redis.service

[Service]
User=metapilot
WorkingDirectory=/opt/metapilot/services/api
Environment="PATH=/opt/metapilot/venv/bin"
ExecStart=/opt/metapilot/venv/bin/celery -A core worker -l warning --concurrency=8
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/metapilot-beat.service
[Unit]
Description=MetaPilot Celery Beat
After=network.target postgresql.service redis.service

[Service]
User=metapilot
WorkingDirectory=/opt/metapilot/services/api
Environment="PATH=/opt/metapilot/venv/bin"
ExecStart=/opt/metapilot/venv/bin/celery -A core beat -l warning
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and start:
```bash
sudo systemctl enable metapilot-api metapilot-worker metapilot-beat
sudo systemctl start metapilot-api metapilot-worker metapilot-beat
```

---

## Monitoring

### Prometheus + Grafana (Optional)

The infrastructure includes pre-configured monitoring:

```bash
# Start monitoring stack
docker compose -f infrastructure/monitoring/docker-compose.yml up -d

# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3001 (admin/admin)
```

### Health Checks

```bash
# Basic health
curl http://localhost:8000/health/
# {"status": "healthy", "version": "1.0.0"}

# Full system check
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/requirements/
# Checks: database, redis, celery workers
```

### Log Management

```python
# Django logging configuration
LOGGING = {
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
        'file': {
            'class': 'logging.FileHandler',
            'filename': '/var/log/metapilot/api.log',
        },
    },
    'loggers': {
        'messaging': {'level': 'INFO'},
        'scheduler': {'level': 'INFO'},
        'webhooks': {'level': 'WARNING'},
        'inbox': {'level': 'INFO'},
    }
}
```

---

## Scaling

| Component | How to Scale |
|-----------|-------------|
| **API (Daphne)** | Run multiple instances behind Nginx load balancer. Redis channel layer handles cross-instance WebSocket. |
| **Celery Workers** | Increase `--concurrency` or add more worker processes. Jobs are claimed via `SELECT FOR UPDATE SKIP LOCKED`. |
| **PostgreSQL** | Read replicas for dashboard queries. Primary for writes. |
| **Redis** | Redis Sentinel or Redis Cluster for HA. Separate instances for broker vs. channel layer. |

### Horizontal Scaling Example

```
                    Nginx (Load Balancer)
                    ┌─────────┼─────────┐
                    │         │         │
                Daphne-1  Daphne-2  Daphne-3
                    │         │         │
                    └─────────┼─────────┘
                              │
                    ┌─────────┼─────────┐
                    │         │         │
                Worker-1  Worker-2  Worker-3
                    │         │         │
                    └─────────┼─────────┘
                              │
                    ┌─────────┼─────────┐
                    │                   │
                PostgreSQL            Redis
                (Primary)           (Cluster)
```

WebSocket messages are delivered correctly across instances because **Redis pub/sub** (via Django Channels) broadcasts to all connected Daphne instances.
