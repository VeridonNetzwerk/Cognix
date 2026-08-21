"""Tests for cog registry — discover_embed_templates, COG_CATEGORIES, cog info.

Tests:
- discover_embed_templates returns list of dicts with augmented metadata
- get_all_cog_info returns cog metadata
- COG_CATEGORIES has expected structure
- get_available_widgets returns widget definitions from cogs
- cog store cogs have required fields
"""

from __future__ import annotations

import pytest


class TestDiscoverEmbedTemplates:
    """registry.discover_embed_templates()"""

    def test_returns_list(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        assert isinstance(result, list)

    def test_each_template_has_key(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert isinstance(tpl.get("key"), str)
            assert len(tpl["key"]) > 0

    def test_each_template_has_cog_metadata(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert "_cog_module" in tpl
            assert "_cog_name" in tpl
            assert "_cog_category" in tpl

    def test_each_template_source_is_cog(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert tpl.get("source") == "cog"

    def test_templates_have_title_and_description(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert "title" in tpl
            assert "description" in tpl

    def test_no_duplicate_keys(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        keys = [t["key"] for t in result]
        assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"


class TestCogCategories:
    """COG_CATEGORIES constant."""

    def test_categories_is_dict(self):
        from bot.cogs.registry import COG_CATEGORIES
        assert isinstance(COG_CATEGORIES, dict)

    def test_categories_have_required_keys(self):
        from bot.cogs.registry import COG_CATEGORIES
        for cat_name, meta in COG_CATEGORIES.items():
            assert "icon" in meta
            assert "slogan" in meta
            assert "gradient_from" in meta
            assert "gradient_to" in meta

    def test_expected_categories_exist(self):
        from bot.cogs.registry import COG_CATEGORIES
        expected = ["Core", "Administration", "Moderation", "Fun", "Utility"]
        for cat in expected:
            assert cat in COG_CATEGORIES


class TestGetAllCogInfo:
    """get_all_cog_info()"""

    def test_returns_list(self):
        from bot.cogs.registry import get_all_cog_info
        result = get_all_cog_info()
        assert isinstance(result, list)

    def test_each_cog_has_required_fields(self):
        from bot.cogs.registry import get_all_cog_info
        result = get_all_cog_info()
        for ci in result:
            assert "name" in ci
            assert "module" in ci
            assert "category" in ci

    def test_each_cog_has_version(self):
        from bot.cogs.registry import get_all_cog_info
        result = get_all_cog_info()
        for ci in result:
            assert "version" in ci


class TestGetAvailableWidgets:
    """get_available_widgets()"""

    def test_returns_list(self):
        from bot.cogs.registry import get_available_widgets
        result = get_available_widgets()
        assert isinstance(result, list)

    def test_each_widget_has_required_fields(self):
        from bot.cogs.registry import get_available_widgets
        result = get_available_widgets()
        for w in result:
            assert "id" in w
            assert "title" in w
            assert "template" in w
            assert "size" in w
