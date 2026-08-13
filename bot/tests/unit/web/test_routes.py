"""Tests for web.api — verify API subpackages can be imported without errors."""

from __future__ import annotations


class TestRouteImports:
    """Verify that all API subpackages import cleanly (no missing imports)."""

    def test_can_import_servers_api(self):
        from web.api import servers
        assert servers is not None
        assert hasattr(servers, "servers_router")

    def test_can_import_bot_api(self):
        from web.api import bot
        assert bot is not None
        assert hasattr(bot, "cogs_router")

    def test_can_import_auth_api(self):
        from web.api import auth
        assert auth is not None
        assert hasattr(auth, "auth_router")
        assert hasattr(auth, "setup_router")

    def test_can_import_ws_api(self):
        from web.api import ws
        assert ws is not None
        assert hasattr(ws, "ws_router")

    def test_can_import_all_api_packages(self):
        from web.api import auth, bot, servers, users, moderation, settings, content, ws
        for pkg in (auth, bot, servers, users, moderation, settings, content, ws):
            assert pkg is not None
