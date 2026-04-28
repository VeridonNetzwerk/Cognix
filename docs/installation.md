# Installation

## Requirements

- Python 3.12+
- Redis 7 (required for IPC and rate-limiting)
- One database: PostgreSQL 14+, MySQL 8+, or SQLite (default for dev)
- (Optional) Lavalink 4 for music

## Local

```bash
git clone <repo> cognix && cd cognix
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell
pip install -e .
cp .env.example .env
# Generate MASTER_KEY (32 random bytes, base64):
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
# Generate JWT_SECRET:
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Edit .env with both values
python main.py
```

Open http://localhost:8080 → the first-run setup wizard guides you through bot token, admin account, and optional 2FA / Google OAuth.

## Docker

```bash
docker compose up -d --build
```

Compose ships PostgreSQL + Redis. Add `--profile music` to start Lavalink.

## Production checklist

- HTTPS (reverse proxy: Caddy / Nginx / Traefik) terminating TLS in front of port 8080
- Strong `MASTER_KEY` and `JWT_SECRET`, never committed
- Set `APP_ENV=production` and `APP_BASE_URL=https://your.domain` (CORS + cookie scope)
- Use PostgreSQL (not SQLite) for concurrency
- Run behind a process supervisor (systemd, Docker, Pterodactyl egg)
