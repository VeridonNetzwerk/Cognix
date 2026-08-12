"""Tests for web.services.bot_ipc — IPC client structure."""

from __future__ import annotations


class TestBotIpcImport:
    """Verify that bot_ipc module can be imported without errors (log variable fix)."""

    def test_can_import_bot_ipc(self):
        from web.services.bot_ipc import BotIpc, get_ipc
        assert BotIpc is not None
        assert get_ipc is not None

    def test_get_ipc_returns_singleton(self):
        from web.services.bot_ipc import get_ipc
        ipc1 = get_ipc()
        ipc2 = get_ipc()
        assert ipc1 is ipc2

    def test_bot_ipc_has_connect_method(self):
        from web.services.bot_ipc import BotIpc
        ipc = BotIpc()
        assert hasattr(ipc, "connect")
        assert hasattr(ipc, "close")
        assert hasattr(ipc, "call")

    def test_bot_ipc_has_subscribe_events(self):
        from web.services.bot_ipc import BotIpc
        ipc = BotIpc()
        assert hasattr(ipc, "subscribe_events")
        assert hasattr(ipc, "unsubscribe_events")
