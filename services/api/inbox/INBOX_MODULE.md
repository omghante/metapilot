# Inbox Module – Regression & Safety Validation

## Summary

The **inbox** Django app is a **pure extension layer**.
It adds new tables, new endpoints, and new WebSocket channels without
modifying any existing file from the original codebase (except the three
registration points listed below).

---

## Files Changed in Existing Codebase

| File | Change Type | Description |
|------|-------------|-------------|
| `core/settings.py` | Additive | Added `daphne`, `channels`, `inbox` to `INSTALLED_APPS`; added `ASGI_APPLICATION` and `CHANNEL_LAYERS` config |
| `core/urls.py` | Additive | Added `path('chat-inbox/', include('inbox.urls'))` |
| `core/asgi.py` | Additive | Wrapped Django ASGI app in `ProtocolTypeRouter` to enable WebSocket |
| `requirements.txt` | Additive | Added `channels>=4.0`, `channels-redis>=4.2`, `daphne>=4.0` |

No existing app code was modified.

---

## New Files Created

```
inbox/
├── __init__.py
├── admin.py              – Django admin registration (read-only views)
├── apps.py               – InboxConfig with ready() signal hook
├── migrations/
│   └── 0001_initial.py   – Creates inbox_conversations + inbox_messages tables
├── models.py             – InboxConversation, InboxMessage
├── routing.py            – WebSocket URL patterns
├── serializers.py        – DRF serializers
├── services.py           – InboxSendService (outbound message sending)
├── urls.py               – REST URL patterns
├── views.py              – API views
├── webhook_listener.py   – post_save signal listener on messaging.Message
└── websocket.py          – InboxConsumer + sync event emitters
```

---

## New Database Tables

### `inbox_conversations`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | FK → tenants_tenant | |
| customer_phone | VARCHAR(30) | E.164 format |
| customer_name | VARCHAR(255) | |
| last_message | TEXT | Denormalized preview |
| last_message_time | DATETIME | Indexed |
| unread_count | INT | Reset on mark-read |
| created_at / updated_at | DATETIME | |

Unique constraint: `(tenant_id, customer_phone)`

### `inbox_messages`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | FK → tenants_tenant | |
| conversation_id | FK → inbox_conversations | |
| meta_message_id | VARCHAR(200) | WhatsApp wamid; indexed for dedup |
| direction | INBOUND / OUTBOUND | |
| type | TEXT / IMAGE / … | |
| content_json | JSON | Full Meta payload |
| status | PENDING / SENT / DELIVERED / READ / FAILED | |
| timestamp | BIGINT | Meta epoch |
| error_code / error_message | | |
| created_at | DATETIME | |

---

## New REST Endpoints

Base prefix: `/chat-inbox/`  
Auth: Bearer JWT (existing `rest_framework_simplejwt`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/chat-inbox/conversations/` | List tenant conversations |
| GET | `/chat-inbox/conversations/{id}/` | Get single conversation |
| POST | `/chat-inbox/conversations/{id}/mark-read/` | Reset unread_count |
| GET | `/chat-inbox/conversations/{id}/messages/` | List messages |
| POST | `/chat-inbox/messages/` | Send outbound message |

---

## WebSocket Endpoint

```
ws://<host>/ws/inbox/{tenant_id}/?token=<jwt_access_token>
```

Events emitted by server → client:

| Event type | Payload |
|------------|---------|
| `new_message` | Full `InboxMessage` serializer data |
| `status_update` | `{meta_message_id, status}` |
| `conversation_update` | Full `InboxConversationList` serializer data |

---

## Webhook Extension Strategy (Non-breaking)

The existing `webhooks/views.py → WebhookReceiveView` is **not modified**.

The inbox attaches a Django `post_save` signal on `messaging.models.Message`
in `InboxConfig.ready()`. When the existing webhook controller saves a message,
the signal fires and:

1. Mirrors the inbound message into `inbox_conversations` + `inbox_messages`.
2. Updates the conversation snapshot (last_message, unread_count).
3. Emits a WebSocket event to the tenant channel.

Signal errors are caught and logged — they can never bubble up to break
the existing webhook 200 response.

---

## Regression Checklist

Run these checks before every deployment:

- [ ] `python manage.py check` — zero issues
- [ ] `python manage.py migrate --check` — no pending migrations on existing apps
- [ ] `GET /api/conversations/` still returns existing messaging conversations
- [ ] `POST /api/messages/` (existing universal_send) still works
- [ ] `GET /api/webhooks/verify/` still responds to Meta verification
- [ ] `POST /api/webhooks/receive/` stores messages into `messaging.Message`
- [ ] Template sending endpoint unchanged
- [ ] No tenant mapping changes
- [ ] `GET /chat-inbox/conversations/` returns 401 without JWT
- [ ] `GET /chat-inbox/conversations/` returns 200 with valid JWT
- [ ] `WS /ws/inbox/{tenant_id}/?token=invalid` closes with code 4001
- [ ] `WS /ws/inbox/{tenant_id}/?token=<valid>` connects and receives events

---

## Environment Variables Added

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHANNEL_REDIS_URL` | falls back to `CELERY_BROKER_URL`, then `redis://localhost:6379/1` | Redis URL for Django Channels layer |

No existing environment variables modified.
