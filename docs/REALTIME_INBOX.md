# Real-Time Inbox System

> How MetaPilot delivers instant WhatsApp messages to the dashboard using WebSockets.

---

## Why a Separate Inbox?

The `messaging` app stores messages in normalized tables (`Conversation` → `Message`) optimized for data integrity. But the inbox UI needs different things:

- **Fast list rendering** — Show 50 conversations with last message, sorted by time
- **Unread counts** — Without counting messages on every page load
- **Real-time updates** — New messages appear instantly, no polling
- **Lightweight payloads** — Only send what the UI needs

So the `inbox` app is a **denormalized, real-time-optimized layer** on top of messaging. Think of it as a "view" over the message data, optimized for the UI.

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                   Dashboard (Next.js)                  │
│                                                        │
│  WebSocket Connection                                  │
│  ws://localhost:8000/ws/inbox/{tenant_id}/?token=JWT   │
│                                                        │
│  Events received:                                      │
│  • new_message → append to chat                        │
│  • status_update → update ✓✓ indicators               │
│  • conversation_update → update sidebar list           │
└──────────────────────┬────────────────────────────────┘
                       │ WebSocket
┌──────────────────────▼────────────────────────────────┐
│          Django Channels (Daphne ASGI Server)          │
│                                                        │
│  InboxConsumer                                         │
│  ├── connect() → authenticate, join group              │
│  ├── disconnect() → leave group                        │
│  ├── inbox_message() → forward to client               │
│  ├── inbox_status() → forward status update            │
│  └── inbox_conversation() → forward conversation data  │
│                                                        │
│  Channel Group: "inbox_{tenant_id}"                    │
└──────────────────────┬────────────────────────────────┘
                       │ Redis Channel Layer
┌──────────────────────▼────────────────────────────────┐
│                    Redis Server                        │
│  Pub/Sub channel: "inbox_{tenant_id}"                  │
└──────────────────────┬────────────────────────────────┘
                       │ published by
┌──────────────────────▼────────────────────────────────┐
│              Event Emitters (service layer)             │
│                                                        │
│  emit_new_message(tenant_id, message_data)             │
│  emit_status_update(tenant_id, status_data)            │
│  emit_conversation_update(tenant_id, conversation)     │
└───────────────────────────────────────────────────────┘
```

---

## Data Model

### InboxConversation

A denormalized conversation record per customer phone per tenant.

```python
class InboxConversation(models.Model):
    id = models.UUIDField(primary_key=True)
    tenant = models.ForeignKey(Tenant)
    
    # Customer info (cached for display)
    customer_phone = models.CharField(max_length=20)
    customer_name = models.CharField(max_length=255, blank=True)
    
    # Denormalized for fast list rendering
    last_message = models.TextField(blank=True)        # Preview text
    last_message_time = models.DateTimeField(null=True) # Sort key
    last_direction = models.CharField()                 # INBOUND/OUTBOUND
    unread_count = models.IntegerField(default=0)       # Badge count
    
    # Status
    status = models.CharField(default='ACTIVE')  # ACTIVE, ARCHIVED, BLOCKED
    is_pinned = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('tenant', 'customer_phone')
        ordering = ['-last_message_time']
        indexes = [
            models.Index(fields=['tenant', '-last_message_time']),
            models.Index(fields=['tenant', 'status']),
        ]
```

**Why denormalize?** The inbox sidebar query is:
```sql
SELECT * FROM inbox_conversations
WHERE tenant_id = %s AND status = 'ACTIVE'
ORDER BY last_message_time DESC
LIMIT 50;
```
That's a **single indexed query** — no JOINs, no subqueries, no COUNT aggregations. Sub-millisecond response time even with thousands of conversations.

### InboxMessage

```python
class InboxMessage(models.Model):
    id = models.UUIDField(primary_key=True)
    conversation = models.ForeignKey(InboxConversation)
    
    direction = models.CharField()        # INBOUND or OUTBOUND
    message_type = models.CharField()     # text, image, document, etc.
    content_json = models.JSONField()     # Full message content
    
    status = models.CharField(default='SENT')  # SENT, DELIVERED, READ, FAILED
    meta_message_id = models.CharField(unique=True, null=True)  # Dedup key
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']  # Chronological within conversation
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]
```

**`content_json` structure:**

For a text message:
```json
{
    "type": "text",
    "text": "Hello, I need help with my order"
}
```

For an image message:
```json
{
    "type": "image",
    "media_url": "https://cdn.meta.com/...",
    "caption": "Here's the product I want"
}
```

This flexible JSON structure handles all WhatsApp message types without needing separate columns for each.

---

## WebSocket Consumer

### Connection Flow

```python
class InboxConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        # 1. Extract tenant_id from URL
        self.tenant_id = self.scope['url_route']['kwargs']['tenant_id']
        self.group_name = f"inbox_{self.tenant_id}"
        
        # 2. Authenticate user from JWT token (query param)
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return
        
        # 3. Verify user belongs to this tenant
        if str(user.tenant_id) != self.tenant_id:
            await self.close(code=4003)
            return
        
        # 4. Join the tenant's channel group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        # 5. Accept the WebSocket connection
        await self.accept()
```

**Authentication:** JWT token is passed as a query parameter (`?token=eyJ...`). The `TokenAuthMiddleware` in `core/asgi.py` extracts and validates it before the consumer connects.

### Event Handlers

```python
    async def inbox_message(self, event):
        """New message received — forward to WebSocket client"""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'data': event['data']
        }))
    
    async def inbox_status(self, event):
        """Message status updated (delivered/read)"""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'data': event['data']
        }))
    
    async def inbox_conversation(self, event):
        """Conversation metadata updated (new unread count, etc.)"""
        await self.send(text_data=json.dumps({
            'type': 'conversation_update',
            'data': event['data']
        }))
```

---

## Event Emitters

These functions broadcast events to all connected clients for a tenant:

```python
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

channel_layer = get_channel_layer()

def emit_new_message(tenant_id, message_data):
    """Broadcast a new message to all dashboard users of this tenant"""
    async_to_sync(channel_layer.group_send)(
        f"inbox_{tenant_id}",
        {
            'type': 'inbox.message',   # Maps to inbox_message() handler
            'data': message_data
        }
    )

def emit_status_update(tenant_id, status_data):
    """Broadcast message status change (✓ → ✓✓ → blue ✓✓)"""
    async_to_sync(channel_layer.group_send)(
        f"inbox_{tenant_id}",
        {
            'type': 'inbox.status',
            'data': status_data
        }
    )

def emit_conversation_update(tenant_id, conversation_data):
    """Broadcast conversation list changes"""
    async_to_sync(channel_layer.group_send)(
        f"inbox_{tenant_id}",
        {
            'type': 'inbox.conversation',
            'data': conversation_data
        }
    )
```

**`async_to_sync`** is needed because emitters are called from synchronous Django views/services, but the channel layer is async. This wrapper handles the event loop bridging.

---

## Inbound Message Flow

When a customer sends a WhatsApp message, here's the complete flow:

```
Customer sends "Hi" on WhatsApp
    │
    ▼
Meta sends POST to /api/webhooks/receive/
    │
    ▼
Webhook handler calls InboxSendService.ingest_inbound_message()
    │
    ▼
┌───────────────────────────────────────────────────┐
│  InboxSendService.ingest_inbound_message()        │
│                                                    │
│  1. Find or create InboxConversation               │
│     get_or_create(tenant=t, customer_phone=phone)  │
│                                                    │
│  2. Create InboxMessage                            │
│     InboxMessage.objects.create(                   │
│         conversation=conv,                         │
│         direction='INBOUND',                       │
│         message_type='text',                       │
│         content_json={'type':'text','text':'Hi'},  │
│         meta_message_id='wamid.xxx'                │
│     )                                              │
│                                                    │
│  3. Update conversation snapshot                   │
│     conv.last_message = 'Hi'                       │
│     conv.last_message_time = now()                 │
│     conv.last_direction = 'INBOUND'                │
│     conv.unread_count += 1                         │
│     conv.save()                                    │
│                                                    │
│  4. Emit WebSocket events                          │
│     emit_new_message(tenant_id, ...)               │
│     emit_conversation_update(tenant_id, ...)       │
└───────────────────────────────────────────────────┘
    │
    ▼
All connected dashboard users see the message instantly
```

---

## Outbound Message Flow

When a dashboard user sends a reply:

```
Dashboard user types "Your order is on the way" and clicks Send
    │
    ▼
POST /inbox/messages/
{
    "conversation": "conv-uuid",
    "message_type": "text",
    "content_json": {"type": "text", "text": "Your order is on the way"}
}
    │
    ▼
┌───────────────────────────────────────────────────┐
│  InboxSendService.send_message()                   │
│                                                    │
│  1. Load conversation + tenant credentials         │
│     access_token = decrypt(config.access_token)    │
│     phone_number_id = decrypt(config.phone_id)     │
│                                                    │
│  2. Send via WhatsApp API                          │
│     service = WhatsAppService(token, phone_id)     │
│     result = service.send_text(                    │
│         to=conv.customer_phone,                    │
│         text="Your order is on the way"            │
│     )                                              │
│                                                    │
│  3. Create InboxMessage                            │
│     InboxMessage.objects.create(                   │
│         direction='OUTBOUND',                      │
│         status='SENT',                             │
│         meta_message_id=result['messages'][0]['id']│
│     )                                              │
│                                                    │
│  4. Update conversation + emit events              │
└───────────────────────────────────────────────────┘
```

---

## REST Endpoints

### List Conversations

```
GET /inbox/conversations/
```

Returns paginated list sorted by `last_message_time` descending:

```json
{
    "count": 156,
    "results": [
        {
            "id": "uuid",
            "customer_phone": "919876543210",
            "customer_name": "John Doe",
            "last_message": "Your order is on the way",
            "last_message_time": "2026-06-15T10:30:00Z",
            "last_direction": "OUTBOUND",
            "unread_count": 0,
            "status": "ACTIVE",
            "is_pinned": false
        }
    ]
}
```

### Get Messages for Conversation

```
GET /inbox/conversations/{id}/messages/
```

Paginated, chronologically ordered messages:

```json
{
    "count": 45,
    "results": [
        {
            "id": "uuid",
            "direction": "INBOUND",
            "message_type": "text",
            "content_json": {"type": "text", "text": "Hi, I need help"},
            "status": "DELIVERED",
            "created_at": "2026-06-15T10:25:00Z"
        },
        {
            "id": "uuid",
            "direction": "OUTBOUND",
            "message_type": "text",
            "content_json": {"type": "text", "text": "Sure, how can I help?"},
            "status": "READ",
            "created_at": "2026-06-15T10:26:00Z"
        }
    ]
}
```

### Mark Conversation as Read

```
POST /inbox/conversations/{id}/mark-read/
```

Resets `unread_count` to 0 and emits a conversation update event.

---

## Frontend Integration (Next.js)

Here's how the dashboard connects:

```javascript
// Simplified WebSocket client
const ws = new WebSocket(
    `ws://localhost:8000/ws/inbox/${tenantId}/?token=${accessToken}`
);

ws.onmessage = (event) => {
    const { type, data } = JSON.parse(event.data);
    
    switch (type) {
        case 'new_message':
            // Append message to current chat
            if (data.conversation_id === activeConversationId) {
                appendMessage(data);
            }
            // Play notification sound for inbound
            if (data.direction === 'INBOUND') {
                playNotificationSound();
            }
            break;
            
        case 'status_update':
            // Update message status indicators (✓ → ✓✓)
            updateMessageStatus(data.meta_message_id, data.status);
            break;
            
        case 'conversation_update':
            // Update sidebar (last message, unread count, sort order)
            updateConversationList(data);
            break;
    }
};
```

---

## Scaling Considerations

| Concern | Solution |
|---------|----------|
| Many concurrent WebSocket connections | Daphne handles thousands per process. Scale horizontally with multiple workers behind a load balancer. |
| Redis memory for channel layer | Messages are transient — only buffered briefly. Redis memory usage stays low. |
| Cross-server WebSocket delivery | Redis channel layer handles pub/sub across multiple Daphne instances automatically. |
| Connection drops | Frontend auto-reconnects with exponential backoff. Missed messages are fetched via REST API. |
