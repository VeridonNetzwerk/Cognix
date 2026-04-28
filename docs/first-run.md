# First-run setup

When CogniX boots with no `system_config.configured` row set, every `/api/*` route returns **HTTP 423 Locked** except the setup endpoints. The dashboard automatically redirects to `/setup`.

## Wizard steps

1. **Discord bot token** – encrypted with AES-256-GCM (AAD `bot_token`) before being stored.
2. **Administrator account** – username, email, password (bcrypt + pepper).
3. **Security options (optional):**
   - Enable TOTP 2FA → returns a `otpauth://` URI, QR data-URL, and 8 single-use backup codes.
   - Google OAuth client (id + secret) – encrypted on save.
4. **Confirmation** – save backup codes; you are redirected to `/login`.

## API equivalents

```
GET  /api/v1/setup/status        → { configured: bool }
POST /api/v1/setup/initialize    → { otp_provisioning_uri?, otp_qr_data_url?, backup_codes? }
```

After step 4, `SetupGateMiddleware` releases the rest of the API.
