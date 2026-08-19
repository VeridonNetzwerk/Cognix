"""Tests for authentication: login, logout, refresh, me, setup gate."""

from __future__ import annotations

import pytest


class TestLogin:
    """POST /api/v1/auth/login"""

    async def test_login_success(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "test-password-123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user" in data
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "ADMIN"
        # Cookies should be set
        assert "cognix_access" in resp.cookies
        assert "cognix_refresh" in resp.cookies

    async def test_login_wrong_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "wrong-password",
        })
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "ghost",
            "password": "whatever",
        })
        assert resp.status_code == 401

    async def test_login_empty_username(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "",
            "password": "test-password-123",
        })
        assert resp.status_code == 422  # validation error

    async def test_login_missing_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
        })
        assert resp.status_code == 422

    async def test_login_remember_me(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "test-password-123",
            "remember_me": True,
        })
        assert resp.status_code == 200
        assert "cognix_access" in resp.cookies


class TestLogout:
    """POST /api/v1/auth/logout"""

    async def test_logout_success(self, auth_client):
        resp = await auth_client.post("/api/v1/auth/logout")
        assert resp.status_code == 200

    async def test_logout_without_auth(self, client):
        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 401


class TestMe:
    """GET /api/v1/auth/me"""

    async def test_me_success(self, auth_client):
        resp = await auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "ADMIN"
        assert "id" in data

    async def test_me_without_auth(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestRefresh:
    """POST /api/v1/auth/refresh"""

    async def test_refresh_success(self, client):
        # Login first
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "test-password-123",
        })
        assert resp.status_code == 200

        # Refresh
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200
        assert "ok" in resp.json()

    async def test_refresh_without_cookie(self, client):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401


class TestAuthHealth:
    """GET /api/v1/auth/health"""

    async def test_health(self, client):
        resp = await client.get("/api/v1/auth/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestSetupGate:
    """Setup gate middleware blocks unconfigured systems."""

    async def test_unconfigured_blocks_api(self, unconfigured_client):
        resp = await unconfigured_client.get("/api/v1/auth/me")
        assert resp.status_code == 423
        assert resp.json()["error"] == "setup_required"

    async def test_unconfigured_allows_setup_status(self, unconfigured_client):
        resp = await unconfigured_client.get("/api/v1/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False

    async def test_unconfigured_allows_health(self, unconfigured_client):
        resp = await unconfigured_client.get("/health")
        assert resp.status_code == 200

    async def test_unconfigured_allows_auth_health(self, unconfigured_client):
        resp = await unconfigured_client.get("/api/v1/auth/health")
        assert resp.status_code == 200

    async def test_configured_allows_api(self, auth_client):
        resp = await auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 200


class TestSetupStatus:
    """GET /api/v1/setup/status"""

    async def test_setup_status_configured(self, client):
        resp = await client.get("/api/v1/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["has_admin"] is True
