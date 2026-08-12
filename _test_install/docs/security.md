# Security model

## Secrets at rest

All bot tokens, OAuth secrets, TOTP secrets, and backup payloads are encrypted with **AES-256-GCM** (`cryptography` library) using a key derived from `MASTER_KEY` (base64 of 32 random bytes). Each ciphertext type is bound by **AAD**:

| Data | AAD |
|---|---|
| Discord bot token | `b"bot_token"` |
| Google OAuth secret | `b"oauth"` |
| TOTP secret | `b"totp"` |
| Backup payload | `b"backup"` |

A leaked ciphertext from one column cannot be decrypted in another context.

## Passwords

- **bcrypt** (rounds=12) + **server-side pepper** (`AUTH_PEPPER` env)
- Length enforced 8..128
- Lockout: 10 failed attempts → 15-minute account lock
- Failed-login counter cleared on successful login

## 2FA

- TOTP via `pyotp` (RFC 6238, 30-second window)
- 8 backup codes generated at enable, **stored as SHA-256 hashes**, single-use

## Sessions

- Access JWT (HS256, 15 min) in cookie `cognix_access`
- Refresh JWT (30 days) in cookie `cognix_refresh`, stored hashed in DB with a `family_id`
- Cookies: **HttpOnly · Secure · SameSite=Lax**
- Refresh rotation: each refresh issues a new (token, family_id) pair and revokes the previous one
- **Reuse detection:** if a previously-rotated refresh token is presented again, the entire family is revoked (defends stolen-cookie replay)

## Rate limiting

- Sliding window in Redis (falls back to in-memory if Redis is unavailable)
- `/auth/login` 10 / min · `/setup/*` 30 / min · default 120 / min per IP+route

## Setup gate

`SetupGateMiddleware` returns **HTTP 423** for every `/api/*` route until `system_config.configured = true`, ensuring no authenticated route is reachable on a fresh install.

## Audit log

Append-only `audit_log` table records actor, action, IP, user-agent, and JSON details for: login, logout, setup, all moderation actions, settings changes, cog actions, and bot restarts.

## OWASP Top-10 mitigations

- A01 (Broken access control): `require_role()` dependency, role enum `ADMIN/MODERATOR/VIEWER`
- A02 (Crypto): AES-GCM with AAD, bcrypt, no MD5/SHA-1 in security paths
- A03 (Injection): SQLAlchemy ORM, Pydantic validation, no raw SQL with user input
- A05 (Misconfig): setup gate, `is_dev` toggles for docs, sensible defaults
- A07 (Auth): lockout, 2FA, rotation, reuse detection
- A08 (Data integrity): refresh-token family revocation, audit log
- A09 (Logging): structlog JSON with request_id correlation
