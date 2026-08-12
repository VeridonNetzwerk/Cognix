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

# 2. Install (automated — creates venv, installs deps, generates secrets, runs migrations)
python install.py

# 3. Start the bot
.venv/Scripts/python main.py    # Windows
.venv/bin/python main.py        # Linux/macOS

# 4. Open http://localhost:8080 — first-run setup wizard will guide you
```

### Manual setup (alternative)

```bash
cp .env.example .env       # edit MASTER_KEY, JWT_SECRET, AUTH_PEPPER, DISCORD_BOT_TOKEN
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows
.venv/bin/pip install -r requirements.txt         # Linux/macOS
alembic upgrade head       # run database migrations
python main.py             # opens http://localhost:8080
```

### Docker

```bash
docker compose up -d --build
```

See [docs/](docs/) for installation, first-run, commands, API, security, and Pterodactyl guides.

## Project Structure

```
CogniX/
├── install.py              # Installer — creates venv, installs deps, generates secrets
├── main.py                 # Entry point — starts bot + web server
├── bot/                    # Discord bot core
│   ├── client.py           #   Bot client (CognixBot)
│   ├── runtime.py          #   Runtime helpers (get_bot, get_bot_info)
│   ├── cogs/               #   Feature modules (lazy-loaded)
│   │   ├── registry.py     #     Cog discovery, load/unload, BUILTIN_COGS
│   │   ├── admin.py        #     /admin cog management commands
│   │   ├── marketplace.py  #     /marketplace install/uninstall commands
│   │   ├── moderation.py   #     Ban, kick, mute, warn, purge
│   │   ├── tickets.py      #     Thread-based support tickets
│   │   ├── music.py        #     Music playback (yt-dlp + FFmpeg)
│   │   ├── backups.py      #     Server backup/restore
│   │   ├── giveaways.py    #     Reaction-based giveaways
│   │   ├── welcome.py      #     Join/leave/boost messages
│   │   ├── invite_tracker.py  #  Invite tracking
│   │   ├── activity_log.py #     Discord event logging
│   │   ├── embeds.py       #     Custom embed templates
│   │   ├── bot_profile.py  #     Bot profile management
│   │   ├── stats.py        #     Message/command statistics
│   │   └── utility.py      #     Ping, info, userinfo, etc.
│   ├── ipc.py              #   Redis IPC consumer (optional, multi-process)
│   ├── services/           #   Audio player service
│   └── utils/              #   Embed helpers, time parser
├── web/                    # Web dashboard + JSON API
│   ├── app.py              #   FastAPI app factory
│   ├── deps.py             #   Shared dependencies (auth, DB session)
│   ├── api/                #   JSON API routes (/api/v1/*)
│   │   ├── auth.py         #     Login/logout/setup API
│   │   ├── marketplace.py  #     Marketplace API (install/uninstall)
│   │   ├── cogs.py         #     Cog management API
│   │   ├── servers.py      #     Server info API
│   │   ├── tickets.py      #     Ticket API
│   │   ├── backups.py      #     Backup API
│   │   ├── moderation.py   #     Moderation API
│   │   ├── music_panel.py  #     Music API
│   │   ├── stats.py        #     Statistics API
│   │   ├── audit.py        #     Audit log API
│   │   ├── bot_control.py  #     Bot lifecycle API
│   │   ├── embed_templates.py  # Embed template API
│   │   ├── settings.py     #     System settings API
│   │   ├── setup.py        #     First-run setup API
│   │   ├── users.py        #     Discord user API
│   │   ├── web_users.py    #     Web user management API
│   │   └── ws.py           #     WebSocket endpoint
│   ├── pages/              #   HTML pages (Jinja2 dashboard, primary UI)
│   │   ├── _shared.py      #     Shared helpers, router, templates
│   │   ├── auth.py         #     Login/logout/setup wizard pages
│   │   ├── dashboard.py    #     Dashboard, servers, server detail
│   │   ├── cogs.py         #     Cogs management, marketplace page
│   │   ├── tickets.py      #     Tickets, types, panels pages
│   │   ├── audit.py        #     Audit log, Discord log pages
│   │   ├── users.py        #     Web user management pages
│   │   ├── backups.py      #     Backups, server permissions pages
│   │   ├── settings.py     #     Settings, 2FA, bot profile pages
│   │   ├── music.py        #     Music page + API
│   │   ├── giveaways.py    #     Giveaways management pages
│   │   └── features.py     #     Members, embeds, invites, misc API
│   ├── templates/          #   Jinja2 HTML templates
│   ├── middleware/         #   Auth refresh, rate limit, setup gate
│   ├── schemas/            #   Pydantic request/response schemas
│   ├── security/           #   Passwords, tokens, TOTP, OAuth
│   └── services/           #   Auth service, bot IPC client
├── database/               # Database layer
│   ├── models/             #   SQLAlchemy models (20+ tables)
│   ├── migrations/         #   Alembic migrations
│   ├── session.py          #   Async session factory
│   └── seed_embeds.py      #   Default embed template seeder
├── config/                 # Configuration
│   ├── settings.py         #   Env-based settings
│   ├── constants.py        #   API prefix, audit actions
│   ├── crypto.py           #   AES-256-GCM encryption
│   └── logging.py          #   Structured logging
├── scripts/                # CLI utility scripts
│   ├── create_admin.py     #   Create admin account
│   └── healthcheck.py      #   Health check
├── tests/                  # Test suite
│   ├── unit/               #   Unit tests (bot/, web/, database/, config/)
│   └── conftest.py         #   Shared test fixtures
├── docs/                   # Documentation
├── docker-compose.yml      # Docker deployment
├── Dockerfile              # Container image
├── requirements.txt        # Python dependencies
└── pyproject.toml          # Project config (ruff, pytest)
```
