"""Tests for bot.cogs.registry — cog registry, load/unload, persistence."""

from __future__ import annotations

from bot.cogs.registry import (
    _loaded_cogs,
    _update_loaded_state,
    get_all_cog_info,
    get_cog_info,
    get_loaded_cogs,
    is_cog_loaded,
)


class TestCogDiscovery:
    """Tests for the dynamic cog discovery."""

    def test_discovered_cogs_not_empty(self):
        cogs = get_all_cog_info()
        assert len(cogs) >= 1

    def test_each_cog_has_required_fields(self):
        for cog in get_all_cog_info():
            assert "module" in cog, f"Missing 'module' in {cog}"
            assert "name" in cog, f"Missing 'name' in {cog}"
            assert "description" in cog, f"Missing 'description' in {cog}"
            assert "category" in cog, f"Missing 'category' in {cog}"
            assert "requires_admin" in cog, f"Missing 'requires_admin' in {cog}"
            assert isinstance(cog["requires_admin"], bool)

    def test_each_cog_module_starts_with_cogs(self):
        for cog in get_all_cog_info():
            mod = cog["module"]
            assert mod.startswith("cogs."), f"Module {mod} doesn't start with cogs."


class TestGetAllCogInfo:
    """Tests for get_all_cog_info()."""

    def test_returns_list_of_dicts(self):
        result = get_all_cog_info()
        assert isinstance(result, list)

    def test_returns_copies_not_references(self):
        result = get_all_cog_info()
        for original, copy in zip(get_all_cog_info(), result, strict=False):
            assert original is not copy, "Should return copies, not references"


class TestGetCogInfo:
    """Tests for get_cog_info() — name matching logic."""

    def test_match_by_module_path(self):
        info = get_cog_info("cogs.moderation.moderation")
        assert info is not None
        assert info["name"] == "Moderation"

    def test_match_by_name(self):
        info = get_cog_info("Moderation")
        assert info is not None
        assert info["module"] == "cogs.moderation.moderation"

    def test_match_by_name_case_insensitive(self):
        info = get_cog_info("moderation")
        assert info is not None
        assert info["module"] == "cogs.moderation.moderation"

    def test_unknown_cog_returns_none(self):
        assert get_cog_info("nonexistent_cog") is None
        assert get_cog_info("") is None


class TestLoadedCogs:
    """Tests for the runtime loaded-cog tracking."""

    def teardown_method(self):
        _loaded_cogs.clear()

    def test_get_loaded_cogs_empty(self):
        _loaded_cogs.clear()
        assert get_loaded_cogs() == []

    def test_update_loaded_state_add(self):
        _loaded_cogs.clear()
        _update_loaded_state("cogs.moderation.moderation", True)
        assert "cogs.moderation.moderation" in _loaded_cogs
        assert "cogs.moderation.moderation" in get_loaded_cogs()

    def test_update_loaded_state_remove(self):
        _loaded_cogs.clear()
        _update_loaded_state("cogs.moderation.moderation", True)
        _update_loaded_state("cogs.moderation.moderation", False)
        assert "cogs.moderation.moderation" not in _loaded_cogs

    def test_is_cog_loaded_by_full_name(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("cogs.moderation.moderation")
        assert is_cog_loaded("cogs.moderation.moderation") is True

    def test_is_cog_loaded_by_short_name(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("cogs.moderation.moderation")
        assert is_cog_loaded("moderation") is True

    def test_is_cog_loaded_not_loaded(self):
        _loaded_cogs.clear()
        assert is_cog_loaded("moderation") is False

    def test_get_loaded_cogs_sorted(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("cogs.utility.utility")
        _loaded_cogs.add("cogs.moderation.moderation")
        result = get_loaded_cogs()
        assert result == sorted(result)
