"""Tests for config.settings — settings loading and validation."""

from __future__ import annotations

from config.settings import Settings, get_settings


class TestSettings:
    """Tests for the Settings class."""

    def test_get_settings_returns_instance(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_is_cached(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_settings_has_jwt_secret(self):
        s = get_settings()
        assert s.jwt_secret

    def test_settings_has_auth_pepper(self):
        s = get_settings()
        assert s.auth_pepper

    def test_settings_has_database_url(self):
        s = get_settings()
        assert s.database_url

    def test_settings_db_kind_sqlite(self):
        s = get_settings()
        assert s.db_kind == "sqlite"

    def test_settings_redis_disabled_by_default_in_tests(self):
        s = get_settings()
        assert s.redis_enabled is False

    def test_settings_access_token_ttl_positive(self):
        s = get_settings()
        assert s.access_token_ttl_minutes > 0
