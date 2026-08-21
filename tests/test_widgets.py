"""Tests for dashboard widget data loading — load_widget_data.

Tests:
- leveling_top returns top_members list
- leveling_stats returns total_users and total_messages
- moderation_recent returns moderation_recent list
- tickets_open returns tickets_open list
- giveaways_active returns giveaways_active list
- activity_recent returns activity_recent list
- welcome_recent returns welcome_recent list
- stats_overview returns stats fields
- music widgets return placeholder data
- recent_audit returns recent_audit list
- unknown widget id returns no data
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from bot.dashboard.widgets import load_widget_data


class TestLoadWidgetDataLeveling:
    """Leveling widget data loading."""

    async def test_leveling_top_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["leveling_top"])
            assert "leveling_top" in data
            assert data["leveling_top"]["top_members"] == []

    async def test_leveling_top_with_data(self, db_sessionmaker):
        from bot.database.models.leveling.leveling import LevelingUser
        async with db_sessionmaker() as s:
            s.add(LevelingUser(server_id=1, user_id=100, xp=500, level=5, messages=50))
            s.add(LevelingUser(server_id=1, user_id=200, xp=300, level=3, messages=30))
            s.add(LevelingUser(server_id=1, user_id=300, xp=100, level=1, messages=10))
            await s.commit()

        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["leveling_top"])
            members = data["leveling_top"]["top_members"]
            assert len(members) == 3
            assert members[0]["xp"] == 500
            assert members[0]["level"] == 5

    async def test_leveling_stats_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["leveling_stats"])
            assert data["leveling_stats"]["total_users"] == 0
            assert data["leveling_stats"]["total_messages"] == 0

    async def test_leveling_stats_with_data(self, db_sessionmaker):
        from bot.database.models.leveling.leveling import LevelingUser
        async with db_sessionmaker() as s:
            s.add(LevelingUser(server_id=1, user_id=100, xp=500, level=5, messages=50))
            s.add(LevelingUser(server_id=1, user_id=200, xp=300, level=3, messages=30))
            await s.commit()

        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["leveling_stats"])
            assert data["leveling_stats"]["total_users"] == 2
            assert data["leveling_stats"]["total_messages"] == 80


class TestLoadWidgetDataCore:
    """Core widget data loading."""

    async def test_moderation_recent_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["moderation_recent"])
            assert "moderation_recent" in data
            assert data["moderation_recent"]["moderation_recent"] == []

    async def test_tickets_open_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["tickets_open"])
            assert "tickets_open" in data
            assert data["tickets_open"]["tickets_open"] == []
            assert data["tickets_open"]["tickets_open_count"] == 0

    async def test_giveaways_active_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["giveaways_active"])
            assert "giveaways_active" in data
            assert data["giveaways_active"]["giveaways_active"] == []

    async def test_activity_recent_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["activity_recent"])
            assert "activity_recent" in data
            assert data["activity_recent"]["activity_recent"] == []

    async def test_welcome_recent_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["welcome_recent"])
            assert "welcome_recent" in data
            assert data["welcome_recent"]["welcome_recent"] == []

    async def test_stats_overview(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["stats_overview"])
            assert "stats_overview" in data
            d = data["stats_overview"]
            assert "stats_messages" in d
            assert "stats_commands" in d
            assert "stats_joins" in d
            assert "stats_leaves" in d

    async def test_music_now_playing(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["music_now_playing"])
            assert "music_now_playing" in data
            assert data["music_now_playing"]["music_now_playing"] is None

    async def test_music_queue(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["music_queue"])
            assert "music_queue" in data
            assert data["music_queue"]["music_queue"] == []

    async def test_recent_audit_empty(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["recent_audit"])
            assert "recent_audit" in data
            assert data["recent_audit"]["recent_audit"] == []

    async def test_unknown_widget(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, ["nonexistent_widget"])
            assert "nonexistent_widget" not in data

    async def test_multiple_widgets(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            data = await load_widget_data(s, [
                "leveling_top", "leveling_stats", "moderation_recent"
            ])
            assert "leveling_top" in data
            assert "leveling_stats" in data
            assert "moderation_recent" in data
