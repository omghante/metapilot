# Scheduler Engine

> Deep dive into MetaPilot's distributed message delivery system.

---

## What Problem Does It Solve?

When a business wants to send 10,000 WhatsApp messages at 2:30 PM, we can't just fire them all at once. Meta has rate limits (80 msg/sec), network calls fail, and servers crash. The Scheduler Engine handles:

1. **Scheduling** — Store the job and execute at the right time
2. **Distribution** — Multiple workers process jobs in parallel safely
3. **Rate Limiting** — Never exceed Meta's API limits
4. **Retry Logic** — Automatically retry failed sends
5. **Exactly-Once Delivery** — Never send duplicate messages

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Celery Beat                           │
│  Runs every 3 seconds: check_and_process_due_jobs()      │
└────────────────────────┬─────────────────────────────────┘
                         │ triggers
┌────────────────────────▼─────────────────────────────────┐
│              SchedulerService.process_due_jobs()          │
│                                                           │
│  1. Find jobs WHERE status='pending'                      │
│     AND scheduled_time <= now()                           │
│  2. Lock each job (SELECT ... FOR UPDATE SKIP LOCKED)     │
│  3. For each locked job → spawn process_single_job()     │
└────────────────────────┬─────────────────────────────────┘
                         │ per job
┌────────────────────────▼─────────────────────────────────┐
│            SchedulerService.process_single_job()          │
│                                                           │
│  1. Claim the job (set claimed_by = worker_id)            │
│  2. Load recipients WHERE status='pending'                │
│  3. Get tenant credentials (decrypt access_token)         │
│  4. For each recipient:                                   │
│     a. Check rate limiter (token bucket)                  │
│     b. If allowed → send via WhatsAppService              │
│     c. Update recipient status (sent/failed)              │
│     d. Update job stats (sent_count, failed_count)        │
│  5. Finalize job:                                         │
│     - All sent → COMPLETED                                │
│     - Some failed → PARTIAL_FAILURE                       │
│     - All failed → retry or FAILED                        │
└──────────────────────────────────────────────────────────┘
```

---

## How Jobs Are Created

Jobs are created by the [Universal Send API](./API_REFERENCE.md#universal-send):

```python
# When scheduled_time > now + 1 minute:
job = SchedulerJob.objects.create(
    tenant=tenant,
    template_name="summer_sale",
    template_type="standard",
    language_code="en_US",
    header_data={"type": "image", "url": "..."},
    body_params=["20%", "Summer"],
    button_params=[...],
    cards_json=[...],  # Only for carousel
    scheduled_time=scheduled_utc,
    priority=5,
    max_retries=3,
    job_hash=md5_hash,  # For deduplication
)

# Create recipient records
for phone in phone_numbers:
    SchedulerJobRecipient.objects.create(
        job=job,
        phone_number=phone,
        status="pending"
    )
```

---

## Distributed Locking (How Multiple Workers Don't Collide)

The key challenge: if 3 Celery workers all run `process_due_jobs()` at the same time, they must not process the same job twice.

### Solution: `SELECT ... FOR UPDATE SKIP LOCKED`

```sql
SELECT * FROM scheduler_jobs
WHERE status = 'pending'
  AND scheduled_time <= NOW()
ORDER BY priority ASC, scheduled_time ASC
FOR UPDATE SKIP LOCKED
LIMIT 10;
```

**How this works:**
1. Worker A executes this query → gets jobs [1, 2, 3]
2. Worker B executes the same query → gets jobs [4, 5, 6] (because 1-3 are locked)
3. Worker C gets [7, 8, 9]
4. Each worker processes its batch independently

**`SKIP LOCKED`** is the magic — instead of waiting for locked rows, it skips them and grabs the next available ones.

### Claiming a Job

After locking, the worker "claims" the job:

```python
job.status = 'processing'
job.claimed_by = f"worker-{hostname}-{pid}"
job.save()
```

This is a safety net — if the worker crashes, we can identify abandoned jobs by checking `claimed_by` timestamps.

---

## Rate Limiting (Token Bucket Algorithm)

Meta allows 80 messages/second per WhatsApp number. MetaPilot enforces a conservative **50 tokens/sec** to leave headroom.

### Implementation: Redis + Lua Script

```python
# Rate limit check before each send
allowed = rate_limiter.check_rate_limit(
    key=f"wa_rate:{phone_number_id}",
    max_tokens=50,
    refill_rate=50,  # tokens per second
    cost=1
)

if not allowed:
    time.sleep(0.1)  # Back off for 100ms
    # Try again
```

**Why Lua?** The check-and-decrement must be atomic. A Lua script runs on the Redis server, eliminating race conditions between multiple workers.

**Token Bucket algorithm:**
1. Bucket starts with 50 tokens
2. Each send consumes 1 token
3. Tokens refill at 50/second
4. If bucket is empty → wait (back-pressure)

---

## Retry Logic

Not all failures are permanent. Network timeouts should be retried; invalid phone numbers should not.

### Retry Flow

```
Job fails (some recipients fail)
    │
    ├── retry_count < max_retries?
    │   ├── YES → status = 'pending'
    │   │         next_retry_at = now + (2^retry_count * 60s)
    │   │         retry_count += 1
    │   │         # Only failed recipients are retried
    │   │
    │   └── NO  → status = 'failed'
    │             # All retries exhausted
    │
    └── Success rate == 100%? → status = 'completed'
```

**Exponential backoff:**
- 1st retry: 2 minutes later
- 2nd retry: 4 minutes later
- 3rd retry: 8 minutes later (default max)

### Per-Recipient Error Isolation

Failed recipients are tracked individually:

```python
recipient.status = 'failed'
recipient.error_message = "Invalid phone number format"
recipient.attempts += 1
```

On retry, only `status='pending'` recipients are re-processed. Successfully sent recipients are never touched again.

---

## Message Sending (The Actual API Call)

For each recipient, the scheduler calls `WhatsAppService`:

### Standard Templates
```python
service = WhatsAppService(
    access_token=decrypted_token,
    phone_number_id=phone_number_id
)

# Build the components[] array
builder = ComponentsBuilder()
builder.set_header(header_type="image", header_data={"url": "https://..."})
builder.set_body_params(["20%", "Summer"])
builder.set_button_params([{"sub_type": "quick_reply", "text": "Shop Now", "index": 0}])
components = builder.build()

# Send
result = service.send_template(
    to="919876543210",
    template_name="summer_sale",
    language="en_US",
    components=components
)
```

### Carousel Templates

Carousel uses a different Meta API structure with `cards[]`:

```python
builder = ComponentsBuilder()
components = builder.build_carousel(
    body_params=["Welcome!"],
    cards=[
        {
            "header": {"type": "image", "url": "https://..."},
            "bodyParams": ["Product 1", "₹999"],
            "buttonParams": [{"sub_type": "url", "text": "/p/1", "index": 0}]
        },
        # ... more cards
    ]
)
```

---

## The ComponentsBuilder Pattern

`ComponentsBuilder` is the abstraction that makes sending messages clean. It translates high-level intent into Meta's exact API format:

```python
# What you write:
builder.set_header(header_type="image", header_data={"url": "banner.jpg"})
builder.set_body_params(["John", "20%"])

# What Meta's API receives:
{
    "components": [
        {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": "banner.jpg"}}]
        },
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "John"},
                {"type": "text", "text": "20%"}
            ]
        }
    ]
}
```

This builder handles ALL template types (text, image, document, video headers + body + buttons + carousel cards) through a single interface.

---

## Deduplication

Every job gets a unique hash:

```python
hash_input = f"{template_name}|{template_type}|{sorted(phones)}|{date}|{time}|{params}"
job_hash = hashlib.md5(hash_input.encode()).hexdigest()
```

Before creating a new job, we check:

```python
existing = SchedulerJob.objects.filter(
    job_hash=job_hash,
    status__in=['pending', 'processing']
).exists()

if existing:
    return Response({"error": "Duplicate job"}, status=409)
```

This prevents the same campaign from being submitted twice (e.g., user double-clicks the send button).

---

## Monitoring

### Job Statistics

Each job tracks live stats:

```json
{
    "total_recipients": 1000,
    "sent_count": 987,
    "failed_count": 13,
    "success_rate": 98.7,
    "processing_started_at": "2026-06-20T09:00:00Z",
    "processing_completed_at": "2026-06-20T09:02:34Z"
}
```

### Celery Beat Schedule

```python
CELERY_BEAT_SCHEDULE = {
    'check-scheduled-jobs': {
        'task': 'scheduler.tasks.check_and_process_due_jobs',
        'schedule': 3.0,  # Every 3 seconds
    },
}
```

**Why 3 seconds?** Balance between responsiveness and database load. A 1-second interval would cause too many queries; 10 seconds would make scheduling feel sluggish.

---

## Error Handling

| Error Type | Handling |
|-----------|----------|
| Network timeout | Retry with backoff |
| Meta API 429 (rate limit) | Back off, reduce send rate |
| Invalid phone number | Mark recipient as failed (no retry) |
| Invalid access token | Mark entire job as failed |
| Worker crash | Job stays in `processing` with stale `claimed_by`. Cleanup task detects and resets. |
| Database error | Transaction rollback, job stays in current state |

---

## Performance Numbers

With the current configuration:

| Metric | Value |
|--------|-------|
| Send rate | ~50 msg/sec per WhatsApp number |
| Job processing delay | 0-3 seconds (Beat interval) |
| 1,000 recipients | ~20 seconds |
| 10,000 recipients | ~3.5 minutes |
| Maximum queue depth | Unlimited (PostgreSQL-backed) |
| Concurrent workers | Configurable (default: 4) |
