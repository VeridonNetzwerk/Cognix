"""Tests for web API routes — embeds CRUD, leveling save, welcome save, dashboard.

Tests:
- Embed template CRUD (list, get, create, update, delete) via API
- Embed template seeding via API on startup
- Leveling settings save and retrieve
- Welcome settings save
- Dashboard widget data loading (leveling_top, leveling_stats)
- Bot status requires admin
- Widget reorder endpoint
"""

from __future__ import annotations

import pytest


class TestEmbedTemplateAPI:
    """Embed template CRUD via /api/v1/embeds."""

    async def test_list_templates(self, auth_client):
        resp = await auth_client.get("/api/v1/embeds")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_create_template(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "test_custom",
            "title": "Test Template",
            "description": "A test description",
            "color": 0xFF0000,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"] == "test_custom"
        assert data["title"] == "Test Template"
        assert data["footer_text"] == "Powered by Cognix · Made by 食べ物"

    async def test_create_duplicate_template(self, auth_client):
        await auth_client.post("/api/v1/embeds", json={
            "key": "dup_test",
            "title": "First",
        })
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "dup_test",
            "title": "Second",
        })
        assert resp.status_code == 409

    async def test_get_template(self, auth_client):
        create = await auth_client.post("/api/v1/embeds", json={
            "key": "get_test",
            "title": "Get Me",
        })
        tpl_id = create.json()["id"]
        resp = await auth_client.get(f"/api/v1/embeds/{tpl_id}")
        assert resp.status_code == 200
        assert resp.json()["key"] == "get_test"

    async def test_get_template_not_found(self, auth_client):
        resp = await auth_client.get("/api/v1/embeds/99999")
        assert resp.status_code == 404

    async def test_update_template(self, auth_client):
        create = await auth_client.post("/api/v1/embeds", json={
            "key": "update_test",
            "title": "Before",
        })
        tpl_id = create.json()["id"]
        resp = await auth_client.patch(f"/api/v1/embeds/{tpl_id}", json={
            "key": "update_test",
            "title": "After",
        })
        assert resp.status_code == 200
        assert resp.json()["title"] == "After"

    async def test_update_template_not_found(self, auth_client):
        resp = await auth_client.patch("/api/v1/embeds/99999", json={
            "key": "nope",
            "title": "Nope",
        })
        assert resp.status_code == 404

    async def test_delete_template(self, auth_client):
        create = await auth_client.post("/api/v1/embeds", json={
            "key": "delete_test",
            "title": "Delete Me",
        })
        tpl_id = create.json()["id"]
        resp = await auth_client.delete(f"/api/v1/embeds/{tpl_id}")
        assert resp.status_code == 204

    async def test_delete_template_not_found(self, auth_client):
        resp = await auth_client.delete("/api/v1/embeds/99999")
        assert resp.status_code == 404

    async def test_embeds_require_mod(self, client):
        resp = await client.get("/api/v1/embeds")
        assert resp.status_code == 401

    async def test_create_with_fields(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "fields_test",
            "title": "With Fields",
            "fields": [
                {"name": "Field 1", "value": "Value 1", "inline": True},
                {"name": "Field 2", "value": "Value 2", "inline": False},
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["fields"]) == 2
        assert data["fields"][0]["name"] == "Field 1"

    async def test_create_with_extras(self, auth_client):
        resp = await auth_client.post("/api/v1/embeds", json={
            "key": "extras_test",
            "title": "With Extras",
            "extras": {"custom_key": "custom_value", "button_label": "Click"},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["extras"]["custom_key"] == "custom_value"


class TestDashboardWidgetData:
    """Dashboard widget data loading for leveling widgets."""

    async def test_widget_refresh_returns_data(self, auth_client):
        """Add a core widget and verify refresh returns data."""
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "bot_status",
        })
        resp = await auth_client.get("/api/v1/dashboard/widgets/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert "widgets" in data
        # bot_status is a core widget, should always be available
        assert "bot_status" in data["widgets"]

    async def test_widget_add_leveling_top(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "leveling_top",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestDashboardReorder:
    """POST /api/v1/dashboard/widgets/reorder — regression tests."""

    async def test_reorder_swap(self, auth_client):
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "reorder_a",
        })
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "reorder_b",
        })
        resp = await auth_client.post("/api/v1/dashboard/widgets/reorder", json={
            "source_id": "reorder_a",
            "target_id": "reorder_b",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_reorder_nonexistent_widgets(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/reorder", json={
            "source_id": "new_source",
            "target_id": "new_target",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_reorder_missing_fields(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/reorder", json={
            "source_id": "only_source",
        })
        assert resp.status_code == 422

    async def test_reorder_without_auth(self, client):
        resp = await client.post("/api/v1/dashboard/widgets/reorder", json={
            "source_id": "a",
            "target_id": "b",
        })
        assert resp.status_code == 401


class TestBotStatusSecurity:
    """Bot status endpoint security — regression tests."""

    async def test_bot_status_requires_admin(self, mod_client):
        """Moderators cannot access bot status (admin only)."""
        resp = await mod_client.get("/api/v1/bot/status")
        assert resp.status_code == 403

    async def test_bot_status_requires_auth(self, client):
        """Unauthenticated users cannot access bot status."""
        resp = await client.get("/api/v1/bot/status")
        assert resp.status_code == 401

    async def test_bot_status_admin_ok(self, auth_client):
        """Admins can access bot status."""
        resp = await auth_client.get("/api/v1/bot/status")
        assert resp.status_code == 200
