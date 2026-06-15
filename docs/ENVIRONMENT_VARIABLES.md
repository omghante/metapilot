# Environment Variables

> Every environment variable explained with defaults and examples.

---

## Quick Reference

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SECRET_KEY` | ✅ | — | Django secret key for token signing |
| `DEBUG` | ❌ | `True` | Enable debug mode |
| `ALLOWED_HOSTS` | ✅ (prod) | `*` | Comma-separated allowed hostnames |
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `CELERY_BROKER_URL` | ✅ | — | Redis URL for Celery task queue |
| `CHANNEL_REDIS_URL` | ✅ | — | Redis URL for WebSocket channel layer |
| `FERNET_KEY` | ✅ | — | AES-256 encryption key for API credentials |
| `OPENROUTER_API_KEY` | ❌ | — | AI chatbot API key |
| `META_APP_ID` | ❌ | — | Meta (Facebook) App ID |
| `META_APP_SECRET` | ❌ | — | Meta App Secret |
| `WEBHOOK_BASE_URL` | ❌ | — | Public URL for webhook callbacks |
| `WA_CHATBOT_ENABLED` | ❌ | `False` | Enable WhatsApp auto-reply chatbot |
| `CORS_ALLOWED_ORIGINS` | ❌ | `http://localhost:3000` | Allowed frontend origins |

---

## Detailed Explanations

### Core Django

#### `SECRET_KEY`
```env
SECRET_KEY=django-insecure-change-me-in-production-to-64-random-chars
```
**What it does:** Used to sign JWT tokens, CSRF tokens, and session cookies. If this changes, all existing tokens become invalid (users get logged out).

**How to generate:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**Security:** In production, use a 64+ character random string. Never commit to git.

---

#### `DEBUG`
```env
DEBUG=True    # Development
DEBUG=False   # Production
```
**What it does:**
- `True` → Detailed error pages, SQL query logging, no HTTPS requirement
- `False` → Generic error pages, HTTPS enforced, static files must be pre-collected

**Warning:** Never run `DEBUG=True` in production. It exposes stack traces, database queries, and environment variables in error pages.

---

#### `ALLOWED_HOSTS`
```env
ALLOWED_HOSTS=localhost,127.0.0.1,api.metapilot.io
```
**What it does:** Django rejects requests with `Host` headers not in this list. Prevents HTTP Host header attacks.

**Development:** Leave as `*` (accept all) or `localhost`.
**Production:** Set to your exact domain(s).

---

### Database

#### `DATABASE_URL`
```env
# Local development
DATABASE_URL=postgresql://metapilot:metapilot@localhost:5432/metapilot

# Docker
DATABASE_URL=postgresql://metapilot:metapilot@db:5432/metapilot

# Production (managed PostgreSQL)
DATABASE_URL=postgresql://user:password@db-host.aws.com:5432/metapilot?sslmode=require
```
**Format:** `postgresql://USER:PASSWORD@HOST:PORT/DATABASE_NAME`

**What it does:** Connection string for PostgreSQL. Parsed by `dj-database-url` in settings.

**Why PostgreSQL?** JSONB columns for flexible data (tags, metadata, template params), `SELECT FOR UPDATE SKIP LOCKED` for distributed job scheduling, excellent indexing.

---

### Redis

#### `CELERY_BROKER_URL`
```env
# Local
CELERY_BROKER_URL=redis://localhost:6379/0

# Docker
CELERY_BROKER_URL=redis://redis:6379/0

# Production (managed Redis)
CELERY_BROKER_URL=rediss://default:password@redis-host:6380/0
```
**What it does:** Redis database 0 is used as the Celery message broker. Task payloads (e.g., "send these 1000 messages") are queued here.

**Database number `0`:** Redis supports 16 databases (0-15). We use 0 for Celery, 1 for Channels.

---

#### `CHANNEL_REDIS_URL`
```env
CHANNEL_REDIS_URL=redis://localhost:6379/1
```
**What it does:** Redis database 1 is used for Django Channels (WebSocket pub/sub). Inbox real-time events are broadcast through this.

**Why a separate database?** Isolation. Celery's high-throughput task queue doesn't interfere with WebSocket message delivery.

---

### Encryption

#### `FERNET_KEY`
```env
FERNET_KEY=your-44-character-base64-encoded-key-here=
```
**What it does:** Symmetric encryption key for encrypting tenant API credentials (Meta access tokens, phone number IDs, app secrets) stored in the `tenant_configs` table.

**How to generate:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Output: something like: s2a3d4f5g6h7j8k9l0a1s2d3f4g5h6j7k8l9a0s1d2f3g4h5=
```

**Security rules:**
- Generate once, never change (or all encrypted data becomes unreadable)
- Store only in environment variables, never in code
- Back up securely (if lost, all encrypted credentials are permanently lost)
- 44 characters, base64-encoded, ending with `=`

**What happens if you lose it:** All tenant API credentials become undecryptable. You'd need to re-enter every tenant's Meta access token, phone number ID, etc.

---

### AI / Chatbot

#### `OPENROUTER_API_KEY`
```env
OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890
```
**What it does:** API key for [OpenRouter](https://openrouter.ai/) — a unified gateway to multiple AI models (GPT-4o, Llama 4, Gemini).

**Used by:**
- Platform chatbot (help assistant)
- WhatsApp auto-reply chatbot (customer-facing)
- Image analysis (vision AI)

**Not required if:** You disable AI features (`WA_CHATBOT_ENABLED=False` and don't use the platform chatbot).

**How to get one:** Sign up at https://openrouter.ai/ → API Keys → Create Key

---

#### `WA_CHATBOT_ENABLED`
```env
WA_CHATBOT_ENABLED=True   # Auto-reply to customer messages
WA_CHATBOT_ENABLED=False  # Just receive and store messages
```
**What it does:** When enabled, incoming WhatsApp messages trigger an AI-generated auto-reply. When disabled, messages are stored and shown in the inbox, but no automatic response is sent.

---

### Meta (WhatsApp) Integration

#### `META_APP_ID`
```env
META_APP_ID=123456789012345
```
**What it does:** Your Meta (Facebook) App ID from the [Meta Developer Console](https://developers.facebook.com/). Used for API authentication and webhook configuration.

---

#### `META_APP_SECRET`
```env
META_APP_SECRET=abc123def456ghi789
```
**What it does:** Used to verify webhook signatures (HMAC-SHA256). Meta signs every webhook payload with this secret, and we verify the signature to prevent fake webhooks.

**Note:** Per-tenant app secrets are stored encrypted in `TenantConfig`. This global setting is a fallback.

---

#### `WEBHOOK_BASE_URL`
```env
WEBHOOK_BASE_URL=https://api.metapilot.io
```
**What it does:** The public URL where Meta sends webhook callbacks. Used to generate per-tenant webhook URLs:
```
{WEBHOOK_BASE_URL}/api/wa-chatbot/webhook/{tenant_id}/
```

**Development:** Use ngrok or similar to expose localhost:
```bash
ngrok http 8000
# Then set: WEBHOOK_BASE_URL=https://abc123.ngrok.io
```

---

### CORS

#### `CORS_ALLOWED_ORIGINS`
```env
# Development
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Production
CORS_ALLOWED_ORIGINS=https://app.metapilot.io,https://admin.metapilot.io
```
**What it does:** Browsers block cross-origin requests by default. This tells the API which frontend origins are allowed to make requests.

**Common mistake:** Forgetting to add your frontend URL here → browser console shows `CORS policy` errors.

---

### Feature Flags

#### `TEMPLATE_AUTO_SYNC`
```env
TEMPLATE_AUTO_SYNC=True
```
**What it does:** When enabled, Celery Beat automatically syncs WhatsApp templates from Meta's API every 5 minutes. Disable to reduce API calls during development.

---

#### `AUDIT_LOG_ENABLED`
```env
AUDIT_LOG_ENABLED=True
```
**What it does:** When enabled, security-relevant actions (login, logout, create, delete) are logged to the `audit_logs` table.

---

## Full `.env.example`

```env
# ═══════════════════════════════════════════════════
# METAPILOT — Environment Configuration
# ═══════════════════════════════════════════════════

# ── Core Django ────────────────────────────────────
SECRET_KEY=django-insecure-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# ── Database ───────────────────────────────────────
DATABASE_URL=postgresql://metapilot:metapilot@localhost:5432/metapilot

# ── Redis ──────────────────────────────────────────
CELERY_BROKER_URL=redis://localhost:6379/0
CHANNEL_REDIS_URL=redis://localhost:6379/1

# ── Encryption ─────────────────────────────────────
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=

# ── AI / Chatbot ───────────────────────────────────
OPENROUTER_API_KEY=
WA_CHATBOT_ENABLED=False

# ── Meta (WhatsApp) ───────────────────────────────
META_APP_ID=
META_APP_SECRET=
WEBHOOK_BASE_URL=http://localhost:8000

# ── CORS ───────────────────────────────────────────
CORS_ALLOWED_ORIGINS=http://localhost:3000

# ── Feature Flags ──────────────────────────────────
TEMPLATE_AUTO_SYNC=True
AUDIT_LOG_ENABLED=True

# ── Email (Optional) ──────────────────────────────
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
```

---

## Environment-Specific Configurations

| Setting | Development | Production |
|---------|-------------|------------|
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | Any string | 64+ random chars |
| `ALLOWED_HOSTS` | `*` | Exact domains |
| `DATABASE_URL` | Local PostgreSQL | Managed PostgreSQL (SSL) |
| `CELERY_BROKER_URL` | Local Redis | Managed Redis (TLS) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | `https://app.metapilot.io` |
| `WA_CHATBOT_ENABLED` | `False` | `True` |
| `WEBHOOK_BASE_URL` | ngrok URL | Production domain |
