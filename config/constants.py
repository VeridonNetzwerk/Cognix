"""Project-wide constants."""

from __future__ import annotations

API_V1_PREFIX = "/api/v1"
SETUP_PATH = "/setup"
HEALTH_PATH = "/health"

# Redis channels / streams
IPC_CMD_CHANNEL = "cognix:bot:cmd"
IPC_ACK_CHANNEL = "cognix:bot:ack"
IPC_EVENT_CHANNEL = "cognix:events"
STATS_STREAM = "cognix:stats"

# Audit log actions
AUDIT_LOGIN = "auth.login"
AUDIT_LOGIN_FAILED = "auth.login_failed"
AUDIT_LOGOUT = "auth.logout"
AUDIT_BOT_TOKEN_CHANGED = "bot.token_changed"
AUDIT_COG_RELOAD = "bot.cog_reload"
AUDIT_BACKUP_CREATE = "backup.create"
AUDIT_BACKUP_RESTORE = "backup.restore"
AUDIT_USER_CREATED = "web_user.created"
AUDIT_USER_UPDATED = "web_user.updated"
AUDIT_USER_DELETED = "web_user.deleted"
AUDIT_SETTINGS_CHANGED = "settings.changed"

# Web roles (also stored in DB; this list bootstraps them)
ROLE_ADMIN = "ADMIN"
ROLE_MODERATOR = "MODERATOR"
ROLE_VIEWER = "VIEWER"
DEFAULT_ROLES = (ROLE_ADMIN, ROLE_MODERATOR, ROLE_VIEWER)
