# Webhook System

> How MetaPilot receives and processes incoming WhatsApp messages from Meta's servers.

---

## What Are Webhooks?

When someone sends a WhatsApp message to your business number, Meta doesn't push it directly to you. Instead, Meta sends an **HTTP POST** to a URL you've configured — that's a webhook. MetaPilot receives these webhooks, parses them, and routes them to the correct tenant's inbox.

---

## The Two Webhook Endpoints

### 1. Verification (GET `/api/webhooks/verify/`)

Before Meta starts sending webhooks, it verifies your endpoint:

```
GET /api/webhooks/verify/?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=123456
```

**What happens internally:**
1. Extract `hub.verify_token` from the query string
2. Search `TenantConfig` for a config with `key_name='webhook_verify_token'` matching that value
3. If found → return `hub.challenge` as plain text (HTTP 200)
4. If not found → return 403 Forbidden

```python
def verify_webhook(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')
    
    if mode != 'subscribe':
        return HttpResponse(status=403)
    
    # Find which tenant this verify token belongs to
    config = TenantConfig.objects.filter(
        key_name='webhook_verify_token',
        is_active=True
    ).first()
    
    # Decrypt and compare
    for cfg in configs:
        if cfg.get_value() == token:
            return HttpResponse(challenge, status=200)
    
    return HttpResponse(status=403)
```

**Why iterate and decrypt?** Because verify tokens are Fernet-encrypted. We can't do a database `WHERE` on encrypted values — we decrypt each one and compare in Python. This is fine because there are typically <100 tenants.

---

### 2. Message Reception (POST `/api/webhooks/receive/`)

This is where all the action happens. Meta sends a POST with a JSON payload for every event: new messages, delivery status updates, read receipts, etc.

**Sample Meta webhook payload (incoming text message):**
```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "BUSINESS_ACCOUNT_ID",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "919876543210",
              "phone_number_id": "109876543210"
            },
            "contacts": [
              {
                "profile": {"name": "John Doe"},
                "wa_id": "919876543211"
              }
            ],
            "messages": [
              {
                "from": "919876543211",
                "id": "wamid.ABGGFlCGg...",
                "timestamp": "1718000000",
                "text": {"body": "Hi, I want to order a pizza"},
                "type": "text"
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
```

---

## Processing Pipeline

```
Meta's Server
    │
    │ POST /api/webhooks/receive/
    │ Headers: X-Hub-Signature-256: sha256=abc123...
    │
    ▼
┌──────────────────────────────────────────────┐
│  Step 1: Tenant Resolution                    │
│  Find tenant by phone_number_id from payload  │
│  metadata.phone_number_id → TenantConfig      │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│  Step 2: HMAC Signature Verification          │
│  Verify X-Hub-Signature-256 header            │
│  Using tenant's app_secret                    │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│  Step 3: Parse Event Type                     │
│  Is this a message? Status update? Error?     │
└─────┬──────────────┬────────────────┬────────┘
      │              │                │
      ▼              ▼                ▼
┌───────────┐  ┌───────────┐  ┌───────────────┐
│  Message   │  │  Status   │  │  Error         │
│  Handler   │  │  Handler  │  │  Handler       │
└─────┬─────┘  └─────┬─────┘  └───────┬───────┘
      │              │                  │
      ▼              ▼                  ▼
┌──────────────────────────────────────────────┐
│  Step 4: Store in Database                    │
│  Create/update Message records                │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│  Step 5: Feed to Inbox System                 │
│  ingest_inbound_message() → WebSocket push    │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼─────────────────────────┐
│  Step 6: AI Chatbot (Optional)                │
│  If WA_CHATBOT_ENABLED → auto-reply           │
└──────────────────────────────────────────────┘
```

---

## Step-by-Step Breakdown

### Step 1: Tenant Resolution

```python
# Extract phone_number_id from the webhook payload
phone_number_id = payload['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']

# Find the tenant that owns this phone number
config = TenantConfig.objects.filter(
    key_name='phone_number_id',
    is_active=True
)

# Decrypt each config value to find a match
for cfg in config:
    if cfg.get_value() == phone_number_id:
        tenant = cfg.tenant
        break
```

**Why can't we just do a WHERE query?** Because `phone_number_id` is stored encrypted with Fernet. We must decrypt each row and compare. This is a conscious security trade-off — the data is safe at rest, at the cost of a few microseconds per webhook.

### Step 2: HMAC-SHA256 Signature Verification

Meta signs every webhook payload with your App Secret. This prevents attackers from sending fake webhooks.

```python
def verify_signature(request, app_secret):
    # Meta sends: X-Hub-Signature-256: sha256=abc123def456...
    signature = request.headers.get('X-Hub-Signature-256', '')
    
    if not signature.startswith('sha256='):
        return False
    
    expected_signature = hmac.new(
        app_secret.encode('utf-8'),
        request.body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(
        signature[7:],  # Remove 'sha256=' prefix
        expected_signature
    )
```

**`hmac.compare_digest`** is used instead of `==` to prevent timing attacks. A regular `==` returns `False` faster when the first character doesn't match, leaking information about the expected value.

### Step 3: Message Handling

Different message types are parsed differently:

```python
# Text message
if msg_type == 'text':
    content = message['text']['body']

# Image message
elif msg_type == 'image':
    media_id = message['image']['id']
    caption = message['image'].get('caption', '')
    # Download media from Meta's CDN
    media_url = download_media(media_id, access_token)

# Document
elif msg_type == 'document':
    filename = message['document']['filename']
    media_id = message['document']['id']

# Location
elif msg_type == 'location':
    lat = message['location']['latitude']
    lng = message['location']['longitude']

# Interactive (button reply, list selection)
elif msg_type == 'interactive':
    interactive_type = message['interactive']['type']
    if interactive_type == 'button_reply':
        button_text = message['interactive']['button_reply']['title']
```

### Step 4: Database Storage

Messages are stored in two places:

1. **`messaging.Message`** — Legacy table for backward compatibility
2. **`inbox.InboxMessage`** — Optimized for real-time inbox UI

```python
# Create Message record
message = Message.objects.create(
    conversation=conversation,
    wa_message_id=wa_message_id,
    direction='INBOUND',
    message_type=msg_type,
    status='DELIVERED',
    content=content,
    payload=raw_payload,
    media_url=media_url,
    sent_at=timestamp
)

# Feed to inbox system
from inbox.services import InboxSendService
InboxSendService.ingest_inbound_message(
    tenant=tenant,
    sender_phone=from_number,
    sender_name=contact_name,
    message_data={
        'type': msg_type,
        'text': content,
        'media_url': media_url,
        'meta_message_id': wa_message_id,
        'timestamp': timestamp
    }
)
```

### Step 5: WebSocket Push

`ingest_inbound_message()` triggers a WebSocket event to all connected dashboard users:

```python
# Inside InboxSendService.ingest_inbound_message()
emit_new_message(
    tenant_id=str(tenant.id),
    message_data={
        'id': str(inbox_message.id),
        'conversation_id': str(conversation.id),
        'direction': 'INBOUND',
        'content_json': inbox_message.content_json,
        'sender_phone': sender_phone,
        'created_at': inbox_message.created_at.isoformat()
    }
)
```

Dashboard users see the new message **instantly** without polling.

### Step 6: AI Auto-Reply (Optional)

If `WA_CHATBOT_ENABLED=True` in settings:

```python
if settings.WA_CHATBOT_ENABLED:
    from wa_chatbot.service import WAChatbotService
    
    reply = WAChatbotService.generate_reply(
        tenant=tenant,
        customer_phone=from_number,
        message_text=content,
        message_type=msg_type,
        media_url=media_url  # For image messages → vision AI
    )
    
    if reply:
        WhatsAppService(access_token, phone_number_id).send_text(
            to=from_number,
            text=reply
        )
```

---

## Status Updates

Meta also sends status updates (sent, delivered, read) via the same webhook:

```json
{
  "entry": [{
    "changes": [{
      "value": {
        "statuses": [{
          "id": "wamid.ABGGFlCGg...",
          "status": "read",
          "timestamp": "1718000010",
          "recipient_id": "919876543211"
        }]
      }
    }]
  }]
}
```

**Processing:**
```python
for status_update in statuses:
    wa_message_id = status_update['id']
    new_status = status_update['status'].upper()
    
    # Update legacy message
    Message.objects.filter(wa_message_id=wa_message_id).update(
        status=new_status,
        delivered_at=now if new_status == 'DELIVERED' else F('delivered_at'),
        read_at=now if new_status == 'READ' else F('read_at')
    )
    
    # Update inbox message + push WebSocket event
    InboxSendService.update_message_status(
        tenant=tenant,
        meta_message_id=wa_message_id,
        status=new_status
    )
```

---

## Error Handling

### Always Return 200

This is critical. Even if processing fails, we **always** return HTTP 200 to Meta:

```python
def receive_webhook(request):
    try:
        # ... process webhook
        return JsonResponse({"status": "ok"}, status=200)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        # STILL return 200 — Meta will retry on non-200 responses,
        # potentially causing duplicate processing
        return JsonResponse({"status": "ok"}, status=200)
```

**Why?** If we return 500, Meta retries the webhook. If our processing was partially successful (message stored but WebSocket failed), the retry creates a duplicate. Better to log the error and investigate than to cause duplicate messages.

### Idempotency

Every message has a unique `wa_message_id` from Meta. Before creating a record, we check:

```python
if Message.objects.filter(wa_message_id=wa_message_id).exists():
    # Already processed — skip
    return
```

This handles Meta's "at-least-once" delivery guarantee safely.

---

## Security Considerations

| Threat | Mitigation |
|--------|-----------|
| Fake webhooks | HMAC-SHA256 signature verification |
| Replay attacks | Message ID deduplication |
| Credential exposure | Fernet-encrypted storage |
| DDoS via webhook | Rate limiting at infrastructure level |
| Cross-tenant leaks | Tenant resolved from encrypted phone_number_id |

---

## Meta Webhook Configuration

To set up webhooks for a new tenant:

1. Go to [Meta Developer Console](https://developers.facebook.com/)
2. Select your WhatsApp Business App
3. Navigate to WhatsApp → Configuration → Webhook
4. Set Callback URL: `https://your-domain.com/api/webhooks/receive/`
5. Set Verify Token: the value stored in `TenantConfig(key_name='webhook_verify_token')`
6. Subscribe to fields: `messages`

**Or** use the per-tenant chatbot webhook URL:
```
https://your-domain.com/api/wa-chatbot/webhook/{tenant_id}/
```
