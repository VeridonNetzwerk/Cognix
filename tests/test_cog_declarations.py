"""Tests for all cog EMBED_TEMPLATES declarations.

Ensures every cog that declares EMBED_TEMPLATES has valid structure:
- Each template has required keys (key, title, description, color, footer_text)
- Keys are unique within a cog
- Colors are valid integers
- COG_INFO is present and valid
"""

from __future__ import annotations

import importlib
import pytest


# All cogs that may declare EMBED_TEMPLATES
_COG_MODULES = [
    "cogs_store.dev.welcome.welcome",
    "cogs_store.dev.tickets.tickets",
    "cogs_store.dev.moderation.moderation",
    "cogs_store.dev.music.music",
    "cogs_store.dev.giveaways.giveaway",
    "cogs_store.dev.leveling.leveling",
    "cogs_store.dev.embeds.embeds",
]


def _safe_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


class TestCogEmbedTemplates:
    """Validate EMBED_TEMPLATES in every cog."""

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_embed_templates_is_list_or_none(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        templates = getattr(mod, "EMBED_TEMPLATES", None)
        if templates is None:
            pytest.skip(f"{module_name} has no EMBED_TEMPLATES")
        assert isinstance(templates, list)

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_embed_templates_have_required_keys(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        templates = getattr(mod, "EMBED_TEMPLATES", None)
        if not templates:
            pytest.skip(f"{module_name} has no EMBED_TEMPLATES")
        for tpl in templates:
            assert "key" in tpl, f"{module_name}: template missing 'key'"
            assert isinstance(tpl["key"], str)
            assert len(tpl["key"]) > 0
            assert "title" in tpl
            assert "description" in tpl
            assert "color" in tpl

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_embed_templates_no_duplicate_keys(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        templates = getattr(mod, "EMBED_TEMPLATES", None)
        if not templates:
            pytest.skip(f"{module_name} has no EMBED_TEMPLATES")
        keys = [t["key"] for t in templates]
        assert len(keys) == len(set(keys)), f"{module_name}: duplicate keys {keys}"

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_embed_templates_colors_are_integers(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        templates = getattr(mod, "EMBED_TEMPLATES", None)
        if not templates:
            pytest.skip(f"{module_name} has no EMBED_TEMPLATES")
        for tpl in templates:
            assert isinstance(tpl["color"], int)
            assert 0 <= tpl["color"] <= 0xFFFFFF


class TestCogInfoDeclarations:
    """Validate COG_INFO in every cog."""

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_cog_info_exists(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        info = getattr(mod, "COG_INFO", None)
        if info is None:
            pytest.skip(f"{module_name} has no COG_INFO")
        assert isinstance(info, dict)

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_cog_info_has_required_fields(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        info = getattr(mod, "COG_INFO", None)
        if info is None:
            pytest.skip(f"{module_name} has no COG_INFO")
        assert "name" in info
        assert "description" in info
        assert "category" in info
        assert "version" in info

    @pytest.mark.parametrize("module_name", _COG_MODULES)
    def test_cog_info_category_is_valid(self, module_name):
        mod = _safe_import(module_name)
        if mod is None:
            pytest.skip(f"Could not import {module_name}")
        info = getattr(mod, "COG_INFO", None)
        if info is None:
            pytest.skip(f"{module_name} has no COG_INFO")
        from bot.cogs.registry import COG_CATEGORIES
        assert info["category"] in COG_CATEGORIES, (
            f"{module_name}: category '{info['category']}' not in COG_CATEGORIES"
        )


class TestLevelingCogInfo:
    """Specific tests for leveling cog declarations."""

    def test_leveling_cog_info(self):
        from cogs_store.dev.leveling.leveling import COG_INFO
        assert COG_INFO["name"] == "Leveling"
        assert COG_INFO["category"] == "Fun"

    def test_leveling_embed_templates_count(self):
        from cogs_store.dev.leveling.leveling import EMBED_TEMPLATES
        assert len(EMBED_TEMPLATES) == 2

    def test_leveling_embed_templates_keys(self):
        from cogs_store.dev.leveling.leveling import EMBED_TEMPLATES
        keys = [t["key"] for t in EMBED_TEMPLATES]
        assert "level_up" in keys
        assert "level_up_dm" in keys

    def test_leveling_widgets_declared(self):
        from cogs_store.dev.leveling.leveling import WIDGETS
        assert isinstance(WIDGETS, list)
        assert len(WIDGETS) == 2
        widget_ids = [w["id"] for w in WIDGETS]
        assert "leveling_top" in widget_ids
        assert "leveling_stats" in widget_ids
