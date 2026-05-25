# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| latest (main) | ✅ |
| older releases | ❌ |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing:  
📧 **mr.omghante1@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within **48 hours**. If the issue is confirmed, a patch will be released as soon as possible.

## Security Controls

| Control | Implementation |
|---|---|
| Authentication | JWT (60min access / 7d refresh + blacklisting) |
| API secret encryption | Fernet AES-128 at rest |
| Webhook verification | HMAC-SHA256 signature check |
| Transport | HTTPS enforced via Nginx + HSTS |
| Tenant isolation | Middleware + per-view permission classes |
| Dependency audits | Weekly automated (pip-audit + CodeQL) |

See [docs/security/README.md](./docs/security/README.md) for full details.
