"""Shared test fixtures and configuration."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

# Set test environment variables BEFORE any settings are loaded
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_cognix.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32chars")
os.environ.setdefault("MASTER_KEY", "")
os.environ.setdefault("AUTH_PEPPER", "test-pepper")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("DISCORD_BOT_TOKEN", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture
def event_loop():
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
