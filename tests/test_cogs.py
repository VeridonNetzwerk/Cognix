"""Tests for cog store API: list, install, uninstall."""

from __future__ import annotations

import pytest


class TestCogStore:
    """GET /api/v1/cogs/store"""

    async def test_store_list(self, auth_client):
        resp = await auth_client.get("/api/v1/cogs/store")
        assert resp.status_code == 200
        data = resp.json()
        assert "cogs" in data
        assert "total" in data
        assert isinstance(data["cogs"], list)

    async def test_store_list_without_auth(self, client):
        resp = await client.get("/api/v1/cogs/store")
        assert resp.status_code == 401

    async def test_store_no_duplicate_cogs(self, auth_client):
        """Verify no duplicate cog names in store (regression test)."""
        resp = await auth_client.get("/api/v1/cogs/store")
        assert resp.status_code == 200
        cogs = resp.json()["cogs"]
        names = [c["name"] for c in cogs]
        # Check for duplicates
        assert len(names) == len(set(names)), f"Duplicate cog names: {names}"

    async def test_store_cogs_have_required_fields(self, auth_client):
        resp = await auth_client.get("/api/v1/cogs/store")
        assert resp.status_code == 200
        cogs = resp.json()["cogs"]
        for cog in cogs:
            assert "name" in cog
            assert "module" in cog
            assert "installed" in cog


class TestCogList:
    """GET /api/v1/cogs/"""

    async def test_list_cogs(self, auth_client):
        resp = await auth_client.get("/api/v1/cogs/")
        assert resp.status_code == 200
        data = resp.json()
        assert "cogs" in data
        assert "total" in data
        assert "loaded_count" in data

    async def test_list_cogs_without_auth(self, client):
        resp = await client.get("/api/v1/cogs/")
        assert resp.status_code == 401
