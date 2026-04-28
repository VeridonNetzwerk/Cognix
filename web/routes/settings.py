"""Settings routes (bot config, runtime toggles)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from config.crypto import decrypt_secret, encrypt_secret
from database.models.system_config import SystemConfig
from web.deps import SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])


class SettingsOut(BaseModel):
    bot_application_id: str
    bot_status_text: str
    bot_status_type: str
    bot_description: str
    google_oauth_enabled: bool
    music_enabled: bool
    registration_open: bool
    bot_token_set: bool


class SettingsUpdate(BaseModel):
    bot_token: SecretStr | None = None
    bot_application_id: str | None = None
    bot_status_text: str | None = None
    bot_status_type: str | None = None
    bot_description: str | None = None
    google_oauth_enabled: bool | None = None
    music_enabled: bool | None = None
    registration_open: bool | None = None


@router.get("/", response_model=SettingsOut)
async def get_settings_endpoint(session: SessionDep) -> SettingsOut:
    cfg = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
    assert cfg is not None
    return SettingsOut(
        bot_application_id=cfg.bot_application_id,
        bot_status_text=cfg.bot_status_text,
        bot_status_type=cfg.bot_status_type,
        bot_description=cfg.bot_description,
        google_oauth_enabled=cfg.google_oauth_enabled,
        music_enabled=cfg.music_enabled,
        registration_open=cfg.registration_open,
        bot_token_set=bool(cfg.bot_token_encrypted),
    )


@router.patch("/")
async def update_settings(payload: SettingsUpdate, session: SessionDep) -> dict:
    cfg = await session.scalar(select(SystemConfig).where(SystemConfig.id == 1))
    assert cfg is not None
    if payload.bot_token is not None:
        token = payload.bot_token.get_secret_value().strip()
        if token:
            cfg.bot_token_encrypted = encrypt_secret(token, aad=b"bot_token")
    for field in (
        "bot_application_id",
        "bot_status_text",
        "bot_status_type",
        "bot_description",
        "google_oauth_enabled",
        "music_enabled",
        "registration_open",
    ):
        val = getattr(payload, field)
        if val is not None:
            setattr(cfg, field, val)

    # Notify bot to reload presence/token if needed
    try:
        await get_ipc().publish_event("settings.changed", {"fields": list(payload.model_fields_set)})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}
