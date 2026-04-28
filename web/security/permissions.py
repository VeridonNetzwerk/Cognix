"""Per-module permission helpers (granular, override role-based)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.web_user import WebRole, WebUser
from database.models.web_user_settings import MODULES, WebUserModulePermission

# none < read < write
_LEVEL_ORDER = {"none": 0, "read": 1, "write": 2}


def _is_admin_user(user: WebUser) -> bool:
    return user.role == WebRole.ADMIN or user.username == "admin"


def _normalize(level: str | None) -> str:
    if not level:
        return "none"
    v = str(level).strip().lower()
    return v if v in _LEVEL_ORDER else "none"


def _default_level(user: WebUser, module: str) -> str:
    if user.role == WebRole.MODERATOR and module in {"tickets", "embeds", "discord_log"}:
        return "write"
    return "read"


async def has_permission(
    session: AsyncSession,
    user: WebUser,
    module: str,
    *,
    level: str = "read",
) -> bool:
    if _is_admin_user(user):
        return True
    row = await session.scalar(
        select(WebUserModulePermission).where(
            WebUserModulePermission.user_id == user.id,
            WebUserModulePermission.module == module,
        )
    )
    actual = _normalize(row.level if row is not None else _default_level(user, module))
    needed = _normalize(level)
    return _LEVEL_ORDER[actual] >= _LEVEL_ORDER[needed]


async def get_permission_map(
    session: AsyncSession, user: WebUser
) -> dict[str, str]:
    if _is_admin_user(user):
        return {m: "write" for m in MODULES}
    rows = (
        await session.scalars(
            select(WebUserModulePermission).where(
                WebUserModulePermission.user_id == user.id
            )
        )
    ).all()
    by_mod = {r.module: _normalize(r.level) for r in rows}
    return {m: by_mod.get(m, _default_level(user, m)) for m in MODULES}
