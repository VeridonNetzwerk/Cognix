"""Tests for config.constants — project-wide constants."""

from __future__ import annotations

from bot.config.constants import (
    API_V1_PREFIX,
    AUDIT_LOGIN,
    AUDIT_LOGIN_FAILED,
    AUDIT_LOGOUT,
    AUDIT_USER_CREATED,
    AUDIT_USER_DELETED,
    AUDIT_USER_UPDATED,
    IPC_ACK_CHANNEL,
    IPC_CMD_CHANNEL,
    IPC_EVENT_CHANNEL,
)


class TestConstants:
    """Tests for project constants."""

    def test_api_prefix(self):
        assert API_V1_PREFIX == "/api/v1"

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
        assert isinstance(AUDIT_LOGIN_FAILED, str)
        assert isinstance(AUDIT_USER_CREATED, str)
        assert isinstance(AUDIT_USER_UPDATED, str)
        assert isinstance(AUDIT_USER_DELETED, str)

