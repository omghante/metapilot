# AI Chatbot System

> How MetaPilot uses AI to power platform assistance and WhatsApp auto-replies.

---

## Two Chatbot Systems

MetaPilot has **two separate chatbot systems** serving different purposes:

| System | Location | Purpose | Who Uses It |
|--------|----------|---------|-------------|
| **Platform Chatbot** | `chatbot/service.py` | Help users navigate MetaPilot's features | Dashboard users (internal) |
| **WA Chatbot** | `wa_chatbot/service.py` | Auto-reply to customer WhatsApp messages | End customers (external) |

---

## 1. Platform Chatbot (RAG-Based)

### What It Does

When a dashboard user asks "How do I create a campaign?", the chatbot searches through MetaPilot's documentation and returns a relevant, context-aware answer.

### Architecture: RAG (Retrieval-Augmented Generation)

```
User asks: "How do I schedule a campaign?"
    │
    ▼
┌──────────────────────────────────────────┐
│  Step 1: Keyword Extraction               │
│  Extract key terms: "schedule", "campaign" │
└────────────────────┬─────────────────────┘
                     │
┌────────────────────▼─────────────────────┐
│  Step 2: Local Search (content.json)      │
│  Search through 50+ Q&A pairs             │
│  Score each by keyword overlap             │
│  Return top 3 matches                      │
└────────────────────┬─────────────────────┘
                     │
                     ├── Found good matches? ──► Return local answer
                     │
                     └── No good matches? ──┐
                                            │
┌───────────────────────────────────────────▼──┐
│  Step 3: AI Fallback (OpenRouter)             │
│  Send question + platform context to LLM      │
│  Model: meta-llama/llama-4-scout OR           │
│         google/gemini-2.5-flash               │
│  Get AI-generated answer                       │
└──────────────────────────────────────────────┘
```

### Local Knowledge Base (`content.json`)

The chatbot first searches a local JSON file with curated Q&A pairs:

```json
{
  "platform_help": [
    {
      "question": "How do I create a campaign?",
      "keywords": ["create", "campaign", "new", "start"],
      "answer": "To create a campaign:\n1. Go to Campaigns page\n2. Click 'New Campaign'\n3. Select a template\n4. Choose your target audience by tags\n5. Set the schedule\n6. Click 'Send' or 'Schedule'"
    },
    {
      "question": "How do I import contacts?",
      "keywords": ["import", "contacts", "csv", "upload", "bulk"],
      "answer": "Go to Contacts → Import. Upload a CSV file with columns: phone, name, email. You can also add tags during import."
    }
  ]
}
```

### Scoring Algorithm

```python
def search_local_content(query):
    query_words = set(query.lower().split())
    results = []
    
    for item in content['platform_help']:
        # Count how many keywords match
        keyword_matches = len(query_words & set(item['keywords']))
        
        # Also check for phrase overlap in the question
        question_words = set(item['question'].lower().split())
        question_overlap = len(query_words & question_words)
        
        score = keyword_matches * 2 + question_overlap
        
        if score > 0:
            results.append((score, item))
    
    # Sort by score, return top 3
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:3]
```

**Why local-first?** Speed and cost. Local search returns in <1ms with zero API calls. AI fallback takes 1-3 seconds and costs money. 80% of questions are answered locally.

### AI Fallback (OpenRouter)

When local search doesn't find a good match:

```python
def get_ai_response(question, context_snippets):
    system_prompt = """You are MetaPilot Assistant, a helpful AI that assists users 
    with the MetaPilot WhatsApp marketing platform. Answer questions about:
    - Campaign management
    - Contact management  
    - Template creation
    - WhatsApp API integration
    - Analytics and reporting
    
    Keep answers concise and actionable. If you don't know, say so."""
    
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "meta-llama/llama-4-scout",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context: {context_snippets}\n\nQuestion: {question}"}
            ],
            "max_tokens": 500,
            "temperature": 0.3  # Low temperature for factual answers
        }
    )
    
    return response.json()['choices'][0]['message']['content']
```

### API Endpoint

```
POST /api/chatbot/ask/

Request:
{
    "question": "How do I schedule a campaign for next Monday?"
}

Response:
{
    "answer": "To schedule a campaign:\n1. Go to Campaigns...",
    "source": "local",  // or "ai"
    "confidence": 0.85
}
```

---

## 2. WhatsApp Auto-Reply Chatbot

### What It Does

When a customer sends a WhatsApp message to a business, the chatbot automatically generates and sends a reply. This works for:

- **Text messages** → AI text response
- **Image messages** → Vision AI analysis + response
- **Document messages** → Acknowledgment response

### Architecture

```
Customer sends WhatsApp message
    │
    ▼
Webhook receives message
    │
    ▼
WA_CHATBOT_ENABLED = True?
    │
    ├── No → Skip (message stored but no auto-reply)
    │
    └── Yes ─┐
             │
┌────────────▼──────────────────────────────────┐
│  WAChatbotService.generate_reply()             │
│                                                │
│  1. Load conversation history (last 10 msgs)   │
│  2. Build system prompt with business context   │
│  3. Select AI model based on message type:      │
│     • Text → meta-llama/llama-4-scout          │
│     • Image → openai/gpt-4o (vision)           │
│  4. Call OpenRouter API                          │
│  5. Return generated reply                       │
└────────────────────┬─────────────────────────┘
                     │
┌────────────────────▼──────────────────────────┐
│  Send reply via WhatsApp API                    │
│  WhatsAppService.send_text(to, reply)           │
└───────────────────────────────────────────────┘
```

### Conversation Context

The chatbot maintains context by loading recent message history:

```python
def build_messages(self, tenant, customer_phone, new_message):
    # Load last 10 messages from this conversation
    recent_messages = InboxMessage.objects.filter(
        conversation__tenant=tenant,
        conversation__customer_phone=customer_phone
    ).order_by('-created_at')[:10]
    
    messages = [
        {
            "role": "system",
            "content": self.get_system_prompt(tenant)
        }
    ]
    
    # Add conversation history
    for msg in reversed(recent_messages):
        role = "assistant" if msg.direction == 'OUTBOUND' else "user"
        messages.append({
            "role": role,
            "content": msg.content_json.get('text', '')
        })
    
    # Add the new message
    messages.append({
        "role": "user",
        "content": new_message
    })
    
    return messages
```

### System Prompt (Per-Tenant Customization)

Each tenant can have a customized chatbot personality:

```python
def get_system_prompt(self, tenant):
    return f"""You are a customer service assistant for {tenant.name}.
    Business type: {tenant.business_type}
    
    Guidelines:
    - Be friendly and professional
    - Answer questions about products and services
    - If you can't help, suggest contacting support
    - Never share customer data
    - Keep responses under 200 words
    - Use the customer's language (auto-detect)
    """
```

### Vision AI (Image Messages)

When a customer sends an image, the chatbot uses GPT-4o's vision capabilities:

```python
def process_image_message(self, image_url, caption=""):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json={
            "model": "openai/gpt-4o",  # Vision-capable model
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"A customer sent this image. {caption}. Describe what you see and respond helpfully."
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        }
                    ]
                }
            ],
            "max_tokens": 300
        }
    )
    return response.json()['choices'][0]['message']['content']
```

**Use cases:**
- Customer sends photo of damaged product → "I can see the damage. Let me connect you with our returns team."
- Customer sends screenshot of order → "I can see your order #12345. Let me check the status."

### Per-Tenant Webhook

Each tenant gets a unique webhook URL for the chatbot:

```
POST /api/wa-chatbot/webhook/{tenant_id}/
```

This allows per-tenant chatbot configuration without sharing Meta webhook endpoints.

---

## AI Model Selection

| Use Case | Model | Why |
|----------|-------|-----|
| Platform help (text) | meta-llama/llama-4-scout | Fast, cost-effective for simple Q&A |
| WA text replies | meta-llama/llama-4-scout | Good conversation ability, low latency |
| Image analysis | openai/gpt-4o | Best vision capabilities available |
| Fallback | google/gemini-2.5-flash | If primary model is down |

### OpenRouter Benefits

Instead of direct API calls to OpenAI/Google/Meta, MetaPilot uses **OpenRouter** as a unified gateway:

1. **Single API key** for all models
2. **Automatic fallback** if one provider is down
3. **Cost tracking** across all models
4. **Rate limit management** handled by OpenRouter

---

## Configuration

```env
# Required for AI features
OPENROUTER_API_KEY=sk-or-v1-xxx

# Feature flags
WA_CHATBOT_ENABLED=True      # Enable WhatsApp auto-replies
CHATBOT_MAX_TOKENS=500        # Max response length
CHATBOT_TEMPERATURE=0.3       # Creativity (0=factual, 1=creative)
```

---

## Cost Management

Each AI call costs money. MetaPilot manages costs by:

1. **Local-first search** — 80% of platform chatbot queries answered locally (free)
2. **Token limits** — `max_tokens=500` caps response length
3. **Low temperature** — Less creative = fewer tokens generated
4. **Conversation truncation** — Only last 10 messages sent as context
5. **Per-tenant toggles** — AI features can be disabled for free-tier tenants

**Estimated costs (via OpenRouter):**
| Model | Cost per 1K tokens |
|-------|-------------------|
| Llama 4 Scout | ~$0.0002 |
| GPT-4o | ~$0.005 |
| Gemini 2.5 Flash | ~$0.0001 |

Average customer conversation (10 messages) costs approximately $0.001-0.01.
