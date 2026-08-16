<div align="center">

<img src="bot/static/text.png" height="128" alt="CogniX Logo">

**Modular Discord bot platform with a secure web dashboard — moderation, music, tickets, backups, and more.**

<p>
  <a href="https://github.com/VeridonNetzwerk/CogniX/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/VeridonNetzwerk/CogniX?style=flat-square" alt="License">
  </a>
  <a href="https://github.com/VeridonNetzwerk/CogniX/issues">
    <img src="https://img.shields.io/github/issues/VeridonNetzwerk/CogniX?style=flat-square" alt="Open Issues">
  </a>
  <a href="https://github.com/VeridonNetzwerk/CogniX/stargazers">
    <img src="https://img.shields.io/github/stars/VeridonNetzwerk/CogniX?style=flat-square" alt="Stars">
  </a>
  <img src="https://img.shields.io/badge/Python-3.12+-yellow" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/discord.py-2.7-blue" alt="discord.py 2.7">
  <img src="https://img.shields.io/badge/FastAPI-latest-teal" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0-red" alt="SQLAlchemy 2.0">
  <img src="https://img.shields.io/badge/TailwindCSS-3-cyan" alt="Tailwind CSS 3">
  <img src="https://img.shields.io/badge/Alpine.js-3-blue" alt="Alpine.js 3">
</p>

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🧩 **Modular Cogs** | Install/uninstall feature modules from the web panel — cogs ship with their own templates and page routes |
| 🎵 **Native Music** | Queue, playlists, loop, shuffle, volume, web-controlled playback via yt-dlp + FFmpeg |
| 🎫 **Ticket System** | Thread-based support tickets with panels, types, and archived viewer with cached message history |
| 🔐 **Encrypted Backups** | AES-256-GCM encrypted server backups with diff preview, purge restore, and autocomplete |
| 🛡️ **Moderation** | Ban, kick, mute, warn, purge with per-server enable/disable and silent rejection of disabled commands |
| 🎉 **Giveaways** | Reaction-based giveaways with automatic winner selection |
| 👋 **Welcome & Invites** | Join/leave/boost messages, invite tracking with leaderboard |
| 📊 **Stats & Logging** | Complete Discord audit/activity log mirroring with aggregated statistics |
| 🖥️ **Web Dashboard** | Server-rendered Jinja2 + Tailwind + Alpine.js — customizable 4×3 widget grid with drag & resize |
| 🔒 **Security** | AES-256-GCM at-rest secrets · bcrypt + pepper · TOTP 2FA + backup codes · refresh-token rotation with reuse detection · per-module RBAC · audit log |
| 🎨 **Per-User Themes** | Theme + accent color + font size per web user |
| 🤖 **Bot Profile Editor** | Avatar, banner, activity, status with live preview |

---

## 🛠️ Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| OS | Any (Windows/Linux/macOS) | Docker recommended for production |
| Python | 3.12+ | Required for running from source |
| FFmpeg | any recent | Required for music playback (yt-dlp) |
| Redis | optional | For multi-process IPC (bot + API on separate machines) |
| Database | SQLite (default) / MySQL | SQLite needs no setup; MySQL for larger deployments |

> **Note**: CogniX ships with zero cogs installed. Install only what you need from the built-in cog store via the web panel.

---

## 🚀 Quick Start

### Option A: Installer (Recommended)

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

The setup wizard guides you through:
- Discord bot token configuration
- Admin account creation
- Database initialization
- Cog installation from the built-in store

### Option B: Manual Setup

```bash
cp .env.example .env       # edit MASTER_KEY, JWT_SECRET, AUTH_PEPPER, DISCORD_BOT_TOKEN
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows
.venv/bin/pip install -r requirements.txt         # Linux/macOS
alembic upgrade head       # run database migrations
python main.py             # opens http://localhost:8080
```

### Option C: Docker

```bash
docker compose up -d --build
```

---

## 🏗️ Architecture

```
CogniX/
├── install.py              # Installer — creates venv, installs deps, generates secrets
├── main.py                 # Entry point — starts bot + web server
├── alembic.ini             # Alembic config (migrations)
├── cogs/                   # Installed cog modules (lazy-loaded at runtime)
├── cogs_store/             # Available cogs (install via web panel)
│   ├── admin/              #   Cog management commands
│   ├── moderation/         #   Ban, kick, mute, warn, purge
│   ├── tickets/            #   Thread-based support tickets
│   ├── music/              #   Music playback (yt-dlp + FFmpeg)
│   ├── backups/            #   Server backup/restore
│   ├── giveaways/          #   Reaction-based giveaways
│   ├── welcome/            #   Join/leave/boost messages, invite tracking
│   ├── logging/            #   Discord event logging, stats
│   └── utility/            #   Ping, info, embeds, bot profile
├── bot/                    # Discord bot core + all backend logic
│   ├── client.py           #   Bot client (CognixBot)
│   ├── runtime.py          #   Runtime helpers (get_bot, get_bot_info)
│   ├── ipc.py              #   Redis IPC consumer (optional, multi-process)
│   ├── cogs/registry.py    #   Cog discovery, load/unload, persistence
│   ├── config/             #   Settings, constants, AES-256-GCM crypto, logging
│   ├── database/           #   SQLAlchemy models (20+ tables), Alembic migrations
│   ├── dashboard/          #   Core dashboard widget definitions
│   ├── pages/              #   Core HTML page routes (Jinja2)
│   ├── scripts/            #   CLI utilities (create_admin, healthcheck)
│   ├── services/           #   Audio player service
│   ├── static/             #   Branding assets (logo, text)
│   ├── templates/          #   Core Jinja2 templates (base, auth, dashboard, settings)
│   ├── tests/              #   Test suite (unit + integration)
│   └── utils/              #   Embed helpers, time parser
├── web/                    # Web dashboard + JSON API
│   ├── app.py              #   FastAPI app factory
│   ├── deps.py             #   Shared dependencies (auth, DB session)
│   ├── api/                #   JSON API routes (/api/v1/*)
│   ├── middleware/         #   Auth refresh, rate limit, setup gate
│   ├── schemas/            #   Pydantic request/response schemas
│   ├── security/           #   Passwords, tokens, TOTP, OAuth
│   └── services/           #   Auth service, bot IPC client
├── docs/                   # Documentation
├── requirements.txt        # Python dependencies
└── pyproject.toml          # Project config (ruff, pytest)
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot | [discord.py](https://github.com/Rapptz/discord.py) 2.7 (slash commands, native voice) |
| API | [FastAPI](https://fastapi.tiangolo.com) + uvicorn |
| Database | [SQLAlchemy](https://www.sqlalchemy.org) 2.0 (async), SQLite / MySQL |
| Migrations | [Alembic](https://alembic.sqlalchemy.org) |
| Templates | [Jinja2](https://jinja.palletsprojects.com) (server-rendered) |
| Frontend | [Tailwind CSS](https://tailwindcss.com) 3, [Alpine.js](https://alpinejs.dev) 3 |
| Audio | [yt-dlp](https://github.com/yt-dlp/yt-dlp) + FFmpeg |
| Security | AES-256-GCM, bcrypt + pepper, TOTP 2FA, JWT refresh-token rotation |
| IPC | [Redis](https://redis.io) (optional, multi-process mode) |
| Logging | [structlog](https://www.structlog.org) (structured JSON logs) |

---

## ⚙️ Configuration

Settings are stored in the `.env` file (auto-generated by the installer):

| Setting | Default | Description |
|---------|---------|-------------|
| `DISCORD_BOT_TOKEN` | — | Discord bot token from the Developer Portal |
| `MASTER_KEY` | auto-generated | AES-256-GCM master key for encrypting secrets at rest |
| `JWT_SECRET` | auto-generated | Secret for signing JWT access/refresh tokens |
| `AUTH_PEPPER` | auto-generated | Pepper appended to password hashes (bcrypt) |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/cognix.db` | Database connection URL |
| `REDIS_URL` | — | Redis URL for multi-process IPC (optional) |
| `API_V1_PREFIX` | `/api/v1` | API route prefix |
| `ENVIRONMENT` | `development` | `development` or `production` |

### Data Storage

| Path | Content |
|------|---------|
| `.env` | Configuration & secrets |
| `data/cognix.db` | SQLite database (users, servers, cogs, tickets, etc.) |
| `data/cog_packages.json` | Tracked pip packages per installed cog |
| `cogs/` | Installed cog modules (copied from `cogs_store/` on install) |
| `cogs_store/` | Available cogs (source for installation) |

---

## 🧩 Cog System

CogniX uses a modular cog system. Cogs are self-contained feature modules that ship with their own Discord commands, web templates, and page routes.

| Cog | Category | Description |
|-----|----------|-------------|
| **Admin** | Core | Cog management commands (load/unload/reload) |
| **Moderation** | Moderation | Ban, kick, mute, warn, purge |
| **Music** | Entertainment | Full music player with queue, playlists, loop, shuffle |
| **Tickets** | Support | Thread-based tickets with panels and types |
| **Giveaways** | Entertainment | Reaction-based giveaways with auto winner selection |
| **Welcome** | Community | Join/leave/boost messages, invite tracking |
| **Logging** | Utility | Discord event logging, activity stats |
| **Backups** | Security | Encrypted server backups with diff preview |
| **Utility** | Utility | Ping, info, embeds, bot profile editor |

Each cog in `cogs_store/` includes:
- `*.py` — Discord cog module(s) with `setup()` function
- `templates/` — Jinja2 HTML templates (loaded dynamically via `ChoiceLoader`)
- `pages/` — FastAPI page routes (loaded dynamically via `importlib`)
- `requirements.txt` — Optional pip dependencies (auto-installed)

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [docs/](docs/) | Installation, first-run, commands, API, security, and Pterodactyl guides |

---

## 🐛 Reporting Issues

Found a bug? Open an [**Issue**](https://github.com/VeridonNetzwerk/CogniX/issues/new) and include:

- What you expected vs. what actually happened
- Your OS and Python version
- Whether you're using Docker or running from source
- Relevant log output from the console

---

## 💖 Support

If you like this project, consider donating:

<a href="https://www.paypal.com/donate/?hosted_button_id=972P9WTWE7RBU">
  <img src="https://img.shields.io/badge/Donate-PayPal-0070ba?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate via PayPal">
</a>

---

## 🙏 Credits & Built With

CogniX stands on the shoulders of these amazing open-source projects:

| Project | Role |
|---------|------|
| [discord.py](https://github.com/Rapptz/discord.py) | Discord API wrapper — powers all bot functionality |
| [FastAPI](https://fastapi.tiangolo.com) | Backend API framework |
| [SQLAlchemy](https://www.sqlalchemy.org) | Async ORM and database layer |
| [Alembic](https://alembic.sqlalchemy.org) | Database migrations |
| [Jinja2](https://jinja.palletsprojects.com) | Server-rendered HTML templates |
| [Tailwind CSS](https://tailwindcss.com) | Utility-first CSS framework |
| [Alpine.js](https://alpinejs.dev) | Lightweight frontend reactivity |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Audio extraction for music playback |
| [structlog](https://www.structlog.org) | Structured logging |
| [PyJWT](https://github.com/jpadilla/pyjwt) | JWT token signing and verification |
| [pyotp](https://github.com/pyauth/pyotp) | TOTP 2FA code generation/verification |
| [bcrypt](https://github.com/pyca/bcrypt) | Password hashing with pepper |
| [cryptography](https://github.com/pyca/cryptography) | AES-256-GCM encryption for secrets at rest |

### 🤖 Built With AI

Parts of this project were created and refined with the assistance of AI tools.

---

<div align="center">
  <sub>© 2026 VeridonNetzwerk</sub>
</div>
