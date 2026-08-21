"""GitHub-backed cog store.

The CogniX cog marketplace is designed to pull cogs from the project's GitHub
repository rather than shipping them locally. This module downloads the
``cogs_store/`` subtree from the public repo as a tarball (no auth, no API
rate limits) and caches it under ``data/github_store/``. The registry then
discovers and installs cogs from that cache exactly as it would from a local
``cogs_store/`` directory.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

from bot.config.logging import get_logger

log = get_logger("bot.github_store")

# --- Repository configuration (public repo, no auth required) ---------------
OWNER = "VeridonNetzwerk"
REPO = "CogniX"
BRANCH = "main"
TARBALL_URL = f"https://github.com/{OWNER}/{REPO}/archive/refs/heads/{BRANCH}.tar.gz"

# Cache location: <project>/data/github_store/cogs_store
_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _ROOT / "data"
_CACHE_BASE = _DATA_DIR / "github_store"
_STORE_DIR = _CACHE_BASE / "cogs_store"
_MARKER = _CACHE_BASE / "STORE_CACHE_MARKER"
_TTL_SECONDS = 3600

# --- Sync state (in-process, not persisted) ---------------------------------
_last_sync_ok: bool = False
_last_sync_ts: float | None = None


def get_github_store_dir() -> Path | None:
    """Return the cached cogs_store directory (or None if not yet downloaded)."""
    return _STORE_DIR


def get_github_store_base() -> Path:
    """Return the cache base (parent of cogs_store) — used for icon serving."""
    return _CACHE_BASE


def get_sync_status() -> dict:
    """Return current store sync state for UI display."""
    if _last_sync_ts is not None:
        ts = datetime.fromtimestamp(_last_sync_ts, tz=UTC).strftime("%H:%M:%S")
    else:
        ts = None
    return {
        "available": _STORE_DIR.exists() and _last_sync_ok,
        "last_sync": ts,
        "has_cache": _STORE_DIR.exists(),
    }


def _marker_fresh() -> bool:
    if not _MARKER.exists() or not _STORE_DIR.exists():
        return False
    try:
        return (time.time() - _MARKER.stat().st_mtime) < _TTL_SECONDS
    except OSError:
        return False


def _write_marker() -> None:
    _CACHE_BASE.mkdir(parents=True, exist_ok=True)
    _MARKER.write_text(f"{OWNER}/{REPO}@{BRANCH}\n", encoding="utf-8")


async def ensure_store_cache(force: bool = False) -> bool:
    """Download (if needed) the cogs_store subtree from GitHub.

    Returns True if a usable store cache is present afterwards. Failures are
    non-fatal: the marketplace simply stays empty (e.g. when offline).

    If a cache exists but is stale, returns True immediately and triggers a
    background refresh so the page doesn't block on a slow GitHub fetch.
    """
    global _last_sync_ok

    if not force and _marker_fresh():
        _last_sync_ok = True
        return _STORE_DIR.exists()

    # If we have a cache but it's stale, serve it immediately and refresh in background
    if not force and _STORE_DIR.exists():
        _last_sync_ok = True
        asyncio.create_task(_background_refresh())
        return True

    # No cache at all — must block on first download
    return await _do_download(force=force)


async def _background_refresh() -> None:
    """Background refresh of the store cache (non-blocking for callers)."""
    try:
        await _do_download(force=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("github_store_background_refresh_failed", error=str(exc))


async def _do_download(force: bool = False) -> bool:
    """Actual download logic. Updates sync state on success/failure."""
    global _last_sync_ok, _last_sync_ts

    try:
        import httpx

        log.info("github_store_download_start", url=TARBALL_URL)
        async with httpx.AsyncClient(follow_redirects=True, timeout=90.0) as client:
            resp = await client.get(TARBALL_URL)
            resp.raise_for_status()
            tar_bytes = resp.content
        _extract_cogs_store(tar_bytes)
        _write_marker()
        _last_sync_ok = True
        _last_sync_ts = time.time()
        # Count cogs in release/ subdir (new structure) or flat (old structure)
        release_dir = _STORE_DIR / "release"
        if release_dir.exists():
            cog_count = len([d for d in release_dir.iterdir() if d.is_dir() and not d.name.startswith("_")])
        else:
            cog_count = len(list(_STORE_DIR.glob("*")))
        log.info("github_store_download_done", cogs=cog_count)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("github_store_download_failed", error=str(exc))
        _last_sync_ok = False
        _last_sync_ts = time.time()
        return _STORE_DIR.exists()


def _extract_cogs_store(tar_bytes: bytes) -> None:
    """Extract only the cogs_store/ subtree from the repo tarball."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        members = tar.getmembers()
        if not members:
            return
        # The tarball top-level dir is "<REPO>-<BRANCH>" (e.g. CogniX-main).
        top_dir = members[0].name.split("/", 1)[0]
        prefix = f"{top_dir}/cogs_store/"
        for member in members:
            if not member.name.startswith(prefix):
                continue
            rel = member.name[len(prefix):]  # strip "<REPO>-<BRANCH>/cogs_store/"
            if not rel:
                continue
            target = _STORE_DIR / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
