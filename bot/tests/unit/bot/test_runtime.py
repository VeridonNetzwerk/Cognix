"""Tests for bot.runtime — bot info, cog state cache, lifecycle control."""

from __future__ import annotations

from bot.runtime import (
    _format_uptime,
    get_bot_info,
    invalidate_cog_state_cache,
    is_bot_paused,
    request_bot_start,
    set_bot_paused,
)


class TestFormatUptime:
    """Tests for _format_uptime()."""

    def test_zero_seconds(self):
        assert _format_uptime(0) == "0s"

    def test_seconds_only(self):
        assert _format_uptime(5) == "5s"

    def test_minutes_and_seconds(self):
        assert _format_uptime(65) == "1m 5s"

    def test_hours_minutes_seconds(self):
        assert _format_uptime(3661) == "1h 1m 1s"

    def test_days_hours_minutes_seconds(self):
        assert _format_uptime(90061) == "1d 1h 1m 1s"

    def test_negative_clamped_to_zero(self):
        assert _format_uptime(-10) == "0s"


class TestGetBotInfo:
    """Tests for get_bot_info() — must return a dict, not None."""

    def test_returns_dict_when_no_bot(self):
        """When no bot is set, should return default dict with name 'CogniX'."""
        info = get_bot_info()
        assert isinstance(info, dict), "get_bot_info() should return a dict, not None"
        assert "name" in info
        assert info["name"] == "CogniX"
        assert info["online"] is False
        assert info["guild_count"] == 0

    def test_returns_all_required_keys(self):
        info = get_bot_info()
        required_keys = {
            "name", "username", "id", "avatar_url", "online",
            "uptime", "uptime_seconds", "latency_ms",
            "guild_count", "user_count", "version", "footer",
        }
        assert required_keys.issubset(info.keys()), f"Missing keys: {required_keys - info.keys()}"


class TestCogStateCache:
    """Tests for the cog state cache invalidation."""

    def test_invalidate_all(self):
        invalidate_cog_state_cache()
        # Should not raise

    def test_invalidate_specific(self):
        invalidate_cog_state_cache(server_id=123, cog_name="moderation")
        # Should not raise


class TestBotLifecycle:
    """Tests for bot lifecycle control flags."""

    def test_pause_and_unpause(self):
        set_bot_paused(True)
        assert is_bot_paused() is True
        request_bot_start()
        assert is_bot_paused() is False
