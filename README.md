# MetaPilot

> **Multi-tenant WhatsApp engagement and automation platform built for high-scale asynchronous communication infrastructure.**

MetaPilot is a production-grade, multi-tenant SaaS platform that enables agencies and businesses to manage WhatsApp marketing campaigns, real-time customer conversations, AI-powered chatbots, and message scheduling — all through a single unified platform.

---

## Platform Capabilities

| Domain | Capability |
|---|---|
| **Messaging** | Bulk campaigns, scheduled delivery, template messages |
| **Inbox** | Real-time two-way WhatsApp conversations via WebSocket |
| **AI Chatbot** | Customer-facing WhatsApp AI bot with knowledge base (OpenRouter + GPT-4o) |
| **Multi-tenancy** | Agency → Client hierarchy with isolated WhatsApp accounts |
| **Scheduler** | High-performance async job scheduler with token-bucket rate limiting |
| **Analytics** | Message delivery, read rates, campaign performance |
| **Webhooks** | HMAC-verified incoming webhook processing from Meta |
| **Templates** | WhatsApp message template builder with Meta API sync |

---

## Monorepo Structure

```
metapilot/
├── apps/                    # User-facing applications
│   ├── api/                 # Django REST API + Celery + Channels
│   └── dashboard-web/       # Next.js SaaS dashboard
├── services/                # Domain service boundaries
├── packages/                # Shared internal libraries
├── infra/                   # Infrastructure (Docker, K8s, Terraform)
├── database/                # Migrations, seeds, schemas
├── docs/                    # All engineering documentation
├── tests/                   # System-wide integration, load, e2e tests
├── observability/           # Monitoring, tracing, alerting
├── security/                # Policies, compliance, threat models
├── configs/                 # Shared linting/type configs
├── scripts/                 # Automation scripts
└── tools/                   # Internal engineering tooling
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/omghante/metapilot.git
cd metapilot

# Bootstrap everything
make setup

# Start all services (dev)
make dev

# Run tests
make test
```

---

## Tech Stack

**Backend** — Django 5 · DRF · Celery · Redis · Django Channels · Daphne (ASGI)  
**Frontend** — Next.js 16 · React 19 · TypeScript · TailwindCSS v4 · Recharts  
**AI** — OpenRouter (stepfun-3.5-flash text · GPT-4o vision)  
**Infra** — Docker · PostgreSQL · Redis · Prometheus · Grafana  
**Auth** — JWT (SimpleJWT) with token blacklisting · Fernet encryption

---

## Documentation

| Doc | Link |
|---|---|
| Architecture Overview | [docs/architecture/](./docs/architecture/) |
| API Reference | [docs/api/](./docs/api/) |
| Deployment Guide | [docs/deployment/](./docs/deployment/) |
| Scaling Strategy | [docs/scaling/](./docs/scaling/) |
| Security Model | [docs/security/](./docs/security/) |
| Developer Onboarding | [docs/onboarding/](./docs/onboarding/) |
| Architecture Decision Records | [docs/decisions/](./docs/decisions/) |

---

## License

MIT License — © 2026 Om Ghante
