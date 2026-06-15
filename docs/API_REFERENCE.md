# API Reference

> Complete documentation of every REST API endpoint in MetaPilot.
> Base URL: `http://localhost:8000`

---

## Table of Contents

- [Authentication](#authentication)
- [Setup (One-Time)](#setup-one-time)
- [Dashboard](#dashboard)
- [Agencies](#agencies)
- [Clients (Tenants)](#clients-tenants)
- [Users](#users)
- [Contacts](#contacts)
- [Conversations & Messages](#conversations--messages)
- [Campaigns](#campaigns)
- [Campaign Messages](#campaign-messages)
- [Scheduler Jobs](#scheduler-jobs)
- [Templates](#templates)
- [Universal Send](#universal-send)
- [Media Assets](#media-assets)
- [Contact Import](#contact-import)
- [Webhooks (Meta WhatsApp)](#webhooks-meta-whatsapp)
- [Inbox (Real-Time Chat)](#inbox-real-time-chat)
- [Notifications](#notifications)
- [Chatbot](#chatbot)
- [Analytics & Quotas](#analytics--quotas)
- [Health Check](#health-check)
- [API Documentation (Swagger)](#api-documentation-swagger)

---

## Authentication

All API endpoints (except login, register, setup, webhooks) require a JWT Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### POST `/api/auth/login/`

**What it does:** Authenticates a user and returns JWT tokens.

**Who can use it:** Anyone (no auth required)

**Request:**
```json
{
  "email": "admin@example.com",
  "password": "securepassword"
}
```

**Response (200 OK):**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@example.com",
    "first_name": "Om",
    "last_name": "Ghante",
    "role": "SUPER_ADMIN",
    "tenant": null
  }
}
```

**What happens internally:**
1. Email is normalized to lowercase
2. Django's `authenticate()` verifies credentials against hashed password
3. If user's tenant is suspended → 403 error
4. JWT token includes custom claims: `role` and `tenant_id`
5. Login attempt is logged in `AuditLog` (success or failure)

**Error Responses:**
- `400` — Missing email or password
- `401` — Invalid credentials
- `403` — Account disabled or tenant suspended

---

### POST `/api/auth/register/`

**What it does:** Creates a new user account.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "first_name": "John",
  "last_name": "Doe",
  "role": "TENANT_USER",
  "tenant": "uuid-of-tenant"
}
```

**What happens internally:**
1. Password is hashed using Django's PBKDF2 algorithm
2. User is created with the specified role
3. `AuditLog` entry is created
4. Super admins are notified via the notification system

---

### GET `/api/auth/me/`

**What it does:** Returns the currently authenticated user's profile.

**Auth required:** Yes

**Response (200 OK):**
```json
{
  "id": "uuid",
  "email": "admin@example.com",
  "first_name": "Om",
  "last_name": "Ghante",
  "role": "SUPER_ADMIN",
  "tenant": null,
  "agency": null,
  "is_active": true
}
```

---

### PATCH `/api/auth/me/`

**What it does:** Updates the current user's profile (first_name, last_name, phone).

---

### GET `/api/auth/my-tenant/`

**What it does:** Returns the tenant details for the current user. Returns 404 if the user is a Super Admin (they don't belong to a tenant).

---

### POST `/api/auth/refresh/`

**What it does:** Exchanges a refresh token for a new access token.

**Request:**
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:**
```json
{
  "access": "new_access_token_here"
}
```

**How token rotation works:**
1. Old refresh token is blacklisted (can't be reused)
2. New access token is generated (valid for 60 minutes)
3. New refresh token is generated (valid for 7 days)

---

### POST `/api/auth/logout/`

**What it does:** Blacklists the refresh token so it can't be used again.

**Request:**
```json
{
  "refresh": "refresh_token_to_blacklist"
}
```

---

## Setup (One-Time)

### GET `/api/setup/status/`

**What it does:** Checks if the platform has been set up (i.e., if a super admin exists).

**Auth required:** No

**Response:**
```json
{
  "is_setup": false,
  "super_admin_count": 0
}
```

---

### POST `/api/setup/create-superadmin/`

**What it does:** Creates the first super admin. Only works if no super admin exists yet.

**Request:**
```json
{
  "email": "admin@example.com",
  "password": "securepassword",
  "first_name": "Om",
  "last_name": "Ghante"
}
```

---

## Dashboard

### GET `/api/dashboard/`

**What it does:** Returns platform-wide overview stats for Super Admins.

**Auth required:** Yes (SUPER_ADMIN only)

**Response:**
```json
{
  "total_agencies": 5,
  "total_clients": 23,
  "total_users": 87,
  "total_campaigns": 156,
  "active_campaigns": 12,
  "total_messages_sent": 45230,
  "recent_audit_logs": [...]
}
```

---

### GET `/api/dashboard/analytics/`

**What it does:** Returns analytics data (message delivery rates, campaign performance).

---

### GET `/api/my-dashboard/`

**What it does:** Returns dashboard data for Tenant Admins/Users (scoped to their tenant only).

---

### GET `/api/agency/dashboard/`

**What it does:** Returns dashboard for Agency Admins (stats across all their clients).

---

## Agencies

> Agencies are resellers who manage multiple clients.

### Standard CRUD — `GET/POST/PATCH/DELETE /api/agencies/`

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/agencies/` | List all agencies | SUPER_ADMIN |
| POST | `/api/agencies/` | Create new agency | SUPER_ADMIN |
| GET | `/api/agencies/{id}/` | Get agency details | SUPER_ADMIN |
| PATCH | `/api/agencies/{id}/` | Update agency | SUPER_ADMIN |
| DELETE | `/api/agencies/{id}/` | Delete agency | SUPER_ADMIN |

**Agency Object:**
```json
{
  "id": "uuid",
  "name": "Digital Marketing Co",
  "slug": "digital-marketing-co",
  "contact_email": "info@dmc.com",
  "phone": "+919876543210",
  "status": "ACTIVE",
  "commission_percent": "10.00",
  "client_count": 5,
  "created_at": "2026-01-15T10:00:00Z"
}
```

---

## Clients (Tenants)

> Each client is a business with its own WhatsApp number, contacts, and campaigns.

### Standard CRUD — `GET/POST/PATCH/DELETE /api/clients/`

**Client Object:**
```json
{
  "id": "uuid",
  "name": "Acme Corp",
  "slug": "acme-corp",
  "business_type": "ECOMMERCE",
  "agency": "uuid-of-agency",
  "status": "ACTIVE",
  "plan_type": "PRO",
  "monthly_message_limit": 10000,
  "active_users_limit": 10,
  "api_rate_limit": 120,
  "whatsapp_enabled": true,
  "campaigns_enabled": true,
  "ai_features_enabled": true,
  "webhook_token": "auto_generated_token",
  "webhook_url": "https://your-domain.com/api/wa-chatbot/webhook/{id}/",
  "user_count": 3,
  "created_at": "2026-01-20T10:00:00Z"
}
```

**Business Types:** `ECOMMERCE`, `SERVICE`, `SAAS`, `RETAIL`, `HEALTHCARE`, `EDUCATION`, `OTHER`

**Plan Types:** `FREE` (1000 msg/mo), `STARTER`, `PRO`, `ENTERPRISE`

---

### Agency Client Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/agency/clients/` | List agency's clients |
| GET | `/api/agency/clients/{id}/` | Get client detail |
| POST | `/api/agency/clients/{id}/suspend/` | Suspend a client |
| POST | `/api/agency/clients/{id}/activate/` | Reactivate a client |

---

## Tenant Configuration (Encrypted API Keys)

### `GET/POST/PATCH /api/configs/`

**What it does:** Manages encrypted API credentials for each tenant's WhatsApp Business account.

**How encryption works:**
1. When you POST a value (e.g., Meta access token), it's encrypted using Fernet (AES-256)
2. The encrypted value is stored in the `tenant_configs` table
3. When the system needs the token (to send a message), it decrypts on-the-fly
4. The decrypted value is **never** returned to the frontend

**Required WhatsApp configs per tenant:**

| key_name | Description | Example |
|----------|-------------|---------|
| `access_token` | Meta Graph API access token | `EAAGm0PX4...` |
| `phone_number_id` | WhatsApp phone number ID | `109876543210` |
| `business_account_id` | WhatsApp Business Account ID | `104253789012` |
| `webhook_verify_token` | Webhook verification token | `my_custom_verify_token` |
| `app_secret` | Meta App Secret (for webhook signature) | `abc123def456` |

---

## Contacts

### Standard CRUD — `GET/POST/PATCH/DELETE /api/contacts/`

**Contact Object:**
```json
{
  "id": "uuid",
  "phone": "919876543210",
  "name": "John Doe",
  "email": "john@example.com",
  "tags": ["VIP", "newsletter"],
  "metadata": {"city": "Mumbai", "source": "website"},
  "is_subscribed": true,
  "is_blocked": false,
  "created_at": "2026-02-01T10:00:00Z"
}
```

**Key behaviors:**
- Phone numbers are unique per tenant (two tenants can have the same phone)
- All queries are automatically scoped to the current user's tenant
- Tags are JSON arrays used for campaign targeting

---

### POST `/api/contacts/import/`

**What it does:** Imports contacts from a CSV or XLSX file.

**Request:** Multipart form data with:
- `file` — CSV/XLSX file with columns: `phone`, `name`, `email`
- `tags` — Optional JSON array of tags to apply

**Response:**
```json
{
  "id": "uuid",
  "file_name": "customers.csv",
  "status": "PROCESSING",
  "total_rows": 500,
  "imported_count": 0,
  "duplicate_count": 0,
  "error_count": 0
}
```

---

## Conversations & Messages

### `GET /api/conversations/`

**What it does:** Lists all conversations for the current tenant, ordered by last message time.

### `GET /api/messages/`

**What it does:** Lists messages, optionally filtered by conversation.

**Message Object:**
```json
{
  "id": "uuid",
  "conversation": "uuid",
  "wa_message_id": "wamid.xxx",
  "direction": "INBOUND",
  "message_type": "TEXT",
  "status": "DELIVERED",
  "content": "Hello, I need help with my order",
  "payload": {},
  "media_url": null,
  "sent_at": "2026-03-01T10:00:00Z",
  "delivered_at": "2026-03-01T10:00:01Z",
  "read_at": "2026-03-01T10:00:05Z"
}
```

**Message Types:** `TEXT`, `IMAGE`, `DOCUMENT`, `AUDIO`, `VIDEO`, `STICKER`, `LOCATION`, `CONTACTS`, `TEMPLATE`, `INTERACTIVE`, `REACTION`

**Message Statuses:** `PENDING` → `SENT` → `DELIVERED` → `READ` (or `FAILED`)

---

## Campaigns

### Standard CRUD — `GET/POST/PATCH/DELETE /api/campaigns/`

**Campaign Object:**
```json
{
  "id": "uuid",
  "name": "Summer Sale 2026",
  "description": "20% off all products",
  "campaign_type": "promotional",
  "template_name": "summer_sale_offer",
  "template_params": ["20%", "Summer"],
  "template_type": "standard",
  "status": "DRAFT",
  "scheduled_at": "2026-06-20T10:00:00Z",
  "target_tags": ["newsletter", "VIP"],
  "target_all": false,
  "recipient_count": 250,
  "sent_count": 248,
  "created_at": "2026-06-15T08:00:00Z"
}
```

**Campaign Statuses:** `DRAFT` → `SCHEDULED` → `ACTIVE` → `COMPLETED` (or `PAUSED` / `CANCELLED`)

**Campaign Types:** `announcement`, `promotional`, `reminder`, `follow_up`

---

## Campaign Messages

> Individual schedulable messages within a campaign. Each can have a different send time.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/campaigns/{id}/messages/` | List messages in campaign |
| POST | `/api/campaigns/{id}/messages/` | Create a message |
| GET | `/api/campaigns/{id}/messages/{msg_id}/` | Get message detail |
| PATCH | `/api/campaigns/{id}/messages/{msg_id}/` | Update (only if PENDING) |
| DELETE | `/api/campaigns/{id}/messages/{msg_id}/` | Delete message |
| GET | `/api/campaigns/{id}/messages/{msg_id}/recipients/` | View recipients |

---

## Scheduler Jobs

### `GET /api/scheduler/jobs/`

**What it does:** Lists all scheduled message delivery jobs for the current tenant.

**Job Object:**
```json
{
  "id": "uuid",
  "template_name": "welcome_offer",
  "template_type": "standard",
  "language_code": "en_US",
  "scheduled_time": "2026-06-20T04:30:00Z",
  "status": "pending",
  "total_recipients": 100,
  "sent_count": 0,
  "failed_count": 0,
  "success_rate": 0.0,
  "priority": 5,
  "retry_count": 0,
  "max_retries": 3,
  "claimed_by": "",
  "created_at": "2026-06-15T08:00:00Z"
}
```

**Job Statuses:** `pending` → `processing` → `completed` / `partial_failure` / `failed` / `cancelled`

---

## Templates

### GET `/api/templates/client/`

**What it does:** Lists WhatsApp templates assigned to the current tenant by the Super Admin.

### GET `/api/templates/meta/`

**What it does:** Returns templates directly from Meta's Graph API (cached locally). Includes filters by status, category, industry, and feature group.

**Query parameters:**
- `status` — APPROVED, PENDING, REJECTED
- `category` — UTILITY, MARKETING, AUTHENTICATION
- `industry` — E-commerce, Healthcare, etc.
- `search` — Full-text search on template name/body

### POST `/api/templates/meta/sync/`

**What it does:** Triggers an immediate sync of templates from Meta's Graph API. Templates are also auto-synced every 5 minutes via Celery Beat.

### POST `/api/templates/meta/create/`

**What it does:** Creates a new template on Meta's platform via Graph API.

### GET `/api/templates/meta/status/{template_name}/`

**What it does:** Checks the approval status of a specific template.

### DELETE `/api/templates/meta/delete/{template_name}/`

**What it does:** Deletes a template from Meta's platform.

---

## Universal Send

### POST `/api/messaging/send`

> **This is the most important endpoint in the platform.** It handles sending WhatsApp template messages — both immediately and scheduled.

**Auth required:** Yes (must be a Tenant Member)

**Standard Template Request:**
```json
{
  "phoneNumbers": ["919876543210", "919876543211"],
  "templateName": "welcome_offer",
  "language": "en_US",
  "templateType": "standard",
  "date": "2026-06-20",
  "time": "14:30",
  "header": {
    "type": "image",
    "url": "https://example.com/banner.jpg"
  },
  "bodyParams": ["John", "20% OFF"],
  "buttonParams": [
    {"sub_type": "quick_reply", "text": "Yes", "index": 0}
  ]
}
```

**Carousel Template Request:**
```json
{
  "phoneNumbers": ["919876543210"],
  "templateName": "product_showcase",
  "language": "en_US",
  "templateType": "carousel",
  "date": "2026-06-20",
  "time": "14:30",
  "bodyParams": ["Welcome to our store!"],
  "cards": [
    {
      "header": {"type": "image", "url": "https://example.com/p1.jpg"},
      "bodyParams": ["Product 1", "₹999"],
      "buttonParams": [
        {"sub_type": "url", "text": "/product/1", "index": 0},
        {"sub_type": "quick_reply", "text": "Buy Now", "index": 1}
      ]
    },
    {
      "header": {"type": "image", "url": "https://example.com/p2.jpg"},
      "bodyParams": ["Product 2", "₹1499"],
      "buttonParams": [
        {"sub_type": "url", "text": "/product/2", "index": 0},
        {"sub_type": "quick_reply", "text": "Buy Now", "index": 1}
      ]
    }
  ]
}
```

**How the scheduling logic works:**

1. The `date` and `time` fields are in IST (Indian Standard Time)
2. They're converted to UTC internally
3. If the scheduled time is ≤ 1 minute from now → **send immediately**
4. Otherwise → **create a SchedulerJob** and return the job ID

**Immediate Response (200):**
```json
{
  "success": true,
  "immediate": true,
  "templateType": "standard",
  "message": "Messages sent immediately",
  "total": 2,
  "sent": 2,
  "failed": 0,
  "results": [
    {"phone": "919876543210", "success": true, "messageId": "wamid.xxx"},
    {"phone": "919876543211", "success": true, "messageId": "wamid.yyy"}
  ]
}
```

**Scheduled Response (201):**
```json
{
  "scheduled": true,
  "templateType": "carousel",
  "jobId": "uuid",
  "scheduledFor": "20/06/2026, 02:30:00 PM",
  "scheduledForUTC": "2026-06-20T09:00:00Z",
  "recipientCount": 1
}
```

**Deduplication:** An MD5 hash is generated from `templateName + templateType + phoneNumbers + date + time + params`. If a matching hash already exists in pending/processing state → `409 Conflict`.

---

## Media Assets

### `GET/POST/DELETE /api/media/`

**What it does:** Manages uploaded media files (images, videos, documents) for campaign templates.

**How media storage works:**
- Files up to 5MB are stored directly in PostgreSQL as binary data (`BinaryField`)
- Each file gets a `public_token` for secure unauthenticated access (needed by Meta's API to fetch header images)
- The URL format: `/api/media/{id}/file/?token={public_token}`

---

## Webhooks (Meta WhatsApp)

> These endpoints are PUBLIC (no auth). They're called by Meta's servers.

### GET `/api/webhooks/verify/`

**What it does:** Handles webhook verification from Meta.

**How it works:**
1. Meta sends: `hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=12345`
2. We find the tenant whose stored `webhook_verify_token` matches
3. If match → return the `hub.challenge` value
4. If no match → 403 Forbidden

### POST `/api/webhooks/receive/`

**What it does:** Receives incoming WhatsApp messages and status updates.

**What happens when a message arrives:**
1. Parse the webhook payload from Meta
2. Find the tenant by matching `phone_number_id` from webhook metadata
3. Verify HMAC-SHA256 signature using the tenant's `app_secret`
4. Store the message in the `messages` table
5. Feed it to the real-time inbox (`ingest_inbound_message`)
6. If AI chatbot is enabled → generate and send auto-reply
7. Always return 200 OK (even on errors, to prevent Meta from retrying)

---

## Inbox (Real-Time Chat)

> Separate from the messaging module — designed specifically for the inbox UI.

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/inbox/conversations/` | List conversations (sorted by last message) |
| GET | `/inbox/conversations/{id}/` | Get conversation detail |
| POST | `/inbox/conversations/{id}/mark-read/` | Reset unread count |
| GET | `/inbox/conversations/{id}/messages/` | Paginated message history |
| POST | `/inbox/messages/` | Send a message (text, image, etc.) |

### WebSocket

**URL:** `ws://localhost:8000/ws/inbox/{tenant_id}/?token=<jwt_access_token>`

**Events received:**
```json
{"type": "new_message", "data": {"id": "uuid", "direction": "INBOUND", "content_json": {...}}}
{"type": "status_update", "data": {"meta_message_id": "wamid.xxx", "status": "READ"}}
{"type": "conversation_update", "data": {"id": "uuid", "last_message": "Hello!", "unread_count": 3}}
```

---

## Notifications

### `GET /api/notifications/`

**What it does:** Lists notifications for the current user (filtered by role).

### `POST /api/notifications/{id}/read/`

**What it does:** Marks a notification as read.

**Notification Types:**
- `USER_REGISTERED` — New user signed up
- `CAMPAIGN_COMPLETED` — Campaign finished sending
- `CAMPAIGN_FAILED` — Campaign delivery failed
- `QUOTA_WARNING` — Approaching message limit
- `SECURITY_ALERT` — Suspicious activity detected

---

## Chatbot

### POST `/api/chatbot/ask/`

**What it does:** Platform assistant that answers questions about MetaPilot using RAG (Retrieval-Augmented Generation).

### WA Chatbot

The WhatsApp chatbot auto-replies to incoming messages. It works automatically when:
1. `WA_CHATBOT_ENABLED=True` in settings
2. A message arrives via webhook
3. The chatbot processes the message using OpenRouter AI
4. Reply is sent back via WhatsApp API

---

## Analytics & Quotas

### `GET /api/quotas/`

**What it does:** Returns message quota information for tenants.

### `GET/PATCH /api/clients/{client_id}/quota/`

**What it does:** View/update a client's daily and monthly message limits.

---

## Health Check

### GET `/health/`

**Response:**
```json
{"status": "healthy", "version": "1.0.0"}
```

### GET `/api/requirements/`

**What it does:** Comprehensive health check including database, Redis, and Celery worker status.

---

## API Documentation (Swagger)

| Endpoint | Description |
|----------|-------------|
| `GET /api/docs/` | Interactive Swagger UI |
| `GET /api/redoc/` | ReDoc documentation |
| `GET /api/schema/` | Raw OpenAPI 3.0 JSON schema |

These are auto-generated from the codebase using `drf-spectacular`.

---

## Pagination

All list endpoints use page-based pagination:

```
GET /api/contacts/?page=2&page_size=20
```

**Response format:**
```json
{
  "count": 500,
  "next": "http://localhost:8000/api/contacts/?page=3",
  "previous": "http://localhost:8000/api/contacts/?page=1",
  "results": [...]
}
```

Default page size: **20 items**.

---

## Error Response Format

All errors follow this format:

```json
{
  "error": "Description of what went wrong"
}
```

Or for validation errors:

```json
{
  "error": {
    "field_name": ["Error message for this field"]
  }
}
```

**Common HTTP Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found |
| 409 | Conflict (duplicate request) |
| 500 | Server Error |
