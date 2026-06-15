# ADR-005 — Enterprise Monorepo Layout

**Status**: Accepted  
**Date**: 2026-05  
**Deciders**: Om Ghante

---

## Context

The original repo structure was:
```
metapilot/
  backend/
  frontend/
```

This works for a small project but becomes problematic at scale:
- No clear separation between apps, shared packages, and infrastructure
- No place for system-wide tests, tooling, or observability configs
- Difficult to add new apps (admin panel, chatbot service, etc.)
- No standardized CI/CD or configuration management

## Decision

Adopt an **enterprise monorepo layout**:

```
metapilot/
  apps/          # User-facing deployable applications
  services/      # Domain service boundaries (future extraction targets)
  packages/      # Shared internal libraries
  infra/         # All infrastructure (Docker, K8s, Terraform)
  database/      # DB engineering (migrations, seeds, schemas)
  docs/          # All engineering documentation
  tests/         # System-wide tests (integration, load, e2e)
  observability/ # Monitoring stack configs
  security/      # Security policies and compliance
  configs/       # Shared linting/type configs
  scripts/       # Automation scripts
  tools/         # Internal tooling
```

## Rationale

- Follows patterns from Vercel, Stripe, and Shopify monorepos
- Clear home for every type of file
- Single `Makefile` entry point for all operations
- Scales to 10+ apps without becoming chaotic
- Makes the project look and feel like an enterprise platform (not a homework project)

## Consequences

- **Positive**: Professional repository structure visible to recruiters/contributors
- **Positive**: Clear home for infra, docs, tests — no more scattered files
- **Positive**: Easy to add new apps (`apps/admin-panel`, `apps/mobile-api`, etc.)
- **Negative**: Slightly more complex initial navigation (mitigated by clear READMEs)
- **Migration**: `backend/` → `apps/api/`, `frontend/` → `apps/` (backward-compatible)
