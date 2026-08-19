"""Tests for server config partial update bug (regression test).

Bug: PUT /api/v1/servers/{id}/config resets all fields to defaults
when they are not provided in the payload. This is because the endpoint
always sets ALL fields from the `allowed` dict, even if the payload
doesn't contain them.
"""

from __future__ import annotations

import pytest
import uuid
from datetime import UTC, datetime

from bot.database.models.server.server import Server
from bot.database.models.server.server_config import ServerConfig


@pytest.fixture
async def test_server(configured_db, db_sessionmaker):
    """Create a test server with config in the DB."""
    server_id = 123456789
    async with db_sessionmaker() as s:
        server = Server(
            id=server_id,
            name="Test Server",
            icon_hash="abc",
            member_count=100,
            is_active=True,
        )
        s.add(server)
        cfg = ServerConfig(
            server_id=server_id,
            prefix="!",
            locale="en",
            mod_log_channel_id=111,
            mute_role_id=222,
            welcome_channel_id=333,
            ticket_category_id=444,
            ticket_support_role_ids=[555, 666],
            ticket_auto_close_hours=48,
            music_dj_role_id=777,
            extras={"custom_key": "custom_value"},
        )
        s.add(cfg)
        await s.commit()

    return server_id


class TestServerConfigPartialUpdate:
    """Regression test for partial update bug."""

    async def test_partial_update_preserves_other_fields(self, auth_client, test_server):
        """Updating only `locale` should NOT reset prefix, channels, etc."""
        # Get current config
        resp = await auth_client.get(f"/api/v1/servers/{test_server}/config")
        assert resp.status_code == 200
        original = resp.json()

        # Update only locale
        resp = await auth_client.put(f"/api/v1/servers/{test_server}/config", json={
            "locale": "de",
        })
        assert resp.status_code == 200

        # Get updated config
        resp = await auth_client.get(f"/api/v1/servers/{test_server}/config")
        assert resp.status_code == 200
        updated = resp.json()

        # locale should be changed
        assert updated["locale"] == "de"

        # All other fields should be preserved (BUG: currently they get reset)
        assert updated["prefix"] == original["prefix"], \
            f"prefix was reset from '{original['prefix']}' to '{updated['prefix']}'"
        assert updated["mod_log_channel_id"] == original["mod_log_channel_id"]
        assert updated["mute_role_id"] == original["mute_role_id"]
        assert updated["welcome_channel_id"] == original["welcome_channel_id"]
        assert updated["ticket_category_id"] == original["ticket_category_id"]
        assert updated["ticket_support_role_ids"] == original["ticket_support_role_ids"]
        assert updated["ticket_auto_close_hours"] == original["ticket_auto_close_hours"]
        assert updated["music_dj_role_id"] == original["music_dj_role_id"]
