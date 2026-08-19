"""Project-wide constants."""

from __future__ import annotations

API_V1_PREFIX = "/api/v1"

# Redis channels / streams
IPC_CMD_CHANNEL = "cognix:bot:cmd"
IPC_ACK_CHANNEL = "cognix:bot:ack"
IPC_EVENT_CHANNEL = "cognix:events"

# Audit log actions
AUDIT_LOGIN = "auth.login"
AUDIT_LOGIN_FAILED = "auth.login_failed"
AUDIT_LOGOUT = "auth.logout"
AUDIT_USER_CREATED = "web_user.created"
AUDIT_USER_UPDATED = "web_user.updated"
AUDIT_USER_DELETED = "web_user.deleted"
