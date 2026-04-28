# Database schema

All tables use the naming convention `pk_*`, `fk_*`, `ix_*`, `uq_*`, `ck_*`. Migrations live in `database/migrations/`.

## Core

- **system_config** (singleton, `id=1`): bootstrap config — encrypted bot token, encrypted Google OAuth credentials, status text/type, feature toggles, `configured` boolean.
- **discord_user**: cache of Discord users (BigInt PK = snowflake).
- **server**: each guild the bot has joined. Soft-deletable.
- **server_config** (1-1 with `server`): prefix, locale, mod log channel, mute role, ticket category / support roles / auto-close hours, music DJ role, free-form `extras` JSON.

## Moderation

- **moderation_action**: append-only ledger (`BAN/UNBAN/KICK/MUTE/UNMUTE/WARN/PURGE`) with optional `expires_at`, `affected_count`, `web_user_id` link.
- **warning**: lighter-weight per-user warnings (the model class is `Warning_` to avoid shadowing the Python builtin).

## Tickets

- **ticket** (UUID PK): `OPEN/CLOSED/ARCHIVED`, unique `thread_id`, opener / closed_by / last_activity_at.
- **ticket_message**: archived message history per ticket.

## Stats

- **stat_event**: raw events (`MESSAGE/COMMAND/JOIN/LEAVE`) indexed by `(server_id, event_type, occurred_at)`.
- **aggregated_stat**: daily rollups, unique on `(day, server_id, event_type, name)`.

## Backups

- **backup**: encrypted `payload` (Text) + non-encrypted `summary` (JSON) describing the snapshot.

## Cogs / permissions

- **cog_state**: per-server cog enable/disable. `server_id` nullable = global default.
- **role_permission**: Discord role → command allow/deny per server.

## Web auth

- **web_user** (UUID PK): role `ADMIN/MODERATOR/VIEWER`, optional encrypted `totp_secret`, optional `google_subject`, lockout fields.
- **refresh_token**: hashed token + `family_id` for rotation; reuse triggers full-family revocation.
- **backup_code**: SHA-256 of single-use 2FA recovery codes.
- **audit_log**: append-only — actor, action, IP, UA, JSON details.
