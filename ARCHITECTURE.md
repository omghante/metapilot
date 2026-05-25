# Architecture Overview

## System Design

MetaPilot is a **modular monolith** designed for horizontal scalability. All domain boundaries are clearly separated as Django apps today and can be extracted into independent microservices as load demands grow.

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        User Browser                          │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTPS / WSS
┌──────────────────────▼───────────────────────────────────────┐
│              Next.js Dashboard  (apps)         │
│         SSR + Client-side rendering · JWT auth               │
└──────────────────────┬───────────────────────────────────────┘
                       │ REST (HTTP) + WebSocket (WS)
┌──────────────────────▼───────────────────────────────────────┐
│     Nginx Reverse Proxy / Dokploy                            │
│     TLS termination · Rate limiting · Static files           │
└──────────┬───────────────────────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────────────────────────────────┐
│                   Django API  (apps/api)  — Daphne ASGI               │
│                                                                         │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  REST API   │  │ WebSocket  │  │ Django Admin │  │  API Docs    │ │
│  │  /api/*     │  │  /ws/*     │  │  /admin/     │  │  /api/docs/  │ │
│  └──────┬──────┘  └─────┬──────┘  └──────────────┘  └──────────────┘ │
│         │               │                                               │
│  ┌──────▼───────────────▼──────────────────────────────────────────┐  │
│  │               Domain Services (Django Apps)                      │  │
│  │  users · tenants · messaging · campaigns · templates            │  │
│  │  scheduler · analytics · billing · notifications                │  │
│  │  inbox · webhooks · chatbot · wa_chatbot                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
        ┌──────────────────┼───────────────────┐
        │                  │                   │
┌───────▼───────┐  ┌───────▼────────┐  ┌──────▼──────────┐
│  PostgreSQL   │  │  Redis         │  │  Meta Cloud API  │
│  Primary DB   │  │  Broker+Cache  │  │  graph.facebook  │
└───────────────┘  └───────┬────────┘  └─────────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
    ┌─────────▼──┐  ┌──────▼─────┐  ┌──▼──────────────┐
    │  Celery    │  │  Celery    │  │  Redis Channel  │
    │  Worker    │  │  Beat      │  │  Layer (WS)     │
    └────────────┘  └────────────┘  └─────────────────┘
```

---

## Multi-Tenant Role Hierarchy

```
SuperAdmin  (platform operator)
  └── Agency  (reseller / marketing agency)
        └── Tenant  (end client / business)
              ├── WhatsApp Business Account
              ├── Contacts
              ├── Campaigns
              ├── Templates
              ├── Inbox
              └── WA AI Chatbot
```

Each **Tenant** has one WhatsApp phone number. The `TenantMiddleware` resolves the active tenant from the JWT claim on every request, ensuring complete data isolation.

---

## Domain Service Boundaries

| Domain | Responsibility | Key Models |
|---|---|---|
| `users` | Authentication, roles | User |
| `tenants` | Multi-tenancy, WA config | Agency, Tenant, WhatsAppConfig |
| `messaging` | Contact management, send messages | Contact, Message, MessageLog |
| `campaigns` | Bulk campaign orchestration | Campaign, CampaignContact |
| `templates` | WA template lifecycle | Template |
| `scheduler` | Job scheduling, rate limiting | SchedulerJob, SchedulerLog |
| `analytics` | Delivery metrics | MessageAnalytics |
| `billing` | Subscription management | Plan, Subscription |
| `notifications` | In-app notifications | Notification |
| `inbox` | Real-time chat (WebSocket) | Conversation, InboxMessage |
| `webhooks` | Incoming Meta events | WebhookLog |
| `chatbot` | AI platform assistant | — (stateless) |
| `wa_chatbot` | WA customer AI bot | WAChatbotSession, KnowledgeDoc |

---

## Asynchronous Architecture

```
HTTP Request
    │
    ▼
Django View ──── enqueues ──── Celery Task ──── Redis Queue
                                    │
                                    ▼
                           WhatsApp API (Meta)
                                    │
                            Webhook response
                                    │
                                    ▼
                           /webhooks/ endpoint
                                    │
                             inbox / analytics
                             update consumer
```

### Celery Queues

| Queue | Tasks |
|---|---|
| `celery` | Default (messaging, templates, general) |
| `scheduler` | Heartbeat, stale job cleanup |
| `jobs` | Individual scheduled job execution |

---

## WebSocket Architecture (Real-time Inbox)

```
Agent Browser ──── WSS ──── Django Channels ──── Redis Pub/Sub
                                   │
                          InboxWebSocketConsumer
                                   │
                    (group: inbox_<tenant_id>)
                                   │
                    Meta Webhook ──► webhook_listener.py
                                   │
                            publishes message
                                   ▼
                         All connected agents
                           receive message
```

---

## Security Model

| Control | Implementation |
|---|---|
| Authentication | JWT Bearer tokens (60min access, 7d refresh) |
| Token blacklisting | SimpleJWT blacklist on logout/rotation |
| Tenant isolation | TenantMiddleware + per-view permission checks |
| API secret encryption | Fernet symmetric encryption at rest |
| Webhook integrity | HMAC-SHA256 signature verification |
| HTTPS enforcement | HSTS + SECURE_PROXY_SSL_HEADER |
| Rate limiting | Token-bucket rate limiter in scheduler |
| RBAC | IsSuperAdmin / IsAgencyOwner / IsTenantUser permission classes |

---

## Scaling Path

### Current (Modular Monolith)
- Single Django process (Daphne)
- Single Celery worker
- SQLite → PostgreSQL
- Redis for queue + channel layer

### Phase 2 — Horizontal Scaling
- Multiple Daphne instances behind load balancer
- Multiple Celery workers (separate scheduler/jobs/default queues)
- PostgreSQL read replicas
- Redis Cluster

### Phase 3 — Service Extraction
- Extract `scheduler` → independent Python service
- Extract `wa_chatbot` → independent AI service
- Extract `inbox` → dedicated WebSocket gateway
- Event-driven communication via Kafka/RabbitMQ
- Kubernetes autoscaling

---

## Key Technical Decisions

### ADR-001: Modular Monolith over Microservices
**Decision**: Keep all domains in one Django process.  
**Rationale**: Shared auth models, simpler debugging, lower infra cost, faster iteration. Domain boundaries exist for future extraction.

### ADR-002: Daphne ASGI over Gunicorn WSGI
**Decision**: Use Daphne as the production server.  
**Rationale**: Required for Django Channels WebSocket support. Handles both HTTP and WebSocket protocols.

### ADR-003: Fernet Encryption for API Secrets
**Decision**: Encrypt WhatsApp API tokens with Fernet before storing.  
**Rationale**: Prevents credential exposure from DB dumps. Keys managed via environment variables.

### ADR-004: Token-Bucket Rate Limiter in Scheduler
**Decision**: Custom token-bucket implementation in `scheduler/services/rate_limiter.py`.  
**Rationale**: Meta Cloud API enforces per-number rate limits. Prevents API bans.
