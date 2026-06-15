# Multi-Tenancy Architecture

> How MetaPilot isolates data between agencies, clients, and users.

---

## What Is Multi-Tenancy?

Multi-tenancy means **one application serving multiple isolated customers**. In MetaPilot, each "tenant" is a business with its own WhatsApp number, contacts, campaigns, and analytics. Data from Tenant A must **never** leak to Tenant B.

MetaPilot uses **application-level multi-tenancy** — all tenants share the same database, but every query is filtered by `tenant_id`. This is simpler than separate databases per tenant and scales well for hundreds of tenants.

---

## Hierarchy

```
Platform (MetaPilot)
  │
  ├── Super Admin (platform owner — Om)
  │     └── Full access to everything
  │
  ├── Agency A (reseller)
  │     ├── Agency Admin (manages clients under this agency)
  │     ├── Client 1 (tenant)
  │     │     ├── Tenant Admin
  │     │     ├── Tenant User
  │     │     ├── Contacts, Campaigns, Messages...
  │     │     └── WhatsApp Number: +91-98765-43210
  │     │
  │     └── Client 2 (tenant)
  │           ├── Tenant Admin
  │           └── WhatsApp Number: +91-98765-43211
  │
  └── Agency B (another reseller)
        └── Client 3 (tenant)
              └── WhatsApp Number: +1-555-123-4567
```

### Roles Explained

| Role | Scope | Can See | Typical User |
|------|-------|---------|--------------|
| `SUPER_ADMIN` | Entire platform | All agencies, all clients, all data | Platform owner |
| `AGENCY_ADMIN` | One agency | Only clients under their agency | Reseller/partner |
| `TENANT_ADMIN` | One tenant | Only their tenant's data | Business owner |
| `TENANT_USER` | One tenant | Limited view of their tenant's data | Marketing team member |

---

## How Tenant Isolation Works

### Step 1: Authentication (JWT)

When a user logs in, the JWT token includes custom claims:

```python
# core/settings.py - SimpleJWT configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# Custom JWT serializer adds role and tenant_id to token
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['tenant_id'] = str(user.tenant_id) if user.tenant_id else None
        return token
```

**Decoded JWT payload:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "TENANT_ADMIN",
  "tenant_id": "660e8400-e29b-41d4-a716-446655440001",
  "exp": 1750000000
}
```

### Step 2: Tenant Middleware

Every request passes through `TenantMiddleware`, which attaches the tenant to `request.tenant`:

```python
class TenantMiddleware:
    def __call__(self, request):
        user = request.user
        
        if not user.is_authenticated:
            request.tenant = None
            return self.get_response(request)
        
        if user.role == 'SUPER_ADMIN':
            # Super admins can specify tenant via header
            tenant_id = request.headers.get('X-Tenant-ID')
            if tenant_id:
                request.tenant = Tenant.objects.get(id=tenant_id)
            else:
                request.tenant = None  # Platform-wide access
        else:
            # Everyone else is locked to their tenant
            request.tenant = user.tenant
        
        return self.get_response(request)
```

**Key behaviors:**
- `TENANT_ADMIN` / `TENANT_USER` → `request.tenant` is always their own tenant. They cannot override it.
- `SUPER_ADMIN` → Can pass `X-Tenant-ID` header to "act as" a specific tenant. Without the header, they see platform-wide data.
- `AGENCY_ADMIN` → `request.tenant` is None, but queries are filtered by `agency=user.agency`.

### Step 3: Query Filtering

Every ViewSet filters data by the resolved tenant:

```python
class ContactViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        # This is the key line — all data is tenant-scoped
        return Contact.objects.filter(tenant=self.request.tenant)
    
    def perform_create(self, serializer):
        # New objects are auto-assigned to the current tenant
        serializer.save(tenant=self.request.tenant)
```

This pattern is repeated across **every model**: Contacts, Campaigns, Messages, Templates, Inbox, Notifications, Analytics.

---

## Agency Isolation

Agency Admins have a different isolation model — they can see data across multiple tenants (their clients), but only within their agency:

```python
class AgencyClientViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        user = self.request.user
        if user.role != 'AGENCY_ADMIN':
            raise PermissionDenied()
        # Only clients belonging to this agency
        return Tenant.objects.filter(agency=user.agency)
```

**Agency Dashboard** aggregates stats across all their clients:
```python
# Total messages sent across all agency clients
total = Message.objects.filter(
    conversation__contact__tenant__agency=user.agency
).count()
```

---

## Super Admin "God Mode"

Super Admins bypass tenant filtering. They see everything:

```python
# Dashboard view for Super Admins
if user.role == 'SUPER_ADMIN':
    data = {
        'total_agencies': Agency.objects.count(),
        'total_clients': Tenant.objects.count(),
        'total_users': User.objects.count(),
        'total_campaigns': Campaign.objects.count(),
    }
```

When a Super Admin needs to act on behalf of a tenant (e.g., debugging a client's issue), they pass the `X-Tenant-ID` header:

```bash
curl -H "Authorization: Bearer <super_admin_token>" \
     -H "X-Tenant-ID: 660e8400-..." \
     http://localhost:8000/api/contacts/
# Returns contacts for that specific tenant
```

---

## Tenant Configuration (Encrypted Credentials)

Each tenant stores their WhatsApp API credentials encrypted:

```python
class TenantConfig(models.Model):
    tenant = models.ForeignKey(Tenant)
    provider = models.CharField()   # META_WHATSAPP
    key_name = models.CharField()   # access_token, phone_number_id, etc.
    encrypted_value = models.TextField()  # Fernet encrypted
    
    def set_value(self, raw_value):
        """Encrypt and store"""
        f = Fernet(settings.FERNET_KEY.encode())
        self.encrypted_value = f.encrypt(raw_value.encode()).decode()
    
    def get_value(self):
        """Decrypt and return"""
        f = Fernet(settings.FERNET_KEY.encode())
        return f.decrypt(self.encrypted_value.encode()).decode()
```

**Security properties:**
- Encrypted at rest (database dump is useless without `FERNET_KEY`)
- `FERNET_KEY` lives only in environment variables, never in code
- Decrypted only when making API calls (in-memory, brief)
- Never returned in API responses

---

## Tenant Feature Flags

Per-tenant feature toggles allow progressive rollouts:

```python
class FeatureFlag(models.Model):
    tenant = models.ForeignKey(Tenant)
    feature_name = models.CharField()  # e.g., "carousel_templates"
    enabled = models.BooleanField(default=False)
```

Usage in views:
```python
if not FeatureFlag.objects.filter(
    tenant=request.tenant,
    feature_name='carousel_templates',
    enabled=True
).exists():
    return Response({"error": "Carousel templates not enabled"}, status=403)
```

---

## Tenant Suspension

An agency admin or super admin can suspend a client:

```python
# Suspend endpoint
tenant.status = 'SUSPENDED'
tenant.save()
```

**What happens when a tenant is suspended:**
1. Login attempts return `403 Forbidden` ("Account suspended")
2. API calls by tenant users are blocked by middleware
3. Scheduled jobs are paused (won't execute)
4. Incoming webhooks are still processed (but no auto-replies)

---

## WebSocket Isolation

Real-time inbox uses tenant-scoped WebSocket groups:

```python
# Channel group name includes tenant_id
group_name = f"inbox_{tenant_id}"

# Only users of that tenant can connect
class InboxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope['user']
        tenant_id = self.scope['url_route']['kwargs']['tenant_id']
        
        # Verify user belongs to this tenant
        if str(user.tenant_id) != tenant_id:
            await self.close()
            return
        
        await self.channel_layer.group_add(group_name, self.channel_name)
        await self.accept()
```

Messages are broadcast only to the correct tenant group — Tenant A never receives Tenant B's messages.

---

## Data Deletion (GDPR)

When a tenant requests data deletion:

```python
class DataDeletionRequest(models.Model):
    tenant = models.ForeignKey(Tenant)
    requested_by = models.ForeignKey(User)
    status = models.CharField()  # PENDING → PROCESSING → COMPLETED
    scope = models.CharField()   # ALL, CONTACTS, MESSAGES, CONVERSATIONS
```

The deletion process:
1. Super Admin approves the request
2. Celery task runs in background
3. Deletes: Contacts → Conversations → Messages → Campaigns → Analytics
4. Preserves: Audit logs (for compliance) and the tenant record itself
5. Status updated to COMPLETED

---

## Common Pitfalls (and How We Avoid Them)

| Pitfall | Our Solution |
|---------|-------------|
| Forgetting `tenant=` filter | Every ViewSet has `get_queryset()` with tenant filter |
| Cross-tenant data in admin | Custom Admin classes filter by user's tenant |
| WebSocket leaks | Group name includes `tenant_id`, connection verified |
| Shared cache pollution | Cache keys include tenant_id prefix |
| Background tasks without tenant | Celery tasks receive `tenant_id` as explicit parameter |
