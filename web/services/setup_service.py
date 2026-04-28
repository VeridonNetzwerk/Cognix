"""Setup wizard service: creates first admin + persists bot config."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.crypto import encrypt_secret
from config.settings import get_settings
from database.models.system_config import SystemConfig
from database.models.web_user import BackupCode, WebRole, WebUser
from web.middleware.setup_gate import SetupGateMiddleware
from web.schemas.auth import SetupRequest, SetupResponse
from web.security.passwords import hash_password
from web.security.totp import (
    encrypted_secret,
    generate_backup_codes,
    generate_secret,
    provisioning_uri,
    qr_data_url,
)


class SetupError(RuntimeError):
    """Raised when setup is invalid or already complete."""


async def get_status(session: AsyncSession) -> dict:
    settings = get_settings()
    cfg = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
    has_admin = bool(
        await session.scalar(select(WebUser.id).where(WebUser.role == WebRole.ADMIN).limit(1))
    )
    return {
        "configured": bool(cfg and cfg.configured),
        "has_admin": has_admin,
        "db_kind": settings.db_kind,
        "google_oauth_enabled": bool(cfg and cfg.google_oauth_enabled),
    }


async def perform_setup(session: AsyncSession, req: SetupRequest) -> SetupResponse:
    cfg = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
    if cfg is None:
        cfg = SystemConfig(id=1)
        session.add(cfg)
    if cfg.configured:
        raise SetupError("System is already configured")

    # Validate
    bot_token = req.bot_token.get_secret_value().strip()
    if not bot_token:
        raise SetupError("Bot token is required")
    pw = req.admin_password.get_secret_value()
    if len(pw) < 10:
        raise SetupError("Admin password must be at least 10 characters")

    # Persist bot config
    cfg.bot_token_encrypted = encrypt_secret(bot_token, aad=b"bot_token")
    cfg.bot_application_id = req.bot_application_id or ""
    if req.google_oauth_client_id and req.google_oauth_client_secret:
        cfg.google_oauth_client_id_encrypted = encrypt_secret(
            req.google_oauth_client_id, aad=b"oauth"
        )
        cfg.google_oauth_client_secret_encrypted = encrypt_secret(
            req.google_oauth_client_secret.get_secret_value(), aad=b"oauth"
        )
        cfg.google_oauth_enabled = True

    # Create admin
    admin = WebUser(
        username=req.admin_username,
        email=str(req.admin_email) if req.admin_email else None,
        password_hash=hash_password(pw),
        role=WebRole.ADMIN,
        is_active=True,
    )

    response = SetupResponse(success=True)

    if req.enable_2fa:
        secret = generate_secret()
        admin.totp_secret_encrypted = encrypted_secret(secret)
        admin.totp_enabled = True
        uri = provisioning_uri(secret, account=admin.username)
        response.totp_provisioning_uri = uri
        response.totp_qr_data_url = qr_data_url(uri)
        codes = generate_backup_codes()
        response.backup_codes = codes
        for raw in codes:
            session.add(
                BackupCode(user_id=admin.id, code_hash=_hash_code(raw))
            )

    session.add(admin)
    cfg.configured = True
    await session.flush()
    SetupGateMiddleware.invalidate()
    return response


def _hash_code(code: str) -> str:
    import hashlib

    return hashlib.sha256(code.encode("utf-8")).hexdigest()
