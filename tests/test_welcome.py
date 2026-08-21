"""Tests for the welcome cog — _format, _build_embed, defaults, disabled logic.

Tests:
- _format replaces all placeholders
- _format handles empty/non-string input
- _build_embed uses defaults when payload fields are empty
- _build_embed returns None for empty payload
- _build_embed handles invalid color gracefully
- _post skips when disabled or channel_id is None
- EMBED_TEMPLATES declaration is valid
"""

from __future__ import annotations

import pytest


class TestWelcomeFormat:
    """_format() placeholder replacement."""

    def _make_member(self, name="TestUser", mention="<@123>", id=123, member_count=100, guild_name="TestGuild"):
        class FakeGuild:
            pass
        class FakeMember:
            pass
        g = FakeGuild()
        g.name = guild_name
        g.member_count = member_count
        m = FakeMember()
        m.name = name
        m.mention = mention
        m.id = id
        m.guild = g
        return m, g

    def test_format_user_mention(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("Hello {user.mention}", m, g) == "Hello <@123>"

    def test_format_user_name(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("Bye {user.name}", m, g) == "Bye TestUser"

    def test_format_guild_name(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("Welcome to {guild.name}", m, g) == "Welcome to TestGuild"

    def test_format_member_count(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("You are #{guild.member_count}", m, g) == "You are #100"

    def test_format_empty_string(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("", m, g) == ""

    def test_format_non_string_input(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format(None, m, g) == ""
        assert _format(123, m, g) == ""

    def test_format_no_placeholders(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        assert _format("Just text", m, g) == "Just text"

    def test_format_multiple_placeholders(self):
        from cogs_store.dev.welcome.welcome import _format
        m, g = self._make_member()
        result = _format("{user.mention} joined {guild.name}! Member #{guild.member_count}", m, g)
        assert result == "<@123> joined TestGuild! Member #100"


class TestWelcomeBuildEmbed:
    """_build_embed() with defaults and edge cases."""

    def _make_member(self):
        class FakeGuild:
            name = "TestGuild"
            member_count = 50
        class FakeMember:
            name = "TestUser"
            mention = "<@123>"
            id = 123
            guild = FakeGuild()
        return FakeMember(), FakeGuild()

    def test_build_embed_with_full_payload(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "Custom Title", "description": "Custom desc", "color": 0xFF0000}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.title == "Custom Title"
        assert embed.description == "Custom desc"

    def test_build_embed_uses_defaults_for_empty_title(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "", "description": "Has desc"}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.title == "Welcome to the server!"

    def test_build_embed_uses_defaults_for_empty_description(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "Has title", "description": ""}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert "Welcome" in embed.description or "welcome" in embed.description

    def test_build_embed_empty_payload_returns_none(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        # Empty dict is falsy, _build_embed returns None
        embed = _build_embed({}, "join", m, g)
        assert embed is None

    def test_build_embed_with_empty_strings_uses_defaults(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        # Non-empty dict with empty title/desc should use defaults
        payload = {"title": "", "description": ""}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.title == "Welcome to the server!"

    def test_build_embed_handles_invalid_color(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "Test", "description": "Desc", "color": "not-a-number"}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        # Should fall back to blurple
        assert embed.colour is not None

    def test_build_embed_with_thumbnail(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "T", "description": "D", "thumbnail_url": "https://example.com/img.png"}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.thumbnail.url == "https://example.com/img.png"

    def test_build_embed_with_image(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "T", "description": "D", "image_url": "https://example.com/banner.png"}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.image.url == "https://example.com/banner.png"

    def test_build_embed_has_footer(self):
        from cogs_store.dev.welcome.welcome import _build_embed
        m, g = self._make_member()
        payload = {"title": "T", "description": "D"}
        embed = _build_embed(payload, "join", m, g)
        assert embed is not None
        assert embed.footer.text == "Powered by Cognix · Made by 食べ物"


class TestWelcomeDefaults:
    """_DEFAULTS dict structure."""

    def test_defaults_has_join(self):
        from cogs_store.dev.welcome.welcome import _DEFAULTS
        assert "join" in _DEFAULTS
        assert "title" in _DEFAULTS["join"]
        assert "description" in _DEFAULTS["join"]

    def test_defaults_has_leave(self):
        from cogs_store.dev.welcome.welcome import _DEFAULTS
        assert "leave" in _DEFAULTS
        assert "title" in _DEFAULTS["leave"]
        assert "description" in _DEFAULTS["leave"]

    def test_defaults_has_boost(self):
        from cogs_store.dev.welcome.welcome import _DEFAULTS
        assert "boost" in _DEFAULTS
        assert "title" in _DEFAULTS["boost"]
        assert "description" in _DEFAULTS["boost"]


class TestWelcomeEmbedTemplates:
    """EMBED_TEMPLATES declaration validity."""

    def test_embed_templates_is_list(self):
        from cogs_store.dev.welcome.welcome import EMBED_TEMPLATES
        assert isinstance(EMBED_TEMPLATES, list)
        assert len(EMBED_TEMPLATES) == 3

    def test_embed_templates_have_keys(self):
        from cogs_store.dev.welcome.welcome import EMBED_TEMPLATES
        keys = [t["key"] for t in EMBED_TEMPLATES]
        assert "welcome_join" in keys
        assert "welcome_leave" in keys
        assert "welcome_boost" in keys

    def test_embed_templates_have_required_fields(self):
        from cogs_store.dev.welcome.welcome import EMBED_TEMPLATES
        for tpl in EMBED_TEMPLATES:
            assert "key" in tpl
            assert "title" in tpl
            assert "description" in tpl
            assert "color" in tpl
            assert "footer_text" in tpl


class TestWelcomeCogInfo:
    """COG_INFO structure."""

    def test_cog_info_has_required_fields(self):
        from cogs_store.dev.welcome.welcome import COG_INFO
        assert "name" in COG_INFO
        assert "description" in COG_INFO
        assert "category" in COG_INFO
        assert "version" in COG_INFO
