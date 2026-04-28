# Pterodactyl deployment

CogniX is a single-process app (FastAPI + Discord bot) that listens on one HTTP port. It runs cleanly inside a Pterodactyl Python egg.

## Egg / startup

- **Image:** `ghcr.io/pterodactyl/yolks:python_3.12`
- **Startup:** `python main.py`
- **Stop:** `^C` (the orchestrator handles `SIGINT`/`SIGTERM`)

## Environment variables

| Var | Required | Description |
|---|---|---|
| `MASTER_KEY` | yes | base64 of 32 random bytes |
| `JWT_SECRET` | yes | random ≥ 64 chars |
| `AUTH_PEPPER` | yes | random secret |
| `DATABASE_URL` | yes | e.g. `postgresql+asyncpg://...` or `sqlite+aiosqlite:///data/cognix.db` |
| `REDIS_URL` | yes | e.g. `redis://redis:6379/0` |
| `APP_BASE_URL` | yes | external URL (cookie/CORS) |
| `API_HOST` | no | `0.0.0.0` |
| `API_PORT` | no | `8080` |

## Allocations & ports

- **Primary:** TCP `8080` (HTTP). Only this port needs to be public.
- **Redis / Postgres:** internal services (separate eggs or sidecar).

## Persistent storage

Data files live under `/home/container/data/` (the working directory). Mount this if persistence between rebuilds is required. The default SQLite DB lives there.

## Healthcheck

`curl -fsS http://127.0.0.1:8080/health` returns `{"status":"ok"}`.
