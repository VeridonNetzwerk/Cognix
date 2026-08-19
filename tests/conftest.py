"""Shared test fixtures for CogniX web panel tests.

Uses an in-memory SQLite database and httpx ASGITransport for fast,
isolated test runs — no external services required.
"""

from __future__ import annotations

import base64
import secrets
import uuid
from datetime import UTC, datetime
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Patch settings BEFORE any other import touches get_settings()
import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests-only-32chars!")
os.environ.setdefault("AUTH_PEPPER", "test-pepper")
os.environ.setdefault("MASTER_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
os.environ.setdefault("DISCORD_BOT_TOKEN", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# Clear lru_cache so settings pick up our env vars
from bot.config.settings import get_settings  # noqa: E402
get_settings.cache_clear()

from bot.database.base import Base  # noqa: E402
from bot.database.models.auth.web_user import WebRole, WebUser  # noqa: E402
from bot.database.models.system.system_config import SystemConfig  # noqa: E402
from web.security.passwords import hash_password  # noqa: E402


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory engine for each test."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_sessionmaker(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(scope="function")
async def db_session(db_sessionmaker) -> AsyncIterator[AsyncSession]:
    """Yield a session that rolls back after each test."""
    session = db_sessionmaker()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()


@pytest_asyncio.fixture(scope="function")
async def configured_db(db_sessionmaker):
    """Insert a SystemConfig row marked as configured + an admin user.
    Returns (sessionmaker, admin_user)."""
    admin_id = uuid.uuid4()
    async with db_sessionmaker() as s:
        cfg = SystemConfig(
            id=1,
            configured=True,
            bot_token_encrypted="",
            bot_application_id="",
            bot_status_text="",
            bot_status_type="playing",
            bot_description="",
            google_oauth_enabled=False,
            music_enabled=False,
            registration_open=False,
            enabled_cogs={},
        )
        s.add(cfg)
        admin = WebUser(
            id=admin_id,
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("test-password-123"),
            role=WebRole.ADMIN,
            is_active=True,
            failed_login_count=0,
        )
        s.add(admin)
        await s.commit()

    return db_sessionmaker, admin_id


@pytest_asyncio.fixture(scope="function")
async def unconfigured_db(db_sessionmaker):
    """Insert a SystemConfig row marked as NOT configured."""
    async with db_sessionmaker() as s:
        cfg = SystemConfig(
            id=1,
            configured=False,
            bot_token_encrypted="",
            bot_application_id="",
            bot_status_text="",
            bot_status_type="playing",
            bot_description="",
            google_oauth_enabled=False,
            music_enabled=False,
            registration_open=False,
            enabled_cogs={},
        )
        s.add(cfg)
        await s.commit()

    return db_sessionmaker


@pytest_asyncio.fixture(scope="function")
async def app(configured_db):
    """Create a FastAPI app instance with patched DB session."""
    db_sessionmaker, _ = configured_db

    # Patch db_session to use our test sessionmaker
    import bot.database.session as session_mod

    original_sessionmaker = session_mod._sessionmaker
    original_engine = session_mod._engine
    session_mod._sessionmaker = db_sessionmaker
    session_mod._engine = True  # truthy so init_engine doesn't override

    # Invalidate setup gate cache
    from web.middleware.auth.setup_gate import SetupGateMiddleware
    SetupGateMiddleware.invalidate()

    from web.app import create_app
    app = create_app()

    yield app

    # Restore
    session_mod._sessionmaker = original_sessionmaker
    session_mod._engine = original_engine
    SetupGateMiddleware.invalidate()


@pytest_asyncio.fixture(scope="function")
async def unconfigured_app(unconfigured_db):
    """Create a FastAPI app with unconfigured system."""
    db_sessionmaker = unconfigured_db

    import bot.database.session as session_mod

    original_sessionmaker = session_mod._sessionmaker
    original_engine = session_mod._engine
    session_mod._sessionmaker = db_sessionmaker
    session_mod._engine = True

    from web.middleware.auth.setup_gate import SetupGateMiddleware
    SetupGateMiddleware.invalidate()

    from web.app import create_app
    app = create_app()

    yield app

    session_mod._sessionmaker = original_sessionmaker
    session_mod._engine = original_engine
    SetupGateMiddleware.invalidate()


@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncIterator[AsyncClient]:
    """HTTP client backed by the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="function")
async def unconfigured_client(unconfigured_app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=unconfigured_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="function")
async def auth_client(app, configured_db) -> AsyncIterator[AsyncClient]:
    """HTTP client that is already logged in as admin."""
    _, admin_id = configured_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "test-password-123",
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        yield c


@pytest_asyncio.fixture(scope="function")
async def mod_client(app, configured_db, db_sessionmaker):
    """HTTP client logged in as a moderator."""
    _, _ = configured_db
    mod_id = uuid.uuid4()
    async with db_sessionmaker() as s:
        from bot.database.models.auth.web_user import WebUser, WebRole
        mod = WebUser(
            id=mod_id,
            username="mod",
            email="mod@example.com",
            password_hash=hash_password("mod-password-123"),
            role=WebRole.MODERATOR,
            is_active=True,
        )
        s.add(mod)
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/login", json={
            "username": "mod",
            "password": "mod-password-123",
        })
        assert resp.status_code == 200, f"Mod login failed: {resp.text}"
        yield c
