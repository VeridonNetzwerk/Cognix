"""Tests for web.api — verify API modules can be imported without errors."""

from __future__ import annotations


class TestRouteImports:
    """Verify that all API modules import cleanly (no missing imports)."""

    def test_can_import_servers_route(self):
        from web.api import servers
        assert servers is not None
        assert hasattr(servers, "router")

    def test_can_import_cogs_route(self):
        from web.api import cogs
        assert cogs is not None
        assert hasattr(cogs, "router")

    def test_can_import_auth_route(self):
        from web.api import auth
        assert auth is not None
        assert hasattr(auth, "router")

    def test_can_import_marketplace_route(self):
        from web.api import marketplace
        assert marketplace is not None
        assert hasattr(marketplace, "router")

    def test_can_import_ws_route(self):
        from web.api import ws
        assert ws is not None
        assert hasattr(ws, "router")
