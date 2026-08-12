"""Tests for config.constants — project-wide constants."""

from __future__ import annotations

from config.constants import (
    API_V1_PREFIX,
    AUDIT_LOGIN,
    AUDIT_LOGOUT,
    DEFAULT_ROLES,
    HEALTH_PATH,
    IPC_ACK_CHANNEL,
    IPC_CMD_CHANNEL,
    IPC_EVENT_CHANNEL,
    ROLE_ADMIN,
    ROLE_MODERATOR,
    ROLE_VIEWER,
    SETUP_PATH,
)


class TestConstants:
    """Tests for project constants."""

    def test_api_prefix(self):
        assert API_V1_PREFIX == "/api/v1"

    def test_setup_path(self):
        assert SETUP_PATH == "/setup"

    def test_health_path(self):
        assert HEALTH_PATH == "/health"

    def test_ipc_channels_are_strings(self):
        assert isinstance(IPC_CMD_CHANNEL, str)
        assert isinstance(IPC_ACK_CHANNEL, str)
        assert isinstance(IPC_EVENT_CHANNEL, str)

    def test_ipc_channels_are_distinct(self):
        assert IPC_CMD_CHANNEL != IPC_ACK_CHANNEL
        assert IPC_CMD_CHANNEL != IPC_EVENT_CHANNEL
        assert IPC_ACK_CHANNEL != IPC_EVENT_CHANNEL

    def test_audit_actions_are_strings(self):
        assert isinstance(AUDIT_LOGIN, str)
        assert isinstance(AUDIT_LOGOUT, str)

    def test_default_roles_contain_all(self):
        assert ROLE_ADMIN in DEFAULT_ROLES
        assert ROLE_MODERATOR in DEFAULT_ROLES
        assert ROLE_VIEWER in DEFAULT_ROLES

    def test_role_values(self):
        assert ROLE_ADMIN == "ADMIN"
        assert ROLE_MODERATOR == "MODERATOR"
        assert ROLE_VIEWER == "VIEWER"
