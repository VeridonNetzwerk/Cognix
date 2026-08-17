# Architecture

## Project Structure

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

## Tech Stack

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

## Credits

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
