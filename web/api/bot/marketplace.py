"""Marketplace API routes — browse, install, and manage cogs from the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select as sa_select

from bot.cogs.registry import BUILTIN_COGS, get_loaded_cogs
from bot.database.models.cogs.cog_package import CogPackage
from web.deps import SessionDep, require_admin
from web.services.bot_ipc import get_ipc

router = APIRouter(prefix="/marketplace", tags=["marketplace"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    cog_or_url: str  # name from registry or direct GitHub URL


class UninstallRequest(BaseModel):
    cog_name: str


class MarketplaceCogOut(BaseModel):
    id: int | None = None
    name: str
    display_name: str
    description: str
    github_repo: str
    version: str | None = None
    dependencies: list[str]
    category: str
    requires_admin: bool
    author: str | None = None
    installed: bool


# ---------------------------------------------------------------------------
# Marketplace registry fetching (shared with bot cog)
# ---------------------------------------------------------------------------

_REGISTRY_CACHE: tuple[list[dict[str, Any]], float] | None = None
_REGISTRY_TTL = 15 * 60  # seconds


async def _get_marketplace_registry() -> list[dict[str, Any]]:
    """Fetch curated registry with TTL-based cache."""
    global _REGISTRY_CACHE
    import time as _time

    now = _time.time()

    if _REGISTRY_CACHE is not None:
        cached_data, cache_time = _REGISTRY_CACHE
        if now - cache_time < _REGISTRY_TTL:
            return cached_data

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json"
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                result = data
            elif isinstance(data, dict) and "cogs" in data:
                result = data["cogs"]
            else:
                result = []
    except Exception:
        result = []

    _REGISTRY_CACHE = (result, now)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/available")
async def list_available(session: SessionDep) -> dict[str, Any]:
    """List all available cogs — built-in + marketplace registry."""
    # Get loaded extensions from bot runtime
    loaded_modules: set[str] = set()
    try:
        loaded_modules = set(get_loaded_cogs())
    except Exception:
        pass

    # Also check bot.extensions directly
    try:
        from bot.runtime import get_bot as _get_bot
        bot = _get_bot()
        if bot is not None:
            loaded_modules |= set(bot.extensions.keys())
    except Exception:
        pass

    # Get installed marketplace packages from DB
    installed_names: set[str] = set()
    try:
        pkgs = await session.scalars(
            sa_select(CogPackage).where(CogPackage.installed.is_(True))
        )
        installed_names = {p.name for p in pkgs}
    except Exception:  # noqa: BLE001
        pass

    cogs_out: list[dict[str, Any]] = []

    # 1. Built-in cogs
    for c in BUILTIN_COGS:
        module = c.get("module", "")
        name = c.get("name", "")
        cogs_out.append({
            "name": name,
            "display_name": name,
            "description": c.get("description", ""),
            "github_repo": "",
            "version": "built-in",
            "dependencies": [],
            "category": c.get("category", "Built-in"),
            "requires_admin": c.get("requires_admin", False),
            "author": "CogniX",
            "installed": module in loaded_modules,
            "is_builtin": True,
        })

    # 2. Remote marketplace registry cogs (skip built-in entries to avoid duplicates)
    raw_list = await _get_marketplace_registry()
    builtin_names = {c.get("name", "") for c in BUILTIN_COGS}
    for c in raw_list:
        if c.get("is_builtin", False) or c.get("name", "") in builtin_names:
            continue
        cogs_out.append({
            "name": c.get("name", ""),
            "display_name": c.get("display_name", c.get("name", "")),
            "description": c.get("description", ""),
            "github_repo": c.get("github_repo", ""),
            "version": c.get("version"),
            "dependencies": c.get("dependencies", []),
            "category": c.get("category", "Marketplace"),
            "requires_admin": c.get("requires_admin", False),
            "author": c.get("author"),
            "installed": c.get("name", "") in installed_names,
            "is_builtin": False,
        })

    return {"cogs": cogs_out}


@router.get("/installed")
async def list_installed(session: SessionDep) -> dict[str, Any]:
    """List all installed/loaded cogs — built-in + marketplace."""
    installed: list[dict[str, Any]] = []

    # 1. Built-in cogs that are loaded
    loaded_modules: set[str] = set()
    try:
        loaded_modules = set(get_loaded_cogs())
    except Exception:
        pass
    try:
        from bot.runtime import get_bot as _get_bot
        bot = _get_bot()
        if bot is not None:
            loaded_modules |= set(bot.extensions.keys())
    except Exception:
        pass

    for c in BUILTIN_COGS:
        module = c.get("module", "")
        if module in loaded_modules:
            installed.append({
                "id": None,
                "name": c.get("name", ""),
                "display_name": c.get("name", ""),
                "description": c.get("description", ""),
                "github_repo": "",
                "version": "built-in",
                "dependencies": [],
                "category": c.get("category", "Built-in"),
                "requires_admin": c.get("requires_admin", False),
                "author": "CogniX",
                "module_name": module,
                "installed_at": None,
                "is_builtin": True,
            })

    # 2. Marketplace-installed cogs from DB
    try:
        pkgs = await session.scalars(
            sa_select(CogPackage).where(
                CogPackage.installed.is_(True),
                CogPackage.uninstall_requested.is_(False),
            )
        )
        for p in pkgs:
            installed.append({
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "github_repo": p.github_repo,
                "version": p.version,
                "dependencies": p.dependencies or [],
                "category": p.category,
                "requires_admin": p.requires_admin,
                "author": p.author,
                "module_name": p.module_name,
                "installed_at": p.last_installed_at.isoformat() if p.last_installed_at else None,
                "is_builtin": False,
            })
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    return {"cogs": installed}


@router.post("/install")
async def install_cog(req: InstallRequest, session: SessionDep) -> dict[str, Any]:
    """Install a cog via the dashboard. Tries bot IPC first, falls back to direct call."""
    # Try IPC (Redis) first
    ipc = get_ipc()
    try:
        result = await ipc.call(
            "marketplace.install",
            {"cog_or_url": req.cog_or_url},
            timeout=120.0,
        )
        if result.get("status") == "ok":
            return {"ok": True, "cog": result.get("payload", {}).get("cog", req.cog_or_url)}
    except Exception:  # noqa: BLE001
        pass

    # Fallback: direct bot call (same process, no Redis needed)
    try:
        from bot.runtime import get_bot as _get_bot

        bot = _get_bot()
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot not running")

        cog_or_url = req.cog_or_url

        # Check if this is a built-in cog by name
        from bot.cogs.registry import BUILTIN_COGS, get_cog_info, load_cog
        builtin_info = get_cog_info(cog_or_url)
        is_builtin_match = any(
            c["name"].lower() == cog_or_url.lower() or c["module"] == cog_or_url
            for c in BUILTIN_COGS
        )

        if is_builtin_match and builtin_info:
            # Built-in cog: just load the extension
            result = await load_cog(bot, builtin_info["module"])
            if not result.get("ok"):
                raise HTTPException(400, result.get("error", "failed to load cog"))
            return {"ok": True, "cog": builtin_info["name"]}

        # Marketplace cog: git clone or pip install
        from bot.cogs.admin.marketplace import install_cog_from_source, save_package_metadata

        is_url = cog_or_url.startswith("http") or cog_or_url.startswith("file:")
        repo_url = cog_or_url
        cog_name = cog_or_url

        if is_url:
            from urllib.parse import urlparse
            parsed = urlparse(cog_or_url)
            path_parts = [p for p in parsed.path.split("/") if p]
            if path_parts:
                cog_name = path_parts[-1].replace(".git", "")
            if cog_or_url.startswith("file://"):
                repo_url = parsed.path
        else:
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://raw.githubusercontent.com/VeridonNetzwerk/cognix-marketplace/main/registry.json"
                    )
                    resp.raise_for_status()
                    reg_data = resp.json()
                found = None
                for c in (reg_data if isinstance(reg_data, list) else reg_data.get("cogs", [])):
                    if c.get("name", "").lower() == cog_or_url.lower():
                        found = c
                        break
            except Exception:
                found = None
            if found is None:
                raise HTTPException(400, f"Unknown marketplace cog: {cog_or_url}")
            repo_url = found.get("github_repo", "")
            cog_name = found.get("name", cog_or_url)

        result = await install_cog_from_source(bot, repo_url, cog_name)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "installation failed"))

        await save_package_metadata(
            cog_name=cog_name,
            display_name=cog_name,
            description=f"Installed from {repo_url}",
            github_repo=repo_url,
            version=None,
            dependencies=[],
            category="Custom",
            requires_admin=False,
            author="Unknown",
            installed=True,
            module_name=result.get("module"),
        )
        await bot.tree.sync()

        return {"ok": True, "cog": cog_name}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.post("/uninstall")
async def uninstall_cog(req: UninstallRequest, session: SessionDep) -> dict[str, Any]:
    """Uninstall a cog via the dashboard. Tries bot IPC first, falls back to direct call."""
    # Try IPC (Redis) first
    ipc = get_ipc()
    try:
        result = await ipc.call(
            "marketplace.uninstall",
            {"cog_name": req.cog_name},
            timeout=30.0,
        )
        if result.get("status") == "ok":
            return {"ok": True, "cog": req.cog_name}
    except Exception:  # noqa: BLE001
        pass

    # Fallback: direct bot call (same process, no Redis needed)
    try:
        from bot.runtime import get_bot as _get_bot

        bot = _get_bot()
        if bot is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot not running")

        # Check if this is a built-in cog
        from bot.cogs.registry import BUILTIN_COGS, unload_cog
        is_builtin_match = any(
            c["name"].lower() == req.cog_name.lower() or c["module"] == req.cog_name
            for c in BUILTIN_COGS
        )

        if is_builtin_match:
            # Built-in cog: just unload the extension
            result = await unload_cog(bot, req.cog_name)
            if not result.get("ok"):
                raise HTTPException(400, result.get("error", "failed to unload cog"))
            return {"ok": True, "cog": req.cog_name}

        # Marketplace cog: uninstall + delete files
        from bot.cogs.admin.marketplace import uninstall_cog as _uninstall_cog

        result = await _uninstall_cog(bot, req.cog_name)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "uninstallation failed"))

        await bot.tree.sync()

        # Update DB record
        try:
            from bot.database.session import db_session
            async with db_session() as s:
                pkg = await s.scalar(sa_select(CogPackage).where(CogPackage.name == req.cog_name))
                if pkg:
                    pkg.installed = False
                    await s.flush()
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "cog": req.cog_name}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


@router.get("/search")
async def search_cogs(query: str, session: SessionDep) -> dict[str, Any]:
    """Search the marketplace registry for cogs matching a query."""
    raw_list = await _get_marketplace_registry()
    ql = query.lower()

    filtered = [
        c for c in raw_list
        if ql in str(c.get("name", "")).lower()
        or ql in str(c.get("display_name", "")).lower()
        or ql in str(c.get("description", "")).lower()
        or ql in str(c.get("category", "")).lower()
    ]

    return {"cogs": filtered, "total": len(filtered)}
