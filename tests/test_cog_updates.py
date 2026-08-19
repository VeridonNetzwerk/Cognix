"""Tests for cog version parsing, update detection, and cog update API endpoints."""

import pytest
from unittest.mock import patch

from bot.cogs.registry import _parse_version, _is_newer, get_cog_updates, get_store_cog_info, get_all_cog_info


class TestVersionParsing:
    """Test the _parse_version helper."""

    def test_parse_simple_semver(self):
        assert _parse_version("1.0.0") == (1, 0, 0)

    def test_parse_two_part(self):
        assert _parse_version("2.1") == (2, 1)

    def test_parse_single_part(self):
        assert _parse_version("3") == (3,)

    def test_parse_with_pre_release_suffix(self):
        # "1.0.0-beta" → strip non-numeric → (1, 0, 0)
        assert _parse_version("1.0.0-beta") == (1, 0, 0)

    def test_parse_empty_string(self):
        assert _parse_version("") == (0,)

    def test_parse_four_parts(self):
        assert _parse_version("1.2.3.4") == (1, 2, 3, 4)


class TestIsNewer:
    """Test the _is_newer version comparison helper."""

    def test_newer_major(self):
        assert _is_newer("2.0.0", "1.0.0") is True

    def test_newer_minor(self):
        assert _is_newer("1.1.0", "1.0.0") is True

    def test_newer_patch(self):
        assert _is_newer("1.0.1", "1.0.0") is True

    def test_same_version(self):
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert _is_newer("1.0.0", "2.0.0") is False

    def test_empty_store_version(self):
        assert _is_newer("", "1.0.0") is False

    def test_empty_installed_version(self):
        assert _is_newer("1.0.0", "") is True

    def test_both_empty(self):
        assert _is_newer("", "") is False

    def test_different_lengths(self):
        assert _is_newer("1.0.0.1", "1.0.0") is True

    def test_pre_release_vs_release(self):
        # "1.0.0-beta" parses to (1,0,0) so same version
        assert _is_newer("1.0.0-beta", "1.0.0") is False


class TestCogInfoHasVersion:
    """Test that CogInfo dicts from registry include version field."""

    def test_store_cogs_have_version(self):
        cogs = get_store_cog_info()
        assert len(cogs) > 0
        for cog in cogs:
            assert "version" in cog
            assert cog["version"] != ""

    def test_store_cogs_version_format(self):
        cogs = get_store_cog_info()
        for cog in cogs:
            v = cog["version"]
            # Should be parseable as a version
            parts = _parse_version(v)
            assert len(parts) >= 1


class TestGetCogUpdates:
    """Test the get_cog_updates function."""

    def test_updates_returns_list(self):
        updates = get_cog_updates()
        assert isinstance(updates, list)

    def test_updates_have_required_fields(self):
        updates = get_cog_updates()
        for upd in updates:
            assert "module" in upd
            assert "name" in upd
            assert "installed_version" in upd
            assert "store_version" in upd
            assert "description" in upd
            assert "category" in upd

    def test_no_updates_when_versions_match(self):
        """When installed and store versions are the same, no updates should be returned."""
        installed = [
            {"module": "cogs.test", "name": "Test", "version": "1.0.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
        ]
        store = [
            {"module": "cogs.test", "name": "Test", "version": "1.0.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
        ]
        with patch("bot.cogs.registry.get_all_cog_info", return_value=installed), \
             patch("bot.cogs.registry.get_store_cog_info", return_value=store):
            updates = get_cog_updates()
        assert len(updates) == 0

    def test_update_detected_when_store_newer(self):
        """When store version is newer, an update should be returned."""
        installed = [
            {"module": "cogs.test", "name": "Test", "version": "1.0.0",
             "description": "Test cog", "category": "Utility", "icon_url": None, "requires_admin": False},
        ]
        store = [
            {"module": "cogs.test", "name": "Test", "version": "2.0.0",
             "description": "Test cog", "category": "Utility", "icon_url": None, "requires_admin": False},
        ]
        with patch("bot.cogs.registry.get_all_cog_info", return_value=installed), \
             patch("bot.cogs.registry.get_store_cog_info", return_value=store):
            updates = get_cog_updates()
        assert len(updates) == 1
        assert updates[0]["module"] == "cogs.test"
        assert updates[0]["installed_version"] == "1.0.0"
        assert updates[0]["store_version"] == "2.0.0"

    def test_no_update_for_cog_not_in_store(self):
        """Cogs installed but not in store should not appear in updates."""
        installed = [
            {"module": "cogs.custom", "name": "Custom", "version": "1.0.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
        ]
        store = []
        with patch("bot.cogs.registry.get_all_cog_info", return_value=installed), \
             patch("bot.cogs.registry.get_store_cog_info", return_value=store):
            updates = get_cog_updates()
        assert len(updates) == 0

    def test_multiple_updates(self):
        installed = [
            {"module": "cogs.a", "name": "A", "version": "1.0.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
            {"module": "cogs.b", "name": "B", "version": "2.1.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
            {"module": "cogs.c", "name": "C", "version": "3.0.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
        ]
        store = [
            {"module": "cogs.a", "name": "A", "version": "1.1.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
            {"module": "cogs.b", "name": "B", "version": "2.1.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
            {"module": "cogs.c", "name": "C", "version": "3.1.0",
             "description": "", "category": "", "icon_url": None, "requires_admin": False},
        ]
        with patch("bot.cogs.registry.get_all_cog_info", return_value=installed), \
             patch("bot.cogs.registry.get_store_cog_info", return_value=store):
            updates = get_cog_updates()
        assert len(updates) == 2
        modules = [u["module"] for u in updates]
        assert "cogs.a" in modules
        assert "cogs.c" in modules
        assert "cogs.b" not in modules  # same version, no update


class TestCogUpdatesAPI:
    """Test the cog updates API endpoints."""

    @pytest.mark.asyncio
    async def test_store_updates_endpoint(self, auth_client):
        """GET /api/v1/cogs/store/updates should return updates list."""
        resp = await auth_client.get("/api/v1/cogs/store/updates")
        assert resp.status_code == 200
        data = resp.json()
        assert "updates" in data
        assert "total" in data
        assert isinstance(data["updates"], list)

    @pytest.mark.asyncio
    async def test_store_endpoint_includes_version(self, auth_client):
        """GET /api/v1/cogs/store should include version field for each cog."""
        resp = await auth_client.get("/api/v1/cogs/store")
        assert resp.status_code == 200
        data = resp.json()
        assert "cogs" in data
        if len(data["cogs"]) > 0:
            cog = data["cogs"][0]
            assert "version" in cog

    @pytest.mark.asyncio
    async def test_store_updates_requires_auth(self, unconfigured_client):
        """Updates endpoint should require auth."""
        resp = await unconfigured_client.get("/api/v1/cogs/store/updates")
        # Should get 423 (setup gate) or 401 (auth required)
        assert resp.status_code in (401, 423)

    @pytest.mark.asyncio
    async def test_list_cogs_includes_version(self, auth_client):
        """GET /api/v1/cogs/ should include version field."""
        resp = await auth_client.get("/api/v1/cogs/")
        assert resp.status_code == 200
        data = resp.json()
        assert "cogs" in data
        if len(data["cogs"]) > 0:
            cog = data["cogs"][0]
            assert "version" in cog
