# Architecture Decision Records (ADRs)

This directory documents all significant architectural decisions made in MetaPilot.

## Format

Each ADR is a separate markdown file named `ADR-NNN-short-title.md`.

## Status Types

| Status | Meaning |
|---|---|
| `Accepted` | Decision is in effect |
| `Superseded` | Replaced by a newer ADR |
| `Deprecated` | No longer relevant |
| `Proposed` | Under discussion |

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](./ADR-001-modular-monolith.md) | Modular Monolith over Microservices | Accepted |
| [ADR-002](./ADR-002-daphne-asgi.md) | Daphne ASGI over Gunicorn WSGI | Accepted |
| [ADR-003](./ADR-003-fernet-encryption.md) | Fernet Encryption for API Secrets | Accepted |
| [ADR-004](./ADR-004-token-bucket-rate-limiter.md) | Token-Bucket Rate Limiter in Scheduler | Accepted |
| [ADR-005](./ADR-005-monorepo-structure.md) | Enterprise Monorepo Layout | Accepted |
