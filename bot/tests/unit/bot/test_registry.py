"""Tests for bot.cogs.registry — cog registry, load/unload, persistence."""

from __future__ import annotations

from bot.cogs.registry import (
    AVAILABLE_COGS,
    BUILTIN_COGS,
    _loaded_cogs,
    _update_loaded_state,
    get_all_cog_info,
    get_cog_info,
    get_loaded_cogs,
    is_cog_loaded,
)


class TestBuiltinCogs:
    """Tests for the static cog registry."""

    def test_builtin_cogs_not_empty(self):
        assert len(BUILTIN_COGS) >= 10

    def test_each_cog_has_required_fields(self):
        for cog in BUILTIN_COGS:
            assert "module" in cog, f"Missing 'module' in {cog}"
            assert "name" in cog, f"Missing 'name' in {cog}"
            assert "description" in cog, f"Missing 'description' in {cog}"
            assert "category" in cog, f"Missing 'category' in {cog}"
            assert "requires_admin" in cog, f"Missing 'requires_admin' in {cog}"
            assert isinstance(cog["requires_admin"], bool)

    def test_each_cog_module_is_valid_path(self):
        for cog in BUILTIN_COGS:
            mod = cog["module"]
            assert mod.startswith("bot.cogs."), f"Module {mod} doesn't start with bot.cogs."

    def test_available_cogs_alias_matches_builtin(self):
        assert AVAILABLE_COGS is BUILTIN_COGS


class TestGetAllCogInfo:
    """Tests for get_all_cog_info()."""

    def test_returns_list_of_dicts(self):
        result = get_all_cog_info()
        assert isinstance(result, list)
        assert len(result) >= len(BUILTIN_COGS)

    def test_returns_copies_not_references(self):
        result = get_all_cog_info()
        for original, copy in zip(BUILTIN_COGS, result, strict=False):
            assert original is not copy, "Should return copies, not references"


class TestGetCogInfo:
    """Tests for get_cog_info() — name matching logic."""

    def test_match_by_module_path(self):
        info = get_cog_info("bot.cogs.moderation.moderation")
        assert info is not None
        assert info["name"] == "Moderation"

    def test_match_by_name(self):
        info = get_cog_info("Moderation")
        assert info is not None
        assert info["module"] == "bot.cogs.moderation.moderation"

    def test_match_by_name_case_insensitive(self):
        info = get_cog_info("moderation")
        assert info is not None
        assert info["module"] == "bot.cogs.moderation.moderation"

    def test_match_by_name_with_spaces(self):
        info = get_cog_info("Activity Log")
        assert info is not None
        assert info["module"] == "bot.cogs.logging.activity_log"

    def test_match_by_name_with_underscores(self):
        """Should match 'Activity_Log' -> 'Activity Log' cog."""
        info = get_cog_info("Activity_Log")
        assert info is not None
        assert info["module"] == "bot.cogs.logging.activity_log"

    def test_match_by_name_with_underscores_welcome(self):
        """Should match 'Welcome_Leave' -> 'Welcome/Leave' cog."""
        info = get_cog_info("Welcome_Leave")
        assert info is not None
        assert info["module"] == "bot.cogs.welcome.welcome"

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
        _update_loaded_state("bot.cogs.moderation.moderation", True)
        assert "bot.cogs.moderation.moderation" in _loaded_cogs
        assert "bot.cogs.moderation.moderation" in get_loaded_cogs()

    def test_update_loaded_state_remove(self):
        _loaded_cogs.clear()
        _update_loaded_state("bot.cogs.moderation.moderation", True)
        _update_loaded_state("bot.cogs.moderation.moderation", False)
        assert "bot.cogs.moderation.moderation" not in _loaded_cogs

    def test_is_cog_loaded_by_full_name(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("bot.cogs.moderation.moderation")
        assert is_cog_loaded("bot.cogs.moderation.moderation") is True

    def test_is_cog_loaded_by_short_name(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("bot.cogs.moderation.moderation")
        assert is_cog_loaded("moderation") is True

    def test_is_cog_loaded_not_loaded(self):
        _loaded_cogs.clear()
        assert is_cog_loaded("moderation") is False

    def test_get_loaded_cogs_sorted(self):
        _loaded_cogs.clear()
        _loaded_cogs.add("bot.cogs.utility.utility")
        _loaded_cogs.add("bot.cogs.moderation.moderation")
        result = get_loaded_cogs()
        assert result == sorted(result)
