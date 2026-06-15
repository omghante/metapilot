# ADR-001 — Modular Monolith over Microservices

**Status**: Accepted  
**Date**: 2026-05  
**Deciders**: Om Ghante

---

## Context

MetaPilot needed a scalable architecture from day one. The two primary options were:
1. Microservices — each domain (messaging, campaigns, scheduler, etc.) as a separate deployable service
2. Modular Monolith — all domains in one codebase/process but with clear boundaries

## Decision

**Modular Monolith** with domain-separated Django apps and a clear service boundary contract.

## Rationale

| Factor | Microservices | Modular Monolith |
|---|---|---|
| Development speed | Slow (distributed calls, contracts) | Fast (direct imports) |
| Debugging | Hard (distributed tracing needed) | Easy (single process) |
| Infra cost | High (N services, N databases) | Low (1 process) |
| Auth sharing | Complex (inter-service tokens) | Simple (shared models) |
| Team size fit | 10+ engineers | 1–5 engineers |
| Scalability | Excellent | Good (workers scale independently) |

The key insight: **our domain boundaries are already clean**. Each Django app (`messaging`, `campaigns`, `scheduler`, etc.) is a self-contained module. When load demands extraction, each app can become a microservice with minimal refactoring.

## Consequences

- **Positive**: Fast iteration, simple debugging, shared auth/models, lower infra cost
- **Positive**: Celery workers already scale independently (separate queues)
- **Negative**: Single point of failure (mitigated by Daphne + worker process separation)
- **Future**: Apps can be extracted to independent services in Phase 3 (see ROADMAP.md)
