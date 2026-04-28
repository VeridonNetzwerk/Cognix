"""Auth + setup schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr
    otp: str | None = Field(default=None, min_length=6, max_length=10)
    remember_me: bool = False


class TokenPair(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    email: str | None
    role: str
    totp_enabled: bool


class SetupStatus(BaseModel):
    configured: bool
    has_admin: bool
    db_kind: str
    google_oauth_enabled: bool


class SetupRequest(BaseModel):
    bot_token: SecretStr
    bot_application_id: str = ""
    database_url: str | None = None  # Optional override; usually pre-set via .env
    admin_username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    admin_email: EmailStr | None = None
    admin_password: SecretStr
    enable_2fa: bool = False
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None


class SetupResponse(BaseModel):
    success: bool
    totp_provisioning_uri: str | None = None
    totp_qr_data_url: str | None = None
    backup_codes: list[str] | None = None
