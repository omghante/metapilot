# Authentication & Security

> JWT authentication, role-based access control, encryption, and security measures.

---

## Authentication Flow

MetaPilot uses **JWT (JSON Web Tokens)** via `djangorestframework-simplejwt` with token rotation and blacklisting.

### Login Flow

```
User submits email + password
    │
    ▼
POST /api/auth/login/
    │
    ▼
┌──────────────────────────────────────────┐
│  1. Normalize email to lowercase          │
│  2. authenticate(email, password)         │
│     → PBKDF2 hash comparison              │
│  3. Check user.is_active                  │
│  4. Check user.tenant.status != SUSPENDED │
│  5. Generate token pair:                  │
│     • Access token  (60 min lifetime)     │
│     • Refresh token (7 day lifetime)      │
│  6. Add custom claims:                    │
│     • role: "TENANT_ADMIN"                │
│     • tenant_id: "uuid"                   │
│  7. Log to AuditLog                       │
└──────────────────────┬───────────────────┘
                       │
                       ▼
{
    "access": "eyJhbGci...",    ← Use this for API calls
    "refresh": "eyJhbGci...",   ← Use this to get new access tokens
    "user": { ... }
}
```

### Token Rotation Flow

```
Access token expires (after 60 min)
    │
    ▼
POST /api/auth/refresh/
{ "refresh": "old_refresh_token" }
    │
    ▼
┌──────────────────────────────────────────┐
│  1. Validate old refresh token            │
│  2. Blacklist old refresh token           │
│     (can never be used again)             │
│  3. Generate new access token             │
│  4. Generate new refresh token            │
└──────────────────────┬───────────────────┘
                       │
                       ▼
{
    "access": "new_access_token",
    "refresh": "new_refresh_token"
}
```

**Why rotate refresh tokens?** If a refresh token is stolen, the attacker can only use it once. The real user's next refresh attempt will fail (because the token is blacklisted), alerting them to the compromise.

### Logout

```
POST /api/auth/logout/
{ "refresh": "current_refresh_token" }
    │
    ▼
Refresh token is blacklisted → user must re-login
```

---

## JWT Token Structure

```
Header:
{
    "alg": "HS256",
    "typ": "JWT"
}

Payload:
{
    "token_type": "access",
    "exp": 1750000000,          // Expiration timestamp
    "iat": 1749996400,          // Issued at
    "jti": "unique-token-id",   // For blacklisting
    "user_id": "uuid",
    "role": "TENANT_ADMIN",     // Custom claim
    "tenant_id": "uuid"         // Custom claim
}

Signature:
HMAC-SHA256(header + payload, SECRET_KEY)
```

**Custom claims** (`role` and `tenant_id`) are added by the custom serializer. This means any service can determine the user's permissions just from the token — no database lookup needed for basic authorization.

---

## Role-Based Access Control (RBAC)

### Role Definitions

| Role | Scope | Example Permissions |
|------|-------|-------------------|
| `SUPER_ADMIN` | Entire platform | Create agencies, manage all tenants, view audit logs, GDPR operations |
| `AGENCY_ADMIN` | One agency + its clients | View/manage clients, suspend/activate clients, agency dashboard |
| `TENANT_ADMIN` | One tenant | Manage contacts, campaigns, templates, inbox, view analytics |
| `TENANT_USER` | One tenant (limited) | View contacts, send messages, use inbox |

### Permission Enforcement

Permissions are enforced at the **view level** using DRF permission classes:

```python
from rest_framework.permissions import BasePermission

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == 'SUPER_ADMIN'

class IsAgencyAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ('SUPER_ADMIN', 'AGENCY_ADMIN')

class IsTenantMember(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ('TENANT_ADMIN', 'TENANT_USER')

class IsTenantAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ('SUPER_ADMIN', 'TENANT_ADMIN')
```

Usage in views:
```python
class AgencyViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    # Only super admins can manage agencies

class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsTenantMember]
    # Only tenant members can manage campaigns
```

### Middleware Chain

Every request passes through this chain:

```
Request arrives
    │
    ▼
1. SecurityMiddleware (HTTPS redirect, HSTS)
    │
    ▼
2. CorsMiddleware (CORS headers for frontend)
    │
    ▼
3. AuthenticationMiddleware (Django session)
    │
    ▼
4. JWTAuthentication (parse Bearer token)
    │
    ▼
5. TenantMiddleware (resolve tenant from user)
    │
    ▼
6. View (permission classes + business logic)
```

---

## Encryption

### Fernet Encryption (AES-256-CBC)

Sensitive data (API keys, access tokens) is encrypted at rest using Fernet symmetric encryption:

```python
from cryptography.fernet import Fernet

# Generate a key (do this once, store in .env)
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Encryption
f = Fernet(settings.FERNET_KEY.encode())
encrypted = f.encrypt(b"EAAGm0PX4ZBsIBAJsZBGqH...")
# Result: gAAAAABh... (base64 encoded)

# Decryption
decrypted = f.decrypt(encrypted)
# Result: b"EAAGm0PX4ZBsIBAJsZBGqH..."
```

**What's encrypted:**
| Data | Why |
|------|-----|
| Meta access tokens | Full API access to WhatsApp account |
| Phone number IDs | Can be used to send messages |
| Business account IDs | Account identification |
| App secrets | Webhook signature verification |
| Webhook verify tokens | Webhook setup authentication |

**What's NOT encrypted:**
- User passwords (hashed with PBKDF2, not encrypted)
- Message content (performance trade-off)
- Contact phone numbers (needed for query filtering)

### Password Security

Passwords are hashed (one-way), not encrypted (reversible):

```python
# Django's default: PBKDF2 with SHA256
# 720,000 iterations (as of Django 5)
# Random salt per password

# Stored format:
# pbkdf2_sha256$720000$randomsalt$hashedpassword
```

---

## Webhook Security

### HMAC-SHA256 Verification

Every incoming webhook from Meta includes a signature header:

```
X-Hub-Signature-256: sha256=abc123def456...
```

Verification:
```python
import hmac
import hashlib

def verify_webhook_signature(request_body, signature_header, app_secret):
    expected = hmac.new(
        app_secret.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    received = signature_header.replace('sha256=', '')
    
    # Constant-time comparison (prevents timing attacks)
    return hmac.compare_digest(expected, received)
```

---

## Audit Logging

Every security-relevant action is logged:

```python
AuditLog.objects.create(
    action='auth.login_success',
    performed_by=user,
    tenant=user.tenant,
    ip_address=get_client_ip(request),
    user_agent=request.META.get('HTTP_USER_AGENT', ''),
    metadata={
        'email': user.email,
        'role': user.role,
        'method': 'jwt'
    }
)
```

**Logged actions:**
| Action | When |
|--------|------|
| `auth.login_success` | Successful login |
| `auth.login_failed` | Failed login attempt |
| `auth.logout` | User logged out |
| `auth.register` | New user created |
| `tenant.created` | New tenant provisioned |
| `tenant.suspended` | Tenant access revoked |
| `campaign.created` | New campaign started |
| `campaign.completed` | Campaign finished |
| `config.updated` | API credentials changed |
| `data.deletion_requested` | GDPR deletion request |

---

## CORS Configuration

```python
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",     # Next.js dev server
    "https://app.metapilot.io",  # Production dashboard
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    'authorization',
    'content-type',
    'x-tenant-id',  # For super admin tenant switching
]
```

---

## Security Headers

```python
# Django security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_SECURE = True       # In production
SESSION_COOKIE_SECURE = True    # In production
SECURE_SSL_REDIRECT = True      # In production
SECURE_HSTS_SECONDS = 31536000  # 1 year HSTS
```

---

## GDPR Compliance

### Data Deletion

Users/tenants can request complete data deletion:

```python
class DataDeletionRequest(models.Model):
    tenant = models.ForeignKey(Tenant)
    requested_by = models.ForeignKey(User)
    status = models.CharField()  # PENDING → PROCESSING → COMPLETED
    scope = models.CharField()   # ALL, CONTACTS, MESSAGES
    reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True)
```

**Deletion cascade:**
1. Contacts and their metadata
2. Conversations and messages
3. Campaign data and results
4. Media assets
5. Analytics records
6. ✗ Audit logs are **preserved** (legal requirement)
7. ✗ Tenant record is **preserved** (billing records)

### Data Export

Before deletion, data can be exported:
```
GET /api/data-export/?format=json
```

Returns all tenant data in a downloadable JSON file.

---

## Common Security Pitfalls (and How We Handle Them)

| Pitfall | Our Mitigation |
|---------|---------------|
| JWT stored in localStorage | Recommended: httpOnly cookies. But localStorage works with short access token lifetime (60 min) |
| Token theft via XSS | CSP headers, input sanitization, httpOnly cookie option |
| Brute force login | Rate limiting on `/api/auth/login/` (configurable per tenant) |
| Insecure direct object references | All queries filtered by `tenant=request.tenant` |
| SQL injection | Django ORM parameterized queries (never raw SQL) |
| Mass assignment | DRF serializer `fields` whitelist (no `__all__`) |
| Timing attacks on auth | `hmac.compare_digest()` for constant-time comparison |
