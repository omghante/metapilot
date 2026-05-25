# MetaPilot — Roadmap

> This roadmap describes the evolution from current modular monolith to a full enterprise-grade communication platform.

---

## Phase 1 — Foundation (Current)

> **Goal**: Enterprise-grade monorepo with proper engineering standards.

### Completed ✅
- [x] Multi-tenant SaaS architecture (Agency → Client hierarchy)
- [x] JWT authentication with token blacklisting + Fernet encryption
- [x] Bulk WhatsApp campaign management
- [x] Template builder with Meta API sync + auto-classifier
- [x] High-performance async message scheduler with token-bucket rate limiting
- [x] Real-time inbox via Django Channels WebSocket
- [x] AI chatbot (platform assistant + customer-facing WA bot)
- [x] HMAC-verified Meta webhook processing
- [x] Monorepo restructure (`apps/`, `services/`, `packages/`, `infra/`)
- [x] CI/CD pipelines (GitHub Actions)
- [x] Docker development & production compose stacks
- [x] Comprehensive architecture documentation

### In Progress 🔄
- [ ] Split oversized view files into domain sub-modules
- [ ] `ruff` + `mypy` enforcement across entire API codebase
- [ ] Prometheus metrics endpoint integration
- [ ] Sentry error tracking integration
- [ ] Structured JSON logging with correlation IDs
- [ ] API versioning (`/api/v1/`, `/api/v2/`)
- [ ] Grafana dashboard templates

---

## Phase 2 — Observability & Performance

> **Goal**: Production-hardened platform with full visibility and horizontal scalability.

### Planned 📋
- [ ] Distributed tracing (OpenTelemetry → Jaeger)
- [ ] Grafana dashboards for message throughput, queue depth, error rates
- [ ] Prometheus alerting rules (worker backlog, failed jobs, API latency)
- [ ] PostgreSQL connection pooling (PgBouncer)
- [ ] Redis Cluster configuration
- [ ] Per-tenant API rate limiting middleware
- [ ] Feature flags system (per-tenant rollout control)
- [ ] Audit log trail (who changed what and when)
- [ ] Media storage migration to S3/Cloudflare R2 + CDN
- [ ] Celery worker autoscaling based on queue depth
- [ ] Load testing suite (Locust)
- [ ] Integration test suite for all critical paths
- [ ] E2E test suite (Playwright)

---

## Phase 3 — Scale & Service Extraction

> **Goal**: Support 1M+ active users with independent deployable services.

### Planned 📋
- [ ] Extract `scheduler` → standalone Python microservice
- [ ] Extract `wa_chatbot` → independent AI inference service
- [ ] Extract `inbox` → dedicated WebSocket gateway (Go or Node.js)
- [ ] Event-driven architecture (Kafka or RabbitMQ) for service communication
- [ ] PostgreSQL primary-replica setup with read routing
- [ ] Kubernetes manifests for all services
- [ ] Helm charts for deployment
- [ ] Horizontal Pod Autoscaler (HPA) configs
- [ ] Multi-region deployment support
- [ ] GDPR compliance tooling (data export, right to erasure)

---

## Phase 4 — Platform Extensions

> **Goal**: Full omnichannel engagement platform.

### Future 🔭
- [ ] Instagram DM integration (Meta Graph API)
- [ ] Facebook Messenger integration
- [ ] SMS channel (Twilio)
- [ ] Email channel (SendGrid)
- [ ] Unified analytics dashboard across all channels
- [ ] Advanced AI flows (multi-turn conversation builders)
- [ ] No-code campaign builder (drag-and-drop)
- [ ] Webhook marketplace (Zapier / Make integration)
- [ ] Public REST API + SDK for third-party developers
- [ ] White-label frontend theming per agency

---

## Version History

| Version | Date | Highlights |
|---|---|---|
| v0.1.0 | 2026-01 | Initial private build |
| v0.2.0 | 2026-03 | Scheduler + Rate limiter |
| v0.3.0 | 2026-04 | Real-time inbox (WebSocket) |
| v0.4.0 | 2026-05 | WA AI Chatbot + knowledge docs |
| v0.5.0 | 2026-05 | Enterprise monorepo restructure |
