"""Tests for web.routes — verify route modules can be imported without errors."""

from __future__ import annotations


class TestRouteImports:
    """Verify that all route modules import cleanly (no missing imports)."""

    def test_can_import_servers_route(self):
        from web.routes import servers
        assert servers is not None
        assert hasattr(servers, "router")

    def test_can_import_cogs_route(self):
        from web.routes import cogs
        assert cogs is not None
        assert hasattr(cogs, "router")

    def test_can_import_auth_route(self):
        from web.routes import auth
        assert auth is not None
        assert hasattr(auth, "router")

    def test_can_import_marketplace_route(self):
        from web.routes import marketplace
        assert marketplace is not None
        assert hasattr(marketplace, "router")

    def test_can_import_ws_route(self):
        from web.routes import ws
        assert ws is not None
        assert hasattr(ws, "router")
