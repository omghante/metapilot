# Database Schema

> Complete documentation of all database models, relationships, and design decisions.

---

## Overview

MetaPilot uses **20+ database tables** across 10 Django apps. All primary keys are **UUIDs** (not auto-incrementing integers) for security and distributed system compatibility.

```
┌─────────────────────────────────────────────────────────────┐
│                    MULTI-TENANCY LAYER                       │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────────┐   │
│  │ agencies │───▶│ tenants  │◀───│ users                │   │
│  └──────────┘    └────┬─────┘    └──────────────────────┘   │
│                       │                                      │
│  ┌────────────────────┼────────────────────────────────┐    │
│  │              TENANT-SCOPED DATA                      │    │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │    │
│  │  │ contacts │  │campaigns │  │ scheduler_jobs     │ │    │
│  │  └────┬─────┘  └────┬─────┘  └────────┬───────────┘ │    │
│  │       │              │                  │             │    │
│  │  ┌────▼─────────┐   │          ┌───────▼──────────┐  │    │
│  │  │conversations │   │          │job_recipients    │  │    │
│  │  └────┬─────────┘   │          └──────────────────┘  │    │
│  │       │              │                                │    │
│  │  ┌────▼─────┐  ┌────▼──────────────┐                 │    │
│  │  │ messages │  │scheduled_messages │                 │    │
│  │  └──────────┘  └───────────────────┘                 │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Users App

### `users` Table

The custom User model replaces Django's default. Uses **email** as the login identifier (not username).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `email` | VARCHAR(254) | Unique, indexed. Login identifier |
| `password` | VARCHAR(128) | PBKDF2 hashed password |
| `first_name` | VARCHAR(150) | Optional |
| `last_name` | VARCHAR(150) | Optional |
| `phone` | VARCHAR(20) | Optional phone number |
| `role` | VARCHAR(20) | `SUPER_ADMIN`, `AGENCY_ADMIN`, `TENANT_ADMIN`, `TENANT_USER` |
| `agency_id` | UUID FK → agencies | Only for AGENCY_ADMIN users |
| `tenant_id` | UUID FK → tenants | NULL for SUPER_ADMIN and AGENCY_ADMIN |
| `is_active` | BOOLEAN | Soft delete / account disable |
| `is_staff` | BOOLEAN | Django admin access |
| `created_at` | TIMESTAMP | Auto-set on creation |
| `updated_at` | TIMESTAMP | Auto-set on update |

**Role Hierarchy:**
```
SUPER_ADMIN        →  Full platform access. No tenant restriction.
  └── AGENCY_ADMIN →  Manages clients under their agency.
        └── TENANT_ADMIN  →  Manages own tenant (contacts, campaigns, etc.)
              └── TENANT_USER   →  Limited access within tenant.
```

---

## 2. Tenants App

### `agencies` Table

Optional reseller layer. An agency manages multiple clients.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `name` | VARCHAR(255) | Agency business name |
| `slug` | VARCHAR(50) | URL-safe identifier, unique |
| `contact_email` | VARCHAR(254) | Primary contact email |
| `phone` | VARCHAR(20) | Phone number |
| `status` | VARCHAR(20) | `ACTIVE` or `SUSPENDED` |
| `commission_percent` | DECIMAL(5,2) | Commission rate for billing |

---

### `tenants` Table

The core multi-tenancy entity. Each tenant = one business = one WhatsApp number.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `name` | VARCHAR(255) | Business name |
| `slug` | VARCHAR(50) | Unique URL identifier |
| `business_type` | VARCHAR(20) | ECOMMERCE, SERVICE, SAAS, etc. |
| `agency_id` | UUID FK → agencies | Parent agency (optional) |
| `status` | VARCHAR(20) | ACTIVE, SUSPENDED, PENDING |
| `plan_type` | VARCHAR(20) | FREE, STARTER, PRO, ENTERPRISE |
| `monthly_message_limit` | INTEGER | Default: 1000 |
| `active_users_limit` | INTEGER | Default: 5 |
| `api_rate_limit` | INTEGER | API calls per minute. Default: 60 |
| `webhook_token` | VARCHAR(64) | Auto-generated 32-byte token |
| `whatsapp_enabled` | BOOLEAN | Feature toggle |
| `campaigns_enabled` | BOOLEAN | Feature toggle |
| `ai_features_enabled` | BOOLEAN | Feature toggle |

**Indexes:**
- `tenants_status` — Fast filtering by status
- `tenants_agency` — Fast lookup of agency's clients
- `tenants_agency_status` — Combined filter for agency dashboard

**Auto-generated webhook URL:**
```
{WEBHOOK_BASE_URL}/api/wa-chatbot/webhook/{tenant_id}/
```

---

### `tenant_configs` Table

Encrypted storage for API credentials. This is how each tenant's WhatsApp keys are stored securely.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `tenant_id` | UUID FK → tenants | Which tenant owns this config |
| `provider` | VARCHAR(50) | META_WHATSAPP, TWILIO, SENDGRID, CUSTOM |
| `key_name` | VARCHAR(100) | e.g., `access_token`, `phone_number_id` |
| `encrypted_value` | TEXT | Fernet-encrypted (AES-256-CBC) value |
| `is_active` | BOOLEAN | Can be deactivated without deleting |

**Unique constraint:** `(tenant, provider, key_name)` — one config per key per provider per tenant.

**Encryption flow:**
```python
# Storing a value
config.set_value("EAAGm0PX4...")  
# Internally: Fernet(FERNET_KEY).encrypt(b"EAAGm0PX4...").decode()

# Retrieving a value  
token = config.get_value()
# Internally: Fernet(FERNET_KEY).decrypt(encrypted_bytes).decode()
```

---

### `audit_logs` Table

Tracks all important user actions for security and compliance.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `action` | VARCHAR(100) | e.g., `auth.login_success`, `campaign.created` |
| `performed_by_id` | UUID FK → users | Who did it |
| `tenant_id` | UUID FK → tenants | Which tenant context |
| `agency_id` | UUID FK → agencies | Which agency context |
| `metadata` | JSONB | Additional context (any key-value data) |
| `ip_address` | INET | Client IP address |
| `user_agent` | TEXT | Browser/client identifier |
| `timestamp` | TIMESTAMP | When it happened |

---

### `feature_flags` Table

Per-tenant feature toggles for progressive rollouts.

| Column | Type | Description |
|--------|------|-------------|
| `tenant_id` | UUID FK → tenants | Which tenant |
| `feature_name` | VARCHAR(100) | e.g., `carousel_templates`, `ai_chatbot_v2` |
| `enabled` | BOOLEAN | ON/OFF |

**Unique:** `(tenant, feature_name)`

---

### `data_deletion_requests` Table

GDPR compliance. Tracks data deletion requests with status.

| Statuses | Description |
|----------|-------------|
| PENDING | Request received, not started |
| PROCESSING | Deletion in progress |
| COMPLETED | Data successfully deleted |
| FAILED | Deletion failed (will retry) |

---

## 3. Messaging App

### `contacts` Table

WhatsApp contacts for each tenant.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `tenant_id` | UUID FK → tenants | Owner tenant |
| `phone` | VARCHAR(20) | WhatsApp number (E.164 format) |
| `name` | VARCHAR(255) | Display name |
| `email` | VARCHAR(254) | Optional email |
| `tags` | JSONB | Array of strings for segmentation: `["VIP", "newsletter"]` |
| `metadata` | JSONB | Arbitrary key-value data |
| `is_subscribed` | BOOLEAN | Opt-in status |
| `is_blocked` | BOOLEAN | Blocked by the business |
| `import_source_id` | UUID FK → contact_imports | Which import batch |

**Unique:** `(tenant, phone)` — same phone can exist in different tenants.

---

### `conversations` Table

Represents a WhatsApp conversation thread with one contact.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `contact_id` | UUID FK → contacts | Who is this conversation with |
| `wa_conversation_id` | VARCHAR(100) | Meta's conversation ID |
| `status` | VARCHAR(20) | ACTIVE, ARCHIVED, BLOCKED |
| `assigned_to_id` | UUID FK → users | Agent assignment |
| `last_message_at` | TIMESTAMP | For sorting |

---

### `messages` Table

Individual WhatsApp messages (both inbound and outbound).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `conversation_id` | UUID FK → conversations | Parent thread |
| `wa_message_id` | VARCHAR(100) | Meta's message ID (for status tracking) |
| `direction` | VARCHAR(10) | INBOUND or OUTBOUND |
| `message_type` | VARCHAR(20) | TEXT, IMAGE, TEMPLATE, etc. |
| `status` | VARCHAR(20) | PENDING → SENT → DELIVERED → READ / FAILED |
| `content` | TEXT | Message text body |
| `payload` | JSONB | Full message payload (template params, media, etc.) |
| `media_url` | URL | Media attachment URL |
| `error_code` | VARCHAR(50) | Meta error code if failed |
| `error_message` | TEXT | Error description |
| `sent_at` | TIMESTAMP | When sent |
| `delivered_at` | TIMESTAMP | When delivered |
| `read_at` | TIMESTAMP | When read |

---

### `media_assets` Table

Uploaded files for campaigns (images, videos, documents).

| Column | Type | Description |
|--------|------|-------------|
| `file_data` | BYTEA | Binary file content stored in PostgreSQL |
| `content_type` | VARCHAR(100) | MIME type for HTTP serving |
| `public_token` | VARCHAR(64) | Random token for unauthenticated access |

**Why store files in PostgreSQL?** Simplicity. No S3 setup needed. Files ≤5MB are stored as binary. The `public_token` lets Meta's servers fetch header images without auth.

---

### `contact_imports` Table

Tracks CSV/XLSX import jobs with result counts.

| Column | Type | Description |
|--------|------|-------------|
| `total_rows` | INTEGER | Rows in uploaded file |
| `imported_count` | INTEGER | Successfully imported |
| `duplicate_count` | INTEGER | Skipped (already existed) |
| `error_count` | INTEGER | Failed rows |
| `errors` | JSONB | Array of error details |
| `apply_tags` | JSONB | Tags auto-applied to imported contacts |

---

## 4. Campaigns App

### `campaigns` Table

Marketing campaigns that target contacts by tags.

Key fields: `template_name`, `template_type` (standard/carousel), `target_tags`, `target_all`, `header_data` (JSON), `cards_json` (JSON for carousel cards).

### `campaign_messages` Table

Individual messages within a campaign, each with independent scheduling. Links to `scheduler_jobs` for execution tracking.

### `scheduled_messages` Table

Legacy per-recipient tracking. Links campaign → contact with status.

### `message_results` Table

Detailed result log for each send attempt.

---

## 5. Scheduler App

### `scheduler_jobs` Table

Central scheduling entity. See [Scheduler Engine](./SCHEDULER_ENGINE.md) for detailed explanation.

Key fields:
- `job_hash` — MD5 deduplication hash (unique)
- `claimed_by` — Server ID for distributed locking
- `priority` — 1 (highest) to 10 (lowest)
- Template data: `template_type`, `header_data`, `cards_json`
- Stats: `total_recipients`, `sent_count`, `failed_count`

**Indexes (4 composite):**
- `(status, scheduled_time)` — Finding due jobs
- `(tenant, scheduled_time)` — Tenant-scoped queries
- `(status, next_retry_at)` — Retry scheduling
- `(status, claimed_by)` — Distributed lock tracking

### `scheduler_job_recipients` Table

Per-recipient tracking with error isolation. Each recipient has independent status.

**Unique:** `(job, phone_number)` — prevents duplicate sends.

---

## 6. Templates App

### `whatsapp_templates` Table

Templates created by Super Admin and assigned to clients (M2M relationship).

### `cached_meta_templates` Table

Templates fetched from Meta's Graph API and cached locally. Includes internal classification fields not provided by Meta: `industry`, `feature_group`, `use_case`.

**Unique:** `(tenant, meta_template_id, language)`

---

## 7. Inbox App

### `inbox_conversations` Table

Denormalized for fast inbox list rendering. Stores `last_message`, `last_message_time`, `unread_count` to avoid expensive JOINs.

**Unique:** `(tenant, customer_phone)`

### `inbox_messages` Table

Full message content stored as `content_json` (JSONB). Deduplication via `meta_message_id`.

---

## 8. Analytics App

### `campaign_stats` — 1:1 with campaigns. Aggregated delivery/read rates.
### `message_analytics` — 1:1 with messages. Latency tracking.
### `client_quotas` — 1:1 with tenants. Daily/monthly message limits.
### `rate_limit_logs` — API rate limit tracking per endpoint.

---

## 9. Notifications App

### `notifications` Table

Role-based notifications with priority levels (LOW, MEDIUM, HIGH, URGENT).

**5 indexes** for fast queries on different access patterns.

---

## Key Design Decisions

1. **UUIDs everywhere** — Prevents ID guessing attacks. Safe for distributed systems.

2. **JSONB for flexible data** — Tags, metadata, template params, carousel cards — all stored as JSONB. PostgreSQL indexes JSONB efficiently.

3. **Soft deletes** — `is_active` flags instead of `DELETE`. Data is never truly lost.

4. **Denormalized inbox** — `InboxConversation.last_message` is duplicated data, but it eliminates a JOIN on every inbox list query. Worth the trade-off for real-time performance.

5. **Fernet encryption** — API keys encrypted at rest. Database dump alone doesn't expose secrets.

6. **Composite indexes** — Every multi-tenant query is indexed: `(tenant, created_at)`, `(tenant, status)`, etc.
