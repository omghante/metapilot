# Security Model

## Authentication & Authorization

### JWT Flow
```
POST /api/auth/login/
  → access_token (60 min TTL)
  → refresh_token (7 day TTL, HttpOnly cookie)

POST /api/auth/token/refresh/
  → new access_token
  → refresh_token rotated (old blacklisted)

POST /api/auth/logout/
  → refresh_token blacklisted immediately
```

### Role-Based Access Control

| Permission Class | Who |
|---|---|
| `IsSuperAdmin` | Platform operator only |
| `IsAgencyOwner` | Agency user for their own tenants |
| `IsTenantUser` | Tenant user for their own data |
| `IsAuthenticated` | Any logged-in user |

---

## Secrets Management

### WhatsApp API Token Encryption

All tenant WhatsApp API tokens are encrypted at rest using **Fernet** (AES-128-CBC + HMAC-SHA256):

```python
from cryptography.fernet import Fernet
f = Fernet(settings.FERNET_KEY)
encrypted = f.encrypt(raw_token.encode())  # stored in DB
decrypted = f.decrypt(encrypted).decode()  # used at runtime
```

The `FERNET_KEY` must be set as an environment variable. It is never stored in code or committed to version control.

---

## Webhook Security

Incoming Meta webhooks are verified using **HMAC-SHA256**:

```python
# webhooks/security.py
import hmac, hashlib

def verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    expected = hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

Requests with invalid signatures return `403 Forbidden` immediately.

---

## Transport Security

| Setting | Value |
|---|---|
| HSTS | 1 year + subdomains + preload (production) |
| HTTPS redirect | Via reverse proxy (Dokploy/nginx) |
| Session cookies | `Secure=True`, `HttpOnly=True` (production) |
| CSRF cookies | `Secure=True` (production) |
| Clickjacking | `X-Frame-Options: DENY` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |

---

## Rate Limiting

### Meta API Rate Limiting
Custom token-bucket rate limiter in `scheduler/services/rate_limiter.py` prevents exceeding Meta's per-number limits.

### API Rate Limiting (Planned)
Per-tenant DRF throttling to prevent abuse:
```python
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '1000/hour',
    }
}
```

---

## Security Checklist

- [x] JWT tokens with short expiry (60 min)
- [x] Refresh token rotation + blacklisting
- [x] Fernet encryption for API secrets at rest
- [x] HMAC-SHA256 webhook signature verification
- [x] HSTS headers in production
- [x] Tenant data isolation via middleware + permission classes
- [x] CORS restricted to known origins in production
- [x] Weekly automated dependency audits (GitHub Actions)
- [x] CodeQL static analysis
- [ ] API rate limiting per tenant (planned)
- [ ] Sentry error tracking (planned)
- [ ] Secrets rotation procedure (planned)
