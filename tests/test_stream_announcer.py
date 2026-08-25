"""Tests for the Stream Announcer cog — models, platform detection, formatting.

Tests:
- StreamAnnouncerConfig defaults
- StreamSession creation and fields
- _detect_platform for twitch, youtube, custom
- _format_message placeholder replacement
- _build_announce_embed structure
- _is_tracked filtering logic (bots, platforms, roles)
- EMBED_TEMPLATES and COG_INFO declarations
- Widget data loading for stream_live
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from bot.database.models.stream_announcer.stream_announcer import (
    StreamAnnouncerConfig,
    StreamSession,
)


class TestStreamAnnouncerConfigModel:
    """StreamAnnouncerConfig defaults and creation."""

    async def test_create_config_with_defaults(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            cfg = StreamAnnouncerConfig(server_id=12345)
            s.add(cfg)
            await s.commit()

            loaded = await s.get(StreamAnnouncerConfig, 12345)
            assert loaded is not None
            assert loaded.enabled is False
            assert loaded.announce_channel_id is None
            assert loaded.tracked_platforms == []
            assert loaded.tracked_roles == []
            assert loaded.ignored_roles == []
            assert loaded.streaming_role_id is None
            assert loaded.delete_on_end is False
            assert loaded.ping_role_id is None
            assert loaded.cooldown_minutes == 60

    async def test_config_primary_key_is_server_id(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            cfg = StreamAnnouncerConfig(server_id=99999)
            s.add(cfg)
            await s.commit()

            loaded = await s.get(StreamAnnouncerConfig, 99999)
            assert loaded is not None
            assert loaded.server_id == 99999

    async def test_config_default_message(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            cfg = StreamAnnouncerConfig(server_id=11111)
            s.add(cfg)
            await s.commit()

            loaded = await s.get(StreamAnnouncerConfig, 11111)
            assert loaded is not None
            assert "{user.name}" in loaded.announce_message
            assert "{stream_title}" in loaded.announce_message
            assert "{stream_url}" in loaded.announce_message


class TestStreamSessionModel:
    """StreamSession creation and fields."""

    async def test_create_session(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            now = int(time.time())
            session = StreamSession(
                server_id=123,
                user_id=456,
                platform="twitch",
                stream_url="https://twitch.tv/test",
                stream_title="Test Stream",
                game="Just Chatting",
                announce_message_id=789,
                is_active=True,
                started_at=now,
            )
            s.add(session)
            await s.commit()

            loaded = await s.scalar(
                select(StreamSession).where(
                    StreamSession.server_id == 123,
                    StreamSession.user_id == 456,
                )
            )
            assert loaded is not None
            assert loaded.platform == "twitch"
            assert loaded.stream_url == "https://twitch.tv/test"
            assert loaded.stream_title == "Test Stream"
            assert loaded.game == "Just Chatting"
            assert loaded.is_active is True
            assert loaded.ended_at is None

    async def test_session_defaults(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            now = int(time.time())
            session = StreamSession(
                server_id=100,
                user_id=200,
                started_at=now,
            )
            s.add(session)
            await s.commit()

            loaded = await s.scalar(
                select(StreamSession).where(
                    StreamSession.server_id == 100,
                    StreamSession.user_id == 200,
                )
            )
            assert loaded is not None
            assert loaded.platform == "twitch"
            assert loaded.stream_url == ""
            assert loaded.stream_title == ""
            assert loaded.game == ""
            assert loaded.is_active is True
            assert loaded.announce_message_id is None
            assert loaded.ended_at is None


class TestDetectPlatform:
    """_detect_platform() correctly identifies streaming platforms."""

    def _make_activity(self, url="", name=""):
        class FakeStreaming:
            pass
        a = FakeStreaming()
        a.url = url
        a.name = name
        return a

    def test_detect_twitch_url(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(url="https://twitch.tv/streamer")
        assert _detect_platform(activity) == "twitch"

    def test_detect_twitch_name(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(name="Twitch")
        assert _detect_platform(activity) == "twitch"

    def test_detect_youtube_url(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(url="https://youtube.com/watch?v=abc")
        assert _detect_platform(activity) == "youtube"

    def test_detect_youtube_short_url(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(url="https://youtu.be/abc")
        assert _detect_platform(activity) == "youtube"

    def test_detect_youtube_name(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(name="YouTube")
        assert _detect_platform(activity) == "youtube"

    def test_detect_custom_url(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity(url="https://example.com/stream")
        assert _detect_platform(activity) == "custom"

    def test_detect_empty(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _detect_platform
        activity = self._make_activity()
        assert _detect_platform(activity) == "custom"


class TestFormatMessage:
    """_format_message() placeholder replacement."""

    def _make_member(self):
        class FakeGuild:
            name = "TestGuild"
            member_count = 100
        class FakeMember:
            mention = "<@123>"
            display_name = "TestUser"
            id = 123
            guild = FakeGuild()
        return FakeMember(), FakeGuild()

    def _make_activity(self):
        class FakeStreaming:
            url = "https://twitch.tv/test"
            name = "My Cool Stream"
            game = "Minecraft"
        return FakeStreaming()

    def test_format_user_mention(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        assert _format_message("Watch {user.mention}!", m, a, g) == "Watch <@123>!"

    def test_format_user_name(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        assert _format_message("Streaming: {user.name}", m, a, g) == "Streaming: TestUser"

    def test_format_stream_url(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        result = _format_message("URL: {stream_url}", m, a, g)
        assert result == "URL: https://twitch.tv/test"

    def test_format_stream_title(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        result = _format_message("Title: {stream_title}", m, a, g)
        assert result == "Title: My Cool Stream"

    def test_format_game(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        result = _format_message("Playing: {game}", m, a, g)
        assert result == "Playing: Minecraft"

    def test_format_guild_name(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        result = _format_message("In {guild.name}", m, a, g)
        assert result == "In TestGuild"

    def test_format_multiple_placeholders(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        result = _format_message(
            "{user.mention} is streaming {stream_title} at {stream_url} in {guild.name}",
            m, a, g,
        )
        assert result == "<@123> is streaming My Cool Stream at https://twitch.tv/test in TestGuild"

    def test_format_empty_string(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        assert _format_message("", m, a, g) == ""

    def test_format_non_string_input(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        assert _format_message(None, m, a, g) == ""
        assert _format_message(123, m, a, g) == ""

    def test_format_no_placeholders(self):
        from cogs_store.dev.stream_announcer.stream_announcer import _format_message
        m, g = self._make_member()
        a = self._make_activity()
        assert _format_message("Just text", m, a, g) == "Just text"


class TestIsTracked:
    """_is_tracked() filtering logic."""

    def _make_cfg(self, tracked_platforms=None, tracked_roles=None, ignored_roles=None):
        cfg = StreamAnnouncerConfig(server_id=1)
        cfg.tracked_platforms = tracked_platforms or []
        cfg.tracked_roles = tracked_roles or []
        cfg.ignored_roles = ignored_roles or []
        return cfg

    def _make_member(self, is_bot=False, role_ids=None):
        class FakeRole:
            def __init__(self, rid):
                self.id = rid
        class FakeMember:
            bot = is_bot
            roles = [FakeRole(rid) for rid in (role_ids or [])]
        return FakeMember()

    def test_tracks_everyone_by_default(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg()
        member = self._make_member()
        assert cog._is_tracked(cfg, member, "twitch") is True

    def test_skips_bots(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg()
        member = self._make_member(is_bot=True)
        assert cog._is_tracked(cfg, member, "twitch") is False

    def test_platform_filter_includes(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg(tracked_platforms=["twitch"])
        member = self._make_member()
        assert cog._is_tracked(cfg, member, "twitch") is True

    def test_platform_filter_excludes(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg(tracked_platforms=["twitch"])
        member = self._make_member()
        assert cog._is_tracked(cfg, member, "youtube") is False

    def test_ignored_roles_blocks(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg(ignored_roles=[999])
        member = self._make_member(role_ids=[999])
        assert cog._is_tracked(cfg, member, "twitch") is False

    def test_tracked_roles_includes(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg(tracked_roles=[100])
        member = self._make_member(role_ids=[100])
        assert cog._is_tracked(cfg, member, "twitch") is True

    def test_tracked_roles_excludes(self):
        from cogs_store.dev.stream_announcer.stream_announcer import StreamAnnouncer
        cog = StreamAnnouncer.__new__(StreamAnnouncer)
        cfg = self._make_cfg(tracked_roles=[100])
        member = self._make_member(role_ids=[200])
        assert cog._is_tracked(cfg, member, "twitch") is False


class TestStreamAnnouncerDeclarations:
    """COG_INFO, EMBED_TEMPLATES, WIDGETS structure."""

    def test_cog_info(self):
        from cogs_store.dev.stream_announcer.stream_announcer import COG_INFO
        assert COG_INFO["name"] == "Stream Announcer"
        assert COG_INFO["category"] == "Utility"
        assert "version" in COG_INFO

    def test_embed_templates_count(self):
        from cogs_store.dev.stream_announcer.stream_announcer import EMBED_TEMPLATES
        assert len(EMBED_TEMPLATES) == 2

    def test_embed_templates_keys(self):
        from cogs_store.dev.stream_announcer.stream_announcer import EMBED_TEMPLATES
        keys = [t["key"] for t in EMBED_TEMPLATES]
        assert "stream_announce" in keys
        assert "stream_end" in keys

    def test_embed_templates_have_required_fields(self):
        from cogs_store.dev.stream_announcer.stream_announcer import EMBED_TEMPLATES
        for tpl in EMBED_TEMPLATES:
            assert "key" in tpl
            assert "title" in tpl
            assert "description" in tpl
            assert "color" in tpl
            assert "footer_text" in tpl

    def test_widgets_declared(self):
        from cogs_store.dev.stream_announcer.stream_announcer import WIDGETS
        assert isinstance(WIDGETS, list)
        assert len(WIDGETS) == 1
        assert WIDGETS[0]["id"] == "stream_live"


class TestStreamWidgetData:
    """Widget data loading for stream_live."""

    async def test_stream_live_empty(self, db_sessionmaker):
        from bot.dashboard.widgets import load_widget_data
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["stream_live"])
            assert "stream_live" in data
            assert data["stream_live"]["live_streams"] == []

    async def test_stream_live_with_data(self, db_sessionmaker):
        from bot.dashboard.widgets import load_widget_data
        now = int(time.time())
        async with db_sessionmaker() as s:
            s.add(StreamSession(
                server_id=1, user_id=100, platform="twitch",
                stream_url="https://twitch.tv/test",
                stream_title="Test Stream", game="Minecraft",
                is_active=True, started_at=now,
            ))
            s.add(StreamSession(
                server_id=1, user_id=200, platform="youtube",
                stream_url="https://youtube.com/watch?v=abc",
                stream_title="YT Stream", game="Music",
                is_active=True, started_at=now,
            ))
            s.add(StreamSession(
                server_id=1, user_id=300, platform="twitch",
                stream_title="Old Stream",
                is_active=False, started_at=now - 3600, ended_at=now,
            ))
            await s.commit()

        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["stream_live"])
            streams = data["stream_live"]["live_streams"]
            assert len(streams) == 2
            assert streams[0]["stream_title"] in ("Test Stream", "YT Stream")
