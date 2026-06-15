<p align="center">
  <h1 align="center">⚡ MetaPilot</h1>
  <p align="center">
    <strong>Production-Grade Multi-Tenant WhatsApp Marketing & Automation Platform</strong>
  </p>
  <p align="center">
    Built with Django 5 · Celery · Django Channels · Redis · PostgreSQL · OpenRouter AI
  </p>
</p>

---

## What is MetaPilot?

MetaPilot is a **full-stack SaaS platform** that allows agencies and businesses to manage WhatsApp marketing at scale. Think of it as a **white-label WhatsApp CRM** — agencies onboard clients, each client gets their own isolated WhatsApp Business account, contacts, campaigns, and analytics.

The platform handles everything from **sending bulk template messages** to **receiving real-time customer replies via WebSocket**, **AI-powered auto-reply chatbots**, and **scheduled campaign delivery with retry logic**.

### Why I Built This

I wanted to solve a real-world problem: businesses need to communicate with customers on WhatsApp, but Meta's API is complex. MetaPilot abstracts that complexity behind a clean REST API and dashboard, while handling the hard parts — multi-tenancy, rate limiting, message scheduling, webhook processing, and credential encryption — behind the scenes.

---

## Platform Capabilities

| Domain | What It Does | Key Technical Detail |
|---|---|---|
| **Multi-Tenancy** | Agency → Client hierarchy with isolated data | Middleware-based tenant resolution from JWT |
| **Messaging** | Send text, image, document, template messages | Meta Graph API v22.0 integration |
| **Campaigns** | Bulk scheduled campaigns with tag-based targeting | Celery Beat + distributed job scheduler |
| **Scheduler** | High-performance async message delivery | Token-bucket rate limiter + `SELECT FOR UPDATE SKIP LOCKED` |
| **Templates** | Create, sync, and manage WhatsApp templates | Auto-sync from Meta API every 5 minutes |
| **Inbox** | Real-time two-way WhatsApp conversations | Django Channels WebSocket + Redis pub/sub |
| **AI Chatbot** | Customer-facing auto-reply bot | OpenRouter (GPT-4o vision + Step-3.5-Flash text) |
| **Webhooks** | Process incoming messages from Meta | HMAC-SHA256 signature verification |
| **Analytics** | Delivery rates, read rates, campaign stats | Per-message latency tracking |
| **Notifications** | Role-based in-app notification system | Priority levels + read tracking |
| **Security** | Fernet-encrypted API keys, GDPR deletion | AES-256 encryption, audit logging |

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────┐
                    │           Next.js Dashboard             │
                    │      (React 19 + TypeScript + TW4)      │
                    └──────────────┬──────────────────────────┘
                                   │ REST + WebSocket
                    ┌──────────────▼──────────────────────────┐
                    │         Django API (Daphne ASGI)         │
                    │   ┌─────────────────────────────────┐   │
                    │   │  JWT Auth + Tenant Middleware    │   │
                    │   └─────────────────────────────────┘   │
                    │   ┌───────┐ ┌────────┐ ┌───────────┐   │
                    │   │ Users │ │Tenants │ │ Campaigns │   │
                    │   └───────┘ └────────┘ └───────────┘   │
                    │   ┌───────────┐ ┌────────┐ ┌───────┐   │
                    │   │ Messaging │ │ Inbox  │ │ Sched │   │
                    │   └───────────┘ └────────┘ └───────┘   │
                    │   ┌──────────┐ ┌─────────┐ ┌───────┐   │
                    │   │Templates │ │Webhooks │ │Chatbot│   │
                    │   └──────────┘ └─────────┘ └───────┘   │
                    └──┬───────────┬──────────────┬───────────┘
                       │           │              │
              ┌────────▼──┐  ┌─────▼────┐  ┌──────▼─────┐
              │ PostgreSQL │  │  Redis   │  │ Meta Graph │
              │   (Data)   │  │(Broker + │  │  API v22   │
              │            │  │ Channels)│  │            │
              └────────────┘  └──────────┘  └────────────┘
```

### Service Architecture

| Service | Role | Port |
|---|---|---|
| **Daphne (ASGI)** | HTTP + WebSocket server | 8000 |
| **Celery Worker** | Background job processing | — |
| **Celery Beat** | Periodic task scheduling (3-second heartbeat) | — |
| **PostgreSQL 16** | Primary database | 5432 |
| **Redis 7** | Message broker + Channel layer + Rate limiter | 6379 |

---

## Monorepo Structure

```
metapilot/
├── services/api/              # Django REST API (the core backend)
│   ├── core/                  # Settings, URLs, Celery, ASGI config
│   ├── users/                 # Custom User model (4 roles)
│   ├── tenants/               # Agency, Tenant, Config, AuditLog, FeatureFlags
│   ├── api/                   # REST ViewSets and URL routing
│   ├── messaging/             # Contact, Conversation, Message, WhatsApp service
│   ├── campaigns/             # Campaign, ScheduledMessage, CampaignMessage
│   ├── scheduler/             # Distributed job scheduler engine
│   ├── templates/             # WhatsApp template management + Meta sync
│   ├── inbox/                 # Real-time chat inbox (WebSocket)
│   ├── webhooks/              # Meta webhook handlers + HMAC verification
│   ├── chatbot/               # Platform assistant (RAG-based)
│   ├── wa_chatbot/            # WhatsApp AI auto-reply bot
│   ├── analytics/             # Campaign stats, quotas, rate limiting
│   └── notifications/         # Role-based notification system
├── apps/                      # Frontend (Next.js dashboard)
├── infrastructure/            # Docker, Nginx, Prometheus, Grafana
├── database/                  # Schema docs, seeds, migration scripts
├── scripts/                   # Setup and deployment automation
├── docs/                      # Engineering documentation
└── Makefile                   # Monorepo task runner
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | Django 5 + DRF | Mature, batteries-included, excellent ORM |
| **Async** | Celery + Redis | Distributed task queue for message delivery |
| **WebSocket** | Django Channels + Daphne | Real-time inbox without separate service |
| **Database** | PostgreSQL 16 | JSON fields, robust indexing, row-level locking |
| **Auth** | SimpleJWT + Token Blacklisting | Stateless auth with secure rotation |
| **Encryption** | Fernet (AES-256) | Encrypt tenant API keys at rest |
| **AI** | OpenRouter (Step-3.5-Flash + GPT-4o) | Multi-model routing for text + vision |
| **API Docs** | drf-spectacular (Swagger + ReDoc) | Auto-generated OpenAPI 3.0 schema |
| **Infra** | Docker Compose + Prometheus + Grafana | Local dev + monitoring stack |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/omghante/metapilot.git
cd metapilot

# 2. Copy env and configure
cp .env.example .env
# Edit .env with your database, Redis, and Fernet key

# 3. Start all services with Docker
make dev

# 4. Or run locally
cd services/api
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# 5. Create super admin
curl -X POST http://localhost:8000/api/setup/create-superadmin/ \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin123"}'

# 6. Access API docs
open http://localhost:8000/api/docs/
```

---

## Documentation

> **📚 Each document below is written in simple language with detailed explanations of every component.**

| Document | What You'll Learn |
|---|---|
| [API Reference](./docs/API_REFERENCE.md) | Every endpoint, request/response format, authentication |
| [Database Schema](./docs/DATABASE_SCHEMA.md) | All 20+ models, relationships, indexes |
| [Scheduler Engine](./docs/SCHEDULER_ENGINE.md) | Distributed job processing, rate limiting, retry logic |
| [Multi-Tenancy](./docs/MULTI_TENANCY.md) | Agency → Client hierarchy, data isolation, middleware |
| [Webhook System](./docs/WEBHOOK_SYSTEM.md) | Meta webhook processing, HMAC verification, message flow |
| [Real-Time Inbox](./docs/REALTIME_INBOX.md) | WebSocket architecture, Django Channels, event system |
| [AI Chatbot](./docs/AI_CHATBOT.md) | RAG pipeline, OpenRouter integration, vision support |
| [Authentication & Security](./docs/AUTHENTICATION.md) | JWT flow, Fernet encryption, RBAC, GDPR |
| [Deployment Guide](./docs/DEPLOYMENT.md) | Docker, Daphne ASGI, Celery workers, production config |
| [Environment Variables](./docs/ENVIRONMENT_VARIABLES.md) | Every env var explained with defaults |

---

## Key Engineering Decisions

1. **Monorepo over Microservices** — Single codebase, shared types, atomic deploys. Complexity of microservices wasn't justified at this scale.

2. **Celery over raw asyncio** — Celery gives us persistent task queues, retry logic, and monitoring out of the box. Tasks survive server restarts.

3. **Django Channels over Socket.IO** — Native Django integration, same auth system, no separate server needed.

4. **Fernet Encryption** — API keys are encrypted at rest using AES-256. Never stored in plaintext. Decrypted only when making API calls.

5. **SELECT FOR UPDATE SKIP LOCKED** — PostgreSQL row-level locking for distributed job scheduling. Multiple workers can safely claim jobs without race conditions.

6. **Token Bucket Rate Limiter** — Redis-backed Lua script for atomic rate limiting. Respects Meta's 80 msg/sec limit with a safety margin of 50 tokens/sec.

---

## License

MIT License — © 2026 Om Ghante
