"""Tests for embed template seeding and discovery.

Tests:
- seed_default_embed_templates inserts all DEFAULT_TEMPLATES
- re-seeding is idempotent (no duplicates)
- cog-discovered templates get proper metadata in extras
- existing templates preserve user edits on re-seed
- discover_embed_templates returns augmented dicts with cog metadata
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.database.models.content.embed_template import EmbedTemplate
from bot.database.seed_embeds import DEFAULT_TEMPLATES, seed_default_embed_templates


class TestSeedEmbedTemplates:
    """seed_default_embed_templates()"""

    async def test_seed_inserts_all_defaults(self, db_sessionmaker):
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        count = await seed_default_embed_templates()
        assert count == len(DEFAULT_TEMPLATES)

        async with db_sessionmaker() as s:
            rows = (await s.scalars(select(EmbedTemplate))).all()
            assert len(rows) == len(DEFAULT_TEMPLATES)
            keys = {r.key for r in rows}
            for tpl in DEFAULT_TEMPLATES:
                assert tpl["key"] in keys

    async def test_seed_is_idempotent(self, db_sessionmaker):
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        first = await seed_default_embed_templates()
        second = await seed_default_embed_templates()
        assert first == len(DEFAULT_TEMPLATES)
        assert second == 0

        async with db_sessionmaker() as s:
            rows = (await s.scalars(select(EmbedTemplate))).all()
            assert len(rows) == len(DEFAULT_TEMPLATES)

    async def test_seeded_templates_are_global(self, db_sessionmaker):
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        await seed_default_embed_templates()

        async with db_sessionmaker() as s:
            rows = (await s.scalars(select(EmbedTemplate))).all()
            for r in rows:
                assert r.server_id is None

    async def test_seeded_templates_have_footer(self, db_sessionmaker):
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        await seed_default_embed_templates()

        async with db_sessionmaker() as s:
            rows = (await s.scalars(select(EmbedTemplate))).all()
            for r in rows:
                assert r.footer_text == "Powered by Cognix · Made by 食べ物"

    async def test_seeded_templates_are_enabled(self, db_sessionmaker):
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        await seed_default_embed_templates()

        async with db_sessionmaker() as s:
            rows = (await s.scalars(select(EmbedTemplate))).all()
            for r in rows:
                assert r.enabled is True

    async def test_seed_preserves_user_edits_on_reseed(self, db_sessionmaker):
        """Re-seeding should not overwrite user edits to template content."""
        import bot.database.session as session_mod
        session_mod._sessionmaker = db_sessionmaker
        session_mod._engine = True

        await seed_default_embed_templates()

        async with db_sessionmaker() as s:
            tpl = await s.scalar(
                select(EmbedTemplate).where(EmbedTemplate.key == "info")
            )
            assert tpl is not None
            tpl.title = "Custom Title by User"
            tpl.description = "User edited description"
            await s.commit()

        count = await seed_default_embed_templates()
        assert count == 0

        async with db_sessionmaker() as s:
            tpl = await s.scalar(
                select(EmbedTemplate).where(EmbedTemplate.key == "info")
            )
            assert tpl is not None
            assert tpl.title == "Custom Title by User"
            assert tpl.description == "User edited description"


class TestDiscoverEmbedTemplates:
    """bot.cogs.registry.discover_embed_templates()"""

    def test_discover_returns_list(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        assert isinstance(result, list)

    def test_discovered_templates_have_keys(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert "key" in tpl
            assert isinstance(tpl["key"], str)
            assert len(tpl["key"]) > 0

    def test_discovered_templates_have_cog_metadata(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert "_cog_module" in tpl
            assert "_cog_name" in tpl
            assert "_cog_category" in tpl
            assert tpl.get("source") == "cog"

    def test_discovered_templates_have_required_fields(self):
        from bot.cogs.registry import discover_embed_templates
        result = discover_embed_templates()
        for tpl in result:
            assert "title" in tpl
            assert "description" in tpl
            assert "color" in tpl
