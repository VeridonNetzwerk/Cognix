"""Application settings.

Loads bootstrap configuration from environment variables / .env file.
Runtime mutable configuration (bot token, etc.) is stored in the database
``system_config`` table and overlays these values at runtime via
``RuntimeConfig`` (see ``config.runtime``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bootstrap settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Core ----
    app_env: Literal["development", "production"] = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    app_base_url: str = "http://localhost:8080"
    trust_proxy: bool = False

    # ---- Crypto ----
    master_key: str = Field(default="", description="Base64 32-byte key for AES-GCM")
    jwt_secret: str = Field(default="", min_length=0)
    auth_pepper: str = ""
    access_token_ttl_minutes: int = 480
    refresh_token_ttl_days: int = 7
    remember_me_ttl_days: int = 30

    # ---- Database ----
    database_url: str = "sqlite+aiosqlite:///./data/cognix.db"

    # ---- Redis ----
    redis_url: str = ""

    # ---- Discord ----
    discord_bot_token: str = ""
    discord_application_id: str = ""
    discord_owner_ids: str = ""

    # ---- Google OAuth ----
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""

    # ---- Frontend ----
    frontend_dir: str = "frontend/.next/standalone"
    serve_frontend: bool = True

    # ---- Logging ----
    log_level: str = "INFO"
    log_json: bool = False

    # ---- Derived helpers ----
    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

    @property
    def cookies_secure(self) -> bool:
        """Only mark auth cookies Secure when the public URL actually uses HTTPS.

        Setting Secure on a plain-http origin causes browsers to silently drop
        the Set-Cookie, which makes login appear to succeed but no session is
        established. Production deployments without TLS (e.g. behind a non-TLS
        Pterodactyl host) need plain cookies.
        """
        return self.app_base_url.lower().startswith("https://")

    @property
    def owner_ids_list(self) -> list[int]:
        return [int(x) for x in self.discord_owner_ids.split(",") if x.strip().isdigit()]

    @property
    def db_kind(self) -> Literal["sqlite", "postgresql", "mysql"]:
        if self.database_url.startswith("sqlite"):
            return "sqlite"
        if self.database_url.startswith("postgresql"):
            return "postgresql"
        if self.database_url.startswith("mysql"):
            return "mysql"
        raise ValueError(f"Unsupported database URL: {self.database_url}")

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url.strip())

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """Normalize common DB URL variants to async SQLAlchemy dialects."""
        value = v.strip()
        if value.startswith("mysql://"):
            return "mysql+aiomysql://" + value[len("mysql://") :]
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        if value.startswith("mysql+pymysql://"):
            return "mysql+aiomysql://" + value[len("mysql+pymysql://") :]
        return value

    @field_validator("master_key")
    @classmethod
    def _validate_master_key(cls, v: str) -> str:
        # In dev / first-run we tolerate empty; the setup wizard fills it.
        return v

    def ensure_data_dirs(self) -> None:
        """Create local data directories needed for SQLite / logs."""
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.split("///", 1)[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings instance."""
    return Settings()
