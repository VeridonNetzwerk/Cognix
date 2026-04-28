# API reference

All routes are prefixed with `/api/v1`. Authentication uses an HttpOnly cookie `cognix_access` (or `Authorization: Bearer ...`).

## Setup

| Method | Path | Auth | Body |
|---|---|---|---|
| GET | `/setup/status` | – | – |
| POST | `/setup/initialize` | – | `{ bot_token, admin_username, admin_email, admin_password, enable_2fa?, google_client_id?, google_client_secret? }` |

Until setup completes, every other `/api/*` route returns **423 Locked**.

## Auth

| Method | Path | Body |
|---|---|---|
| POST | `/auth/login` | `{ username, password, otp? }` |
| POST | `/auth/refresh` | – (uses cookie) |
| POST | `/auth/logout` | – |
| GET | `/auth/me` | – |

## Bot control (admin)

| Method | Path | Body |
|---|---|---|
| GET | `/bot/status` | – |
| POST | `/bot/restart` | – |
| POST | `/bot/presence` | `{ text, type }` |

## Cogs (admin)

| Method | Path | Body |
|---|---|---|
| GET | `/cogs` | – |
| POST | `/cogs/{name}` | `{ action: "load" \| "unload" \| "reload" }` |

## Servers / Users / Moderation / Tickets / Stats / Backups / Settings

See the OpenAPI spec at `/api/openapi.json` (dev only) or browse `/api/docs`.

## WebSocket

`GET /ws` (cookie or `?token=…`) – streams JSON `{ event, payload }` from the bot.

Events: `bot.ready`, `bot.guild_join`, `moderation.action`, `ticket.opened`, `ticket.closed`, `stats.event`, `settings.changed`.
