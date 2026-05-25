# Contributing to MetaPilot

Thank you for contributing to MetaPilot! This document covers everything you need to get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Branch Naming](#branch-naming)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Code Standards](#code-standards)
- [Testing Requirements](#testing-requirements)

---

## Code of Conduct

All contributors must follow our [Code of Conduct](./CODE_OF_CONDUCT.md). Be respectful and constructive.

---

## Getting Started

### Prerequisites

| Tool | Minimum Version |
|---|---|
| Python | 3.12+ |
| Node.js | 20+ |
| Docker | 24+ |
| Redis | 7+ |
| PostgreSQL | 16+ |

### Setup

```bash
git clone https://github.com/omghante/metapilot.git
cd metapilot
make setup
make dev
```

See [docs/onboarding/](./docs/onboarding/) for detailed environment setup.

---

## Development Workflow

1. Fork the repository
2. Create a feature branch from `develop`
3. Make your changes with tests
4. Run `make lint` and `make test`
5. Submit a Pull Request targeting `develop`

> **Note:** Never PR directly to `main`. All changes go through `develop` first.

---

## Branch Naming

```
feature/<short-description>      # New feature
fix/<issue-number>-<description> # Bug fix
chore/<description>              # Tooling, CI, docs
refactor/<module>-<description>  # Code refactoring
hotfix/<description>             # Production hotfix
```

**Examples:**
```
feature/inbox-file-attachments
fix/42-campaign-contact-dedup
chore/update-celery-to-5.4
refactor/messaging-views-split
```

---

## Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no logic change |
| `refactor` | Code restructure, no feature/fix |
| `test` | Adding or updating tests |
| `chore` | Build, CI, tooling changes |
| `perf` | Performance improvement |

**Examples:**
```
feat(scheduler): add token-bucket rate limiter per phone number
fix(inbox): websocket disconnect not closing consumer properly
docs(api): add OpenAPI examples for campaign endpoints
refactor(campaigns): split views.py into domain sub-modules
```

---

## Pull Request Process

1. Fill in the PR template completely
2. Ensure CI passes (lint, tests, build)
3. Add/update tests for all changed code
4. Request review from at least one maintainer
5. Squash and merge after approval

### PR Checklist

- [ ] Tests added or updated
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] Documentation updated (if applicable)
- [ ] Migration files included (if model changes)
- [ ] `.env.example` updated (if new env vars)

---

## Code Standards

### Python (Backend — `apps/api/`)

- **Formatter**: `ruff format`
- **Linter**: `ruff check`
- **Type checker**: `mypy`
- **Max line length**: 100
- **Max file length**: 500 lines (split larger files)
- **No bare `except:`** — always catch specific exceptions
- **No `print()`** in production code — use `logging`

```bash
# Run from apps/api/
ruff check .
ruff format .
mypy .
```

### TypeScript (Frontend — `apps/`)

- **Formatter**: Prettier
- **Linter**: ESLint (Next.js config)
- **Max line length**: 100
- **Max file length**: 400 lines
- **No `any` types** unless absolutely unavoidable
- **Prefer named exports** over default exports for components

```bash
# Run from apps/
yarn lint
yarn tsc --noEmit
```

### File Size Guidelines

| Type | Max Lines |
|---|---|
| Django views | 200 per file (split into sub-modules) |
| React components | 300 per file |
| Service classes | 300 per file |
| Utility functions | 100 per file |

---

## Testing Requirements

| Layer | Minimum Coverage |
|---|---|
| Django views | 80% |
| Service classes | 90% |
| Utility functions | 95% |
| React components | Key interactions |

### Backend Tests

```bash
cd apps/api
pytest --cov=. -v
```

### Frontend Tests

```bash
cd apps
yarn test
```

---

## Questions?

Open a [GitHub Discussion](https://github.com/omghante/metapilot/discussions) for questions, or an [Issue](https://github.com/omghante/metapilot/issues) for bugs.
