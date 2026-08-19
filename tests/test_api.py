"""Tests for server config, stats, users, moderation, settings, web-users, embeds."""

from __future__ import annotations

import pytest
import uuid


class TestServerConfig:
    """Server config endpoints."""

    async def test_list_servers_empty(self, auth_client):
        resp = await auth_client.get("/api/v1/servers/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_config_not_found(self, auth_client):
        resp = await auth_client.get("/api/v1/servers/999/config")
        assert resp.status_code == 404

    async def test_update_config_not_found(self, auth_client):
        resp = await auth_client.put("/api/v1/servers/999/config", json={
            "prefix": "!",
        })
        assert resp.status_code == 404

    async def test_list_servers_without_auth(self, client):
        resp = await client.get("/api/v1/servers/")
        assert resp.status_code == 401


class TestStats:
    """GET /api/v1/stats/overview"""

    async def test_stats_overview(self, auth_client):
        resp = await auth_client.get("/api/v1/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "series" in data
        assert isinstance(data["series"], list)

    async def test_stats_with_days_param(self, auth_client):
        resp = await auth_client.get("/api/v1/stats/overview?days=7")
        assert resp.status_code == 200

    async def test_stats_without_auth(self, client):
        resp = await client.get("/api/v1/stats/overview")
        assert resp.status_code == 401


class TestSettings:
    """Settings endpoints."""

    async def test_get_settings(self, auth_client):
        resp = await auth_client.get("/api/v1/settings/")
        assert resp.status_code == 200
        data = resp.json()
        assert "bot_application_id" in data
        assert "bot_token_set" in data
        assert "music_enabled" in data

    async def test_patch_settings_partial(self, auth_client):
        """Partial update should only change the provided field."""
        # Get current settings
        resp = await auth_client.get("/api/v1/settings/")
        assert resp.status_code == 200
        original = resp.json()

        # Update only bot_description
        resp = await auth_client.patch("/api/v1/settings/", json={
            "bot_description": "Updated description",
        })
        assert resp.status_code == 200

        # Verify only bot_description changed
        resp = await auth_client.get("/api/v1/settings/")
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["bot_description"] == "Updated description"
        # Other fields should be unchanged
        assert updated["bot_status_text"] == original["bot_status_text"]
        assert updated["bot_status_type"] == original["bot_status_type"]
        assert updated["music_enabled"] == original["music_enabled"]

    async def test_get_settings_without_auth(self, client):
        resp = await client.get("/api/v1/settings/")
        assert resp.status_code == 401


class TestWebUsers:
    """Web user management (admin only)."""

    async def test_list_users(self, auth_client):
        resp = await auth_client.get("/api/v1/web-users")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(u["username"] == "admin" for u in data)

    async def test_create_user(self, auth_client):
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "newuser",
            "email": "new@example.com",
            "password": "newuser-password-123",
            "role": "VIEWER",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "VIEWER"

    async def test_create_duplicate_user(self, auth_client):
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "admin",
            "password": "some-password-123",
            "role": "VIEWER",
        })
        assert resp.status_code == 409

    async def test_create_user_short_password(self, auth_client):
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "shortpw",
            "password": "short",
            "role": "VIEWER",
        })
        assert resp.status_code == 422

    async def test_update_user_role(self, auth_client):
        # Create a user first
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "rolechange",
            "password": "some-password-123",
            "role": "VIEWER",
        })
        assert resp.status_code == 201
        user_id = resp.json()["id"]

        # Update role
        resp = await auth_client.patch(f"/api/v1/web-users/{user_id}", json={
            "role": "MODERATOR",
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "MODERATOR"

    async def test_cannot_demote_self(self, auth_client):
        """Admin cannot demote themselves."""
        resp = await auth_client.get("/api/v1/web-users")
        admin_id = next(u["id"] for u in resp.json() if u["username"] == "admin")

        resp = await auth_client.patch(f"/api/v1/web-users/{admin_id}", json={
            "role": "VIEWER",
        })
        assert resp.status_code == 400

    async def test_cannot_deactivate_self(self, auth_client):
        resp = await auth_client.get("/api/v1/web-users")
        admin_id = next(u["id"] for u in resp.json() if u["username"] == "admin")

        resp = await auth_client.patch(f"/api/v1/web-users/{admin_id}", json={
            "is_active": False,
        })
        assert resp.status_code == 400

    async def test_cannot_delete_self(self, auth_client):
        resp = await auth_client.get("/api/v1/web-users")
        admin_id = next(u["id"] for u in resp.json() if u["username"] == "admin")

        resp = await auth_client.delete(f"/api/v1/web-users/{admin_id}")
        assert resp.status_code == 400

    async def test_delete_user(self, auth_client):
        # Create a user
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "todelete",
            "password": "some-password-123",
            "role": "VIEWER",
        })
        assert resp.status_code == 201
        user_id = resp.json()["id"]

        # Delete
        resp = await auth_client.delete(f"/api/v1/web-users/{user_id}")
        assert resp.status_code == 204

    async def test_reset_password(self, auth_client):
        # Create a user
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "pwreset",
            "password": "original-password-123",
            "role": "VIEWER",
        })
        user_id = resp.json()["id"]

        # Reset password
        resp = await auth_client.post(f"/api/v1/web-users/{user_id}/password", json={
            "new_password": "new-password-123",
        })
        assert resp.status_code == 204

    async def test_disable_2fa(self, auth_client):
        resp = await auth_client.post("/api/v1/web-users", json={
            "username": "twofa",
            "password": "some-password-123",
            "role": "VIEWER",
        })
        user_id = resp.json()["id"]

        resp = await auth_client.post(f"/api/v1/web-users/{user_id}/disable-2fa")
        assert resp.status_code == 204

    async def test_list_users_mod_forbidden(self, mod_client):
        """Moderators cannot list web users (admin only)."""
        resp = await mod_client.get("/api/v1/web-users")
        assert resp.status_code == 403


class TestEmbedTemplates:
    """Embed template CRUD."""

    async def test_list_templates(self, auth_client):
        resp = await auth_client.get("/api/v1/embeds")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_template(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "test_embed",
            "title": "Test Embed",
            "description": "A test embed",
            "color": 0xFF0000,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"] == "test_embed"
        assert data["title"] == "Test Embed"

    async def test_create_duplicate_template(self, auth_client):
        await auth_client.post("/api/v1/embeds", json={
            "key": "dup_embed",
        })
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "dup_embed",
        })
        assert resp.status_code == 409

    async def test_get_template(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "get_test",
        })
        tpl_id = resp.json()["id"]

        resp = await auth_client.get(f"/api/v1/embeds/{tpl_id}")
        assert resp.status_code == 200
        assert resp.json()["key"] == "get_test"

    async def test_get_template_not_found(self, auth_client):
        resp = await auth_client.get("/api/v1/embeds/99999")
        assert resp.status_code == 404

    async def test_update_template(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "update_test",
            "title": "Before",
        })
        tpl_id = resp.json()["id"]

        resp = await auth_client.patch(f"/api/v1/embeds/{tpl_id}", json={
            "key": "update_test",
            "title": "After",
        })
        assert resp.status_code == 200
        assert resp.json()["title"] == "After"

    async def test_delete_template(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "delete_test",
        })
        tpl_id = resp.json()["id"]

        resp = await auth_client.delete(f"/api/v1/embeds/{tpl_id}")
        assert resp.status_code == 204

    async def test_delete_template_not_found(self, auth_client):
        resp = await auth_client.delete("/api/v1/embeds/99999")
        assert resp.status_code == 404


class TestAuditLog:
    """GET /api/v1/audit"""

    async def test_list_audit(self, auth_client):
        resp = await auth_client.get("/api/v1/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_audit_with_limit(self, auth_client):
        resp = await auth_client.get("/api/v1/audit?limit=5")
        assert resp.status_code == 200

    async def test_list_audit_mod_forbidden(self, mod_client):
        resp = await mod_client.get("/api/v1/audit")
        assert resp.status_code == 403


class TestBotStatus:
    """GET /api/v1/bot/status"""

    async def test_bot_status(self, auth_client):
        resp = await auth_client.get("/api/v1/bot/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "online" in data
        assert "guild_count" in data
        assert "version" in data

    async def test_bot_status_mod_forbidden(self, mod_client):
        """Moderators cannot access bot control (admin only)."""
        resp = await mod_client.get("/api/v1/bot/status")
        assert resp.status_code == 403


class TestRoleGuard:
    """Verify role-based access control."""

    async def test_mod_can_access_servers(self, mod_client):
        resp = await mod_client.get("/api/v1/servers/")
        assert resp.status_code == 200

    async def test_mod_can_access_stats(self, mod_client):
        resp = await mod_client.get("/api/v1/stats/overview")
        assert resp.status_code == 200

    async def test_mod_can_access_users(self, mod_client):
        resp = await mod_client.get("/api/v1/users/")
        assert resp.status_code == 200

    async def test_mod_cannot_access_settings(self, mod_client):
        resp = await mod_client.get("/api/v1/settings/")
        assert resp.status_code == 403

    async def test_mod_cannot_access_backups(self, mod_client):
        resp = await mod_client.get("/api/v1/backups/")
        assert resp.status_code == 403

    async def test_unauthenticated_blocked_everywhere(self, client):
        endpoints = [
            ("/api/v1/servers/", "GET"),
            ("/api/v1/stats/overview", "GET"),
            ("/api/v1/settings/", "GET"),
            ("/api/v1/bot/status", "GET"),
            ("/api/v1/web-users", "GET"),
            ("/api/v1/audit", "GET"),
            ("/api/v1/dashboard/widgets/add", "POST"),
        ]
        for path, method in endpoints:
            if method == "GET":
                resp = await client.get(path)
            else:
                resp = await client.post(path, json={})
            assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"
