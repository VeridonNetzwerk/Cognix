# CogniX

A modular, production-ready Discord bot platform with a secure web dashboard.

- **Bot:** discord.py 2.7 + native voice (yt-dlp + FFmpeg) — moderation, tickets, music, stats, backups
- **API:** FastAPI + SQLAlchemy 2 (async) + WebSocket events
- **Dashboard:** Server-rendered Jinja2 + Tailwind + Alpine.js
- **Security:** AES-256-GCM at-rest secrets · bcrypt + pepper · TOTP 2FA + backup codes · refresh-token rotation with reuse detection · per-module RBAC · audit log
- **Deploy:** single `python main.py` entry · Docker · Pterodactyl-friendly

## Features

- Per-server cog enable/disable (silent rejection of disabled commands)
- Native music player: queue, playlists, loop, shuffle, volume, web control
- Encrypted backups with diff preview, purge restore, autocomplete
- Archived ticket viewer with cached message history (incl. deletions)
- Bot profile editor (avatar, banner, activity, status) live preview
- Theme + accent color + font size per web user
- Granular per-module permissions (none / read / write); admin account locked
- Complete Discord audit / activity log mirroring

## Setup

```bash
# 1. System dependencies
#    - Python 3.12+
#    - FFmpeg (required for music playback)

# 2. Local
cp .env.example .env       # edit MASTER_KEY (base64 32 bytes), JWT_SECRET, etc.
pip install -r requirements.txt
alembic upgrade head       # run database migrations
python main.py             # opens http://localhost:8080 — first-run setup wizard

# 3. Docker
docker compose up -d --build
```

See [docs/](docs/) for installation, first-run, commands, API, security, and Pterodactyl guides.
