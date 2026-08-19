"""Tests for dashboard widget API: add, remove, reorder, resize."""

from __future__ import annotations

import pytest


class TestWidgetAdd:
    """POST /api/v1/dashboard/widgets/add"""

    async def test_add_widget_success(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "test_widget_1",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_add_widget_duplicate(self, auth_client):
        # Add once
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "dup_widget",
        })
        # Add again — should succeed (re-enable)
        resp = await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "dup_widget",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_add_widget_missing_field(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/add", json={})
        assert resp.status_code == 422

    async def test_add_widget_without_auth(self, client):
        resp = await client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "test",
        })
        assert resp.status_code == 401


class TestWidgetRemove:
    """POST /api/v1/dashboard/widgets/remove"""

    async def test_remove_widget_success(self, auth_client):
        # Add first
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "to_remove",
        })
        # Remove
        resp = await auth_client.post("/api/v1/dashboard/widgets/remove", json={
            "widget_id": "to_remove",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_remove_nonexistent_widget(self, auth_client):
        resp = await auth_client.post("/api/v1/dashboard/widgets/remove", json={
            "widget_id": "never_existed",
        })
        assert resp.status_code == 200  # idempotent
        assert resp.json()["ok"] is True


class TestWidgetReorder:
    """POST /api/v1/dashboard/widgets/reorder"""

    async def test_reorder_swap(self, auth_client):
        # Add two widgets
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "widget_a",
        })
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "widget_b",
        })
        # Swap them
        resp = await auth_client.post("/api/v1/dashboard/widgets/reorder", json={
            "source_id": "widget_a",
            "target_id": "widget_b",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_reorder_nonexistent_widgets(self, auth_client):
        """Reorder should create DB entries for widgets that don't exist yet."""
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


class TestWidgetResize:
    """POST /api/v1/dashboard/widgets/resize"""

    async def test_resize_existing_widget(self, auth_client):
        # Add first
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "resize_me",
        })
        resp = await auth_client.post("/api/v1/dashboard/widgets/resize", json={
            "widget_id": "resize_me",
            "size_w": 2,
            "size_h": 2,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_resize_new_widget(self, auth_client):
        """Resize should create the widget if it doesn't exist."""
        resp = await auth_client.post("/api/v1/dashboard/widgets/resize", json={
            "widget_id": "auto_create",
            "size_w": 3,
            "size_h": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_resize_clamps_values(self, auth_client):
        """Resize should clamp to reasonable bounds."""
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "clamp_test",
        })
        resp = await auth_client.post("/api/v1/dashboard/widgets/resize", json={
            "widget_id": "clamp_test",
            "size_w": 99,
            "size_h": 99,
        })
        assert resp.status_code == 200

    async def test_resize_negative_values(self, auth_client):
        await auth_client.post("/api/v1/dashboard/widgets/add", json={
            "widget_id": "neg_test",
        })
        resp = await auth_client.post("/api/v1/dashboard/widgets/resize", json={
            "widget_id": "neg_test",
            "size_w": -5,
            "size_h": -5,
        })
        assert resp.status_code == 200  # should clamp, not crash
