"""Cog Registry — central registry of all available cogs and their load state.

This module provides:
1. Dynamic discovery of cogs from the top-level cogs/ directory (installed/active)
2. Discovery of cogs from cogs_store/ directory (available to install)
3. Runtime tracking of which cogs are currently loaded
4. Helper functions to load/unload/reload cogs with automatic slash-command tree sync
5. Persistence of loaded state to the database so it survives restarts
6. Install/uninstall cogs (copy between cogs_store/ and cogs/)

Design principle:
- Extensions in discord.py are bot-wide (not per-guild). When a cog is loaded,
  its commands become available on ALL servers.
- Per-server enable/disable is handled separately via ServerConfig.enabled_cogs.
- This registry tracks which cogs are *loaded* globally.
- Installed cogs live in the top-level cogs/ directory and are auto-loaded on startup.
- Available (not-yet-installed) cogs live in cogs_store/ and can be installed via the web panel.
"""

from __future__ import annotations

import ast
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from bot.config.logging import get_logger

log = get_logger("bot.cog_registry")

# ---------------------------------------------------------------------------
# Cog Discovery — scan the top-level cogs/ directory for cog modules
# ---------------------------------------------------------------------------

CogInfo = dict[str, str | bool | None]
_COGS_DIR = Path(__file__).resolve().parent.parent.parent / "cogs"
_COGS_STORE_DIR = Path(__file__).resolve().parent.parent.parent / "cogs_store"

# Dev mode flag — when True, cogs are loaded from cogs_store/dev/ (flat structure).
# When False (default), cogs are loaded from cogs_store/release/<cog>/v<version>/.
_DEV_MODE: bool = False


def set_dev_mode(enabled: bool) -> None:
    """Enable or disable dev mode for cog store discovery."""
    global _DEV_MODE, _store_cache
    _DEV_MODE = enabled
    _store_cache = None  # invalidate cache
    log.info("cog_store_mode", mode="dev" if enabled else "release")


# ---------------------------------------------------------------------------
# Category metadata — gradient colors, icons, slogans (Ubuntu App Center style)
# ---------------------------------------------------------------------------

COG_CATEGORIES: dict[str, dict[str, str]] = {
    "Core": {
        "icon": "ph-cpu",
        "slogan": "Core bot widgets",
        "gradient_from": "#1a1a2e",
        "gradient_to": "#4a3f6b",
    },
    "Administration": {
        "icon": "ph-shield-star",
        "slogan": "Manage, configure, and protect your bot",
        "gradient_from": "#320a39",
        "gradient_to": "#0a737e",
    },
    "Moderation": {
        "icon": "ph-gavel",
        "slogan": "Keep your servers safe and orderly",
        "gradient_from": "#700045",
        "gradient_to": "#e95420",
    },
    "Fun": {
        "icon": "ph-confetti",
        "slogan": "Entertainment, music, and games for your community",
        "gradient_from": "#b41601",
        "gradient_to": "#feac0c",
    },
    "Logging": {
        "icon": "ph-scroll",
        "slogan": "Track and record every event in your servers",
        "gradient_from": "#082435",
        "gradient_to": "#297068",
    },
    "Analytics": {
        "icon": "ph-chart-line",
        "slogan": "Insights, statistics, and growth tracking",
        "gradient_from": "#12224b",
        "gradient_to": "#d27ed9",
    },
    "Support": {
        "icon": "ph-lifebuoy",
        "slogan": "Ticket systems and support tools for your members",
        "gradient_from": "#271658",
        "gradient_to": "#3be173",
    },
    "Utility": {
        "icon": "ph-wrench",
        "slogan": "Handy tools and everyday commands",
        "gradient_from": "#000594",
        "gradient_to": "#ff9bb3",
    },
}

# "All" pseudo-category for the explore view
COG_CATEGORY_ALL = {
    "icon": "ph-squares-four",
    "slogan": "Discover and manage all your bot's modules",
    "gradient_from": "#360050",
    "gradient_to": "#e13b95",
}


def _find_cog_icon(cog_dir: Path, module_name: str) -> str | None:
    """Check for icon.png in a cog's directory. Returns a static URL path or None."""
    for icon_name in ("icon.png", "icon.svg"):
        icon_path = cog_dir / icon_name
        if icon_path.exists():
            # Extract cog dir name from module_name (e.g. 'cogs.moderation.moderation' -> 'moderation')
            parts = module_name.split(".")
            cog_slug = parts[1] if len(parts) >= 2 else cog_dir.name
            return f"/cogs/icon/{cog_slug}/{icon_name}"
    return None


def _make_cog_info(module: str, *, name: str = "", description: str = "", category: str = "", requires_admin: bool = False, icon_url: str | None = None, version: str = "", verified: bool = False, permissions: list | None = None) -> CogInfo:
    """Build a CogInfo dict, deriving name from module if not provided."""
    if not name:
        short = module.rsplit(".", 1)[-1]
        name = short.replace("_", " ").title()
    return {
        "module": module,
        "name": name,
        "description": description,
        "category": category,
        "requires_admin": requires_admin,
        "icon_url": icon_url,
        "version": version,
        "verified": verified,
        "permissions": permissions or [],
    }


def _cog_info_from_dict(module: str, info: dict, icon_url: str | None = None) -> CogInfo:
    """Build a CogInfo dict from a COG_INFO dict, with defaults."""
    return _make_cog_info(
        module,
        name=info.get("name", ""),
        description=info.get("description", ""),
        category=info.get("category", ""),
        requires_admin=info.get("requires_admin", False),
        icon_url=icon_url,
        version=info.get("version", ""),
        verified=info.get("verified", False),
        permissions=info.get("permissions", []),
    )


def _discover_cogs() -> list[CogInfo]:
    """Discover all cog modules in the top-level cogs/ directory.

    Scans for .py files (excluding __init__.py, _*.py) in cogs/
    and its subdirectories. Each module may define a COG_INFO dict with
    metadata (name, description, category, requires_admin).
    """
    if not _COGS_DIR.exists():
        return []

    cogs: list[CogInfo] = []

    for py_file in sorted(_COGS_DIR.rglob("*.py")):
        if py_file.name == "__init__.py" or py_file.name.startswith("_"):
            continue

        # Skip non-cog files: pages/ and templates/ are cog web assets, not discord.py cogs
        parts_relative = py_file.relative_to(_COGS_DIR).parts
        if any(p in ("pages", "templates") for p in parts_relative[:-1]):
            continue

        try:
            rel = py_file.relative_to(_COGS_DIR.parent)
            module_parts = list(rel.parts)
            module_parts[-1] = module_parts[-1].removesuffix(".py")
            module_name = ".".join(module_parts)
        except ValueError:
            continue

        icon_url = _find_cog_icon(py_file.parent, module_name)

        try:
            mod = importlib.import_module(module_name)
            info = getattr(mod, "COG_INFO", None)
            if info and isinstance(info, dict):
                cogs.append(_cog_info_from_dict(module_name, info, icon_url))
            else:
                log.debug("cog_skip_no_info", module=module_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("cog_discover_failed", module=module_name, error=str(exc))

    return cogs


def _discover_cogs_cached() -> list[CogInfo]:
    """Discover cogs with caching to avoid repeated filesystem scans."""
    global _cogs_cache
    if _cogs_cache is not None:
        return _cogs_cache
    _cogs_cache = _discover_cogs()
    return _cogs_cache


_cogs_cache: list[CogInfo] | None = None


def refresh_cogs_cache() -> None:
    """Force a re-scan of the cogs directory. Call after installing/removing cogs."""
    global _cogs_cache
    _cogs_cache = None


def get_all_cog_info() -> list[CogInfo]:
    """Return metadata for all installed cogs (in cogs/ directory)."""
    return [dict(c) for c in _discover_cogs_cached()]


# ---------------------------------------------------------------------------
# Cog Store — discover cogs available to install from cogs_store/
# ---------------------------------------------------------------------------

_store_cache: list[CogInfo] | None = None


def _store_root() -> Path | None:
    """Resolve the cog-store source directory.

    In dev mode, returns ``cogs_store/dev/``.
    In release mode, returns ``cogs_store/release/``.
    Falls back to the GitHub-backed cache if the local directory doesn't exist.
    """
    subdir = "dev" if _DEV_MODE else "release"
    local = _COGS_STORE_DIR / subdir
    if local.exists():
        return local
    try:
        from bot.cogs.github_store import get_github_store_dir

        gh = get_github_store_dir()
        if gh is not None and gh.exists():
            gh_sub = gh / subdir
            if gh_sub.exists():
                return gh_sub
            return gh  # fallback: flat structure (old github cache)
    except Exception:  # noqa: BLE001
        pass
    return None


def _latest_version_dir(cog_root: Path) -> Path | None:
    """Find the latest version subdirectory inside a release cog folder.

    Expects directories named like ``v0.1.0``, ``v1.2.3``, etc.
    Returns the highest-version Path, or None if no version dirs exist.
    """
    if not cog_root.is_dir():
        return None
    version_dirs = []
    for d in cog_root.iterdir():
        if d.is_dir() and d.name.startswith("v"):
            version_dirs.append(d)
    if not version_dirs:
        return None
    # Sort by parsed version tuple
    version_dirs.sort(key=lambda d: _parse_version(d.name.removeprefix("v")))
    return version_dirs[-1]


def _resolve_store_cog_dir(root: Path, cog_dir_name: str) -> Path | None:
    """Resolve the actual cog directory within the store root.

    In dev mode: ``root/<cog_dir_name>/`` (flat).
    In release mode: ``root/<cog_dir_name>/v<latest>/``.
    """
    base = root / cog_dir_name
    if not base.is_dir():
        return None
    if _DEV_MODE:
        return base
    # Release mode: find latest version subdirectory
    return _latest_version_dir(base) or base


def _discover_store_cogs() -> list[CogInfo]:
    """Discover all cog modules in the cog store directory.

    In dev mode, scans ``cogs_store/dev/<cog>/`` (flat structure).
    In release mode, scans ``cogs_store/release/<cog>/v<version>/``.
    """
    root = _store_root()
    if root is None:
        return []

    cogs: list[CogInfo] = []

    if _DEV_MODE:
        # Dev mode: flat structure — scan each cog dir directly
        scan_dirs = []
        for cog_dir in sorted(root.iterdir()):
            if not cog_dir.is_dir() or cog_dir.name.startswith("_"):
                continue
            scan_dirs.append((cog_dir, cog_dir.name))
    else:
        # Release mode: scan release/<cog>/v<latest>/
        scan_dirs = []
        for cog_dir in sorted(root.iterdir()):
            if not cog_dir.is_dir() or cog_dir.name.startswith("_"):
                continue
            latest = _latest_version_dir(cog_dir)
            if latest is not None:
                scan_dirs.append((latest, cog_dir.name))

    for cog_dir, cog_slug in scan_dirs:
        for py_file in sorted(cog_dir.glob("*.py")):
            if py_file.name == "__init__.py" or py_file.name.startswith("_"):
                continue

            module_name = "cogs." + cog_slug + "." + py_file.stem
            icon_url = _find_cog_icon(cog_dir, module_name)
            info = _read_cog_info_from_file(py_file)
            if info:
                info.setdefault("verified", True)
                cogs.append(_cog_info_from_dict(module_name, info, icon_url))
            else:
                log.debug("store_cog_skip_no_info", file=str(py_file))

    return cogs


def _read_cog_info_from_file(py_file: Path) -> dict | None:
    """Read COG_INFO dict from a .py file without importing it."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "COG_INFO":
                        return ast.literal_eval(node.value)
    except Exception:  # noqa: BLE001
        pass
    return None


def get_store_cog_info() -> list[CogInfo]:
    """Return metadata for all cogs available in the store (cogs_store/)."""
    global _store_cache
    if _store_cache is None:
        _store_cache = _discover_store_cogs()
    return [dict(c) for c in _store_cache]


def refresh_store_cache() -> None:
    """Force a re-scan of the cogs_store directory."""
    global _store_cache
    _store_cache = None


def is_cog_installed(module_name: str) -> bool:
    """Check if a cog is installed (exists in cogs/ directory)."""
    # module_name is like 'cogs.moderation.moderation'
    parts = module_name.split(".")
    if parts[0] == "cogs":
        parts = parts[1:]
    py_file = _COGS_DIR / Path(*parts).with_suffix(".py")
    return py_file.exists()


def discover_embed_templates() -> list[dict[str, Any]]:
    """Scan all installed cogs for EMBED_TEMPLATES declarations.

    Each cog may optionally define ``EMBED_TEMPLATES`` — a list of dicts with
    keys like: key, title, description, color, footer_text, thumbnail_url,
    image_url, author_name, fields, extras.

    Returns a list of template dicts augmented with cog metadata:
    ``_cog_module``, ``_cog_name``, ``_cog_category``.
    """
    templates: list[dict[str, Any]] = []
    for cog in _discover_cogs_cached():
        module_name = cog["module"]
        try:
            mod = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            continue
        embed_templates = getattr(mod, "EMBED_TEMPLATES", None)
        if not embed_templates or not isinstance(embed_templates, list):
            continue
        for tpl in embed_templates:
            if not isinstance(tpl, dict) or not tpl.get("key"):
                continue
            augmented = dict(tpl)
            augmented["_cog_module"] = module_name
            augmented["_cog_name"] = cog.get("name", module_name)
            augmented["_cog_category"] = cog.get("category", "Utility")
            augmented.setdefault("source", "cog")
            templates.append(augmented)
    return templates


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a semver-like string into a comparable tuple."""
    parts: list[int] = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            # Strip non-numeric suffix (e.g. "1.0.0-beta" → 1,0,0)
            num = ""
            for ch in p:
                if ch.isdigit():
                    num += ch
                else:
                    break
            parts.append(int(num) if num else 0)
    return tuple(parts)


def _is_newer(store_ver: str, installed_ver: str) -> bool:
    """Return True if store_ver is strictly newer than installed_ver."""
    if not store_ver:
        return False
    if not installed_ver:
        return True
    return _parse_version(store_ver) > _parse_version(installed_ver)


def get_cog_updates() -> list[dict]:
    """Return installed cogs that have a newer version available in the store.

    Each item contains: module, name, installed_version, store_version, description,
    category, icon_url, requires_admin.
    """
    installed = get_all_cog_info()
    store = get_store_cog_info()
    store_by_module = {c["module"]: c for c in store}

    updates: list[dict] = []
    for cog in installed:
        module = cog["module"]
        store_cog = store_by_module.get(module)
        if store_cog is None:
            continue
        installed_ver = cog.get("version", "") or ""
        store_ver = store_cog.get("version", "") or ""
        if _is_newer(store_ver, installed_ver):
            updates.append({
                "module": module,
                "name": cog["name"],
                "description": cog.get("description", ""),
                "category": cog.get("category", ""),
                "icon_url": cog.get("icon_url"),
                "requires_admin": cog.get("requires_admin", False),
                "installed_version": installed_ver,
                "store_version": store_ver,
            })
    return updates


# ---------------------------------------------------------------------------
# Pip package tracking — persist which packages were installed by which cog
# ---------------------------------------------------------------------------

_PKG_TRACK_FILE = _COGS_DIR.parent / "data" / "cog_packages.json"


def _load_pkg_tracking() -> dict[str, list[str]]:
    """Load the cog→packages mapping from disk."""
    if _PKG_TRACK_FILE.exists():
        try:
            return json.loads(_PKG_TRACK_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_pkg_tracking(data: dict[str, list[str]]) -> None:
    """Save the cog→packages mapping to disk."""
    _PKG_TRACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PKG_TRACK_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_requirements(req_path: Path) -> list[str]:
    """Parse a requirements.txt file and return a list of package names (normalized)."""
    if not req_path.exists():
        return []
    packages: list[str] = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers: package>=1.0 → package
        pkg = line.split("=")[0].split(">")[0].split("<")[0].split("!")[0].split("~")[0].strip()
        if pkg:
            packages.append(pkg)
    return packages


def _get_all_installed_cog_requirements(exclude: str | None = None) -> set[str]:
    """Get all packages required by all installed cogs, optionally excluding one."""
    tracking = _load_pkg_tracking()
    all_pkgs: set[str] = set()
    for cog_module, pkgs in tracking.items():
        if exclude and cog_module == exclude:
            continue
        # Only count packages from cogs that are still installed
        if is_cog_installed(cog_module):
            all_pkgs.update(pkgs)
    return all_pkgs


def _pip_install(packages: list[str]) -> dict:
    """Install packages via pip. Returns {'ok': True} or {'error': '...'}."""
    return _pip_run(["install"], packages, timeout=120, action="install")


def _pip_uninstall(packages: list[str]) -> dict:
    """Uninstall packages via pip. Returns {'ok': True} or {'error': '...'}."""
    return _pip_run(["uninstall", "-y"], packages, timeout=60, action="uninstall")


def _pip_run(args: list[str], packages: list[str], *, timeout: int, action: str) -> dict:
    """Run a pip command with packages. Returns {'ok': True} or {'error': '...'}."""
    if not packages:
        return {"ok": True}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", *args, *packages],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"error": f"pip {action} failed: {result.stderr.strip()[-500:]}"}
        log.info(f"cog_pip_{action}ed", packages=packages)
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"error": f"pip {action} timed out ({timeout}s)"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"pip {action} error: {exc}"}


def _resolve_store_dir_for_module(module_name: str) -> Path | None:
    """Resolve the store directory for a cog module. Returns None if unavailable."""
    root = _store_root()
    if root is None:
        return None
    parts = module_name.split(".")
    return _resolve_store_cog_dir(root, parts[1]) if len(parts) >= 2 else root


def get_cog_requirements(module_name: str) -> list[str]:
    """Get the pip requirements for a cog from its store directory."""
    store_dir = _resolve_store_dir_for_module(module_name)
    if store_dir is None:
        return []
    return _parse_requirements(store_dir / "requirements.txt")


def get_cog_files(module_name: str) -> list[dict]:
    """Get list of extra files (non-.py) bundled with a cog in the store."""
    store_dir = _resolve_store_dir_for_module(module_name)
    if store_dir is None or not store_dir.exists():
        return []
    _skip_suffixes = {".py", ".zip", ".pyc"}
    extra_files: list[dict] = []
    for f in sorted(store_dir.rglob("*")):
        if f.is_dir() or f.name == "__init__.py" or f.name.startswith("_"):
            continue
        if f.suffix in _skip_suffixes:
            continue
        rel = f.relative_to(store_dir)
        extra_files.append({
            "path": str(rel),
            "size": f.stat().st_size,
        })
    return extra_files


def _refresh_template_loader() -> None:
    """Refresh the Jinja2 template loader to pick up new/removed cog templates."""
    try:
        from bot.pages._shared import _get_template_loaders, templates
        from jinja2 import ChoiceLoader
        templates.env.loader = ChoiceLoader(_get_template_loaders())
    except Exception as exc:  # noqa: BLE001
        log.warning("template_loader_refresh_failed", error=str(exc))


def _refresh_cog_pages() -> None:
    """Re-import cog page modules so new routes are registered without restart."""
    try:
        from bot.pages import refresh_cog_pages
        refresh_cog_pages()
    except Exception as exc:  # noqa: BLE001
        log.warning("cog_pages_refresh_failed", error=str(exc))


def _ensure_init_files(base_dir: Path, root: Path) -> None:
    """Create __init__.py in base_dir and all parent dirs up to root (exclusive)."""
    for p in base_dir.parents:
        if p == root:
            break
        init = p / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def _validate_cog_import(module_name: str, cog_dir: Path) -> dict:
    """Validate that a cog can be imported in a subprocess.

    Copies the cog into a temp location, tries to import it, and returns
    {'ok': True} or {'error': '...'}.
    """
    # Create a temp directory that mirrors the cogs/ structure
    parts = module_name.split(".")
    if parts[0] == "cogs":
        parts = parts[1:]
    rel_path = Path(*parts)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cogs = Path(tmpdir) / "cogs"
        tmp_cogs.mkdir()
        (tmp_cogs / "__init__.py").write_text("", encoding="utf-8")

        target_dir = tmp_cogs / rel_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        _ensure_init_files(target_dir, Path(tmpdir))

        # Copy the cog files
        for item in cog_dir.iterdir():
            if item.name == "__pycache__":
                continue
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dest))

        # Try importing in a subprocess
        full_module = "cogs." + ".".join(parts[:-1]) + "." + parts[-1] if len(parts) > 1 else "cogs." + parts[0]
        _ensure_init_files(tmp_cogs / rel_path, Path(tmpdir))

        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 f"import sys; sys.path.insert(0, r'{tmpdir}'); "
                 f"import {full_module}; print('OK')"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()[-500:]
                return {"error": f"Import validation failed: {stderr}"}
            return {"ok": True}
        except subprocess.TimeoutExpired:
            return {"error": "Import validation timed out (30s)"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Import validation error: {exc}"}


def _check_host_dependencies(module_name: str) -> dict:
    """Check for host-level dependencies (ffmpeg, etc.) based on cog requirements."""
    store_dir = _resolve_store_dir_for_module(module_name)
    if store_dir is None:
        return {"ok": True}
    req_file = store_dir / "requirements.txt"
    if not req_file.exists():
        return {"ok": True}

    packages = _parse_requirements(req_file)
    warnings: list[str] = []

    _HOST_DEPS = {
        "yt-dlp": ["ffmpeg"],
        "pytube": ["ffmpeg"],
        "discord.py": [],
    }
    for pkg in packages:
        for dep_name, binaries in _HOST_DEPS.items():
            if dep_name.lower() in pkg.lower():
                for binary in binaries:
                    if not shutil.which(binary):
                        warnings.append(f"Host dependency '{binary}' not found (required by pip package '{pkg}')")

    if warnings:
        return {"ok": True, "warnings": warnings}
    return {"ok": True}


def install_cog(module_name: str) -> dict:
    """Install a cog from cogs_store/ to cogs/ directory.

    In release mode: extracts the cog's zip archive to a temp dir, validates,
    and installs from the extracted files.
    In dev mode: copies files directly from the cog's dev directory.
    Temp files are cleaned up automatically.
    Returns {'ok': True} on success, {'error': '...'} on failure.
    """
    log.info("cog_install_start", cog=module_name, dev_mode=_DEV_MODE)

    parts = module_name.split(".")
    store_dir = _resolve_store_dir_for_module(module_name)
    if store_dir is None:
        return {"error": "Cog store unavailable (is the bot offline?)"}
    store_file = store_dir / (parts[-1] + ".py")

    cog_parts = parts if parts[0] == "cogs" else ["cogs"] + parts
    cog_dir = _COGS_DIR.parent / Path(*cog_parts[:-1]) if len(cog_parts) >= 3 else _COGS_DIR.parent / Path(*cog_parts)

    if not store_file.exists():
        return {"error": f"Cog not found in store: {module_name}"}

    log.info("cog_install_store_resolved", cog=module_name, store_dir=str(store_dir), store_file=str(store_file))

    dep_check = _check_host_dependencies(module_name)
    dep_warnings = dep_check.get("warnings", [])

    zip_file: Path | None = None
    if not _DEV_MODE:
        for z in store_dir.glob("*.zip"):
            zip_file = z
            break

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        tmp_target = tmp_root / "cogs" / parts[1] if len(parts) >= 2 else tmp_root / "cogs"
        tmp_target.mkdir(parents=True, exist_ok=True)
        (tmp_root / "cogs" / "__init__.py").write_text("", encoding="utf-8")
        _ensure_init_files(tmp_target, tmp_root)

        if zip_file is not None and zip_file.exists():
            log.info("cog_install_extract_zip", cog=module_name, zip=zip_file.name, size=zip_file.stat().st_size)
            with zipfile.ZipFile(str(zip_file), "r") as zf:
                zf.extractall(str(tmp_target))
            log.info("cog_install_extract_done", cog=module_name, files=[f.name for f in tmp_target.iterdir()])
        else:
            log.info("cog_install_copy_files", cog=module_name, src=str(store_dir))
            for item in store_dir.iterdir():
                if item.name == "__pycache__" or item.suffix == ".zip":
                    continue
                dest = tmp_target / item.name
                if item.is_dir():
                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                else:
                    shutil.copy2(str(item), str(dest))
            log.info("cog_install_copy_done", cog=module_name, files=[f.name for f in tmp_target.iterdir()])

        log.info("cog_install_validating", cog=module_name)
        import_result = _validate_cog_import(module_name, tmp_target)
        if not import_result.get("ok"):
            log.warning("cog_install_validation_failed", cog=module_name, error=import_result.get("error"))
            return {"error": import_result.get("error", "import validation failed")}
        log.info("cog_install_validation_ok", cog=module_name)

        req_file = tmp_target / "requirements.txt"
        if req_file.exists():
            packages = _parse_requirements(req_file)
            if packages:
                log.info("cog_install_pip", cog=module_name, packages=packages)
                pip_result = _pip_install(packages)
                tracking = _load_pkg_tracking()
                tracking[module_name] = packages
                _save_pkg_tracking(tracking)
                if not pip_result.get("ok"):
                    log.warning("cog_pip_install_failed", cog=module_name, error=pip_result.get("error"))
                    return {"ok": True, "warning": f"Cog installed but pip install failed: {pip_result.get('error')}"}
                log.info("cog_install_pip_done", cog=module_name)

        log.info("cog_install_copy_to_cogs", cog=module_name, dest=str(cog_dir))
        cog_dir.mkdir(parents=True, exist_ok=True)
        for item in tmp_target.iterdir():
            if item.name == "__pycache__":
                continue
            dest = cog_dir / item.name
            if item.is_dir():
                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dest))
        log.info("cog_install_copy_to_cogs_done", cog=module_name)

    refresh_cogs_cache()
    refresh_store_cache()
    _refresh_template_loader()
    _refresh_cog_pages()

    log.info("cog_installed", cog=module_name)
    result: dict = {"ok": True}
    if dep_warnings:
        result["warning"] = "; ".join(dep_warnings)
    return result


def uninstall_cog(module_name: str) -> dict:
    """Uninstall a cog — remove it from cogs/ directory and uninstall pip packages.

    The cog remains available in cogs_store/ for reinstallation.
    Pip packages are only uninstalled if no other installed cog still needs them.
    Returns {'ok': True} on success, {'error': '...'} on failure.
    """
    parts = module_name.split(".")
    if parts[0] == "cogs":
        parts = parts[1:]

    cog_file = _COGS_DIR / Path(*parts).with_suffix(".py")

    if not cog_file.exists():
        return {"error": f"Cog not installed: {module_name}"}

    cog_dir = cog_file.parent

    if cog_dir == _COGS_DIR:
        cog_file.unlink()
    else:
        shutil.rmtree(str(cog_dir), ignore_errors=True)
        # Recreate __init__.py if needed for parent dirs
        parent = cog_dir.parent
        while parent != _COGS_DIR and parent.exists():
            init = parent / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
            parent = parent.parent

    # Uninstall pip packages that are no longer needed
    tracking = _load_pkg_tracking()
    cog_packages = tracking.pop(module_name, [])
    if cog_packages:
        still_needed = _get_all_installed_cog_requirements(exclude=module_name)
        to_uninstall = [p for p in cog_packages if p not in still_needed]
        if to_uninstall:
            pip_result = _pip_uninstall(to_uninstall)
            if not pip_result.get("ok"):
                log.warning("cog_pip_uninstall_failed", cog=module_name, error=pip_result.get("error"))
        _save_pkg_tracking(tracking)

    refresh_cogs_cache()
    refresh_store_cache()
    _refresh_template_loader()
    _refresh_cog_pages()

    log.info("cog_uninstalled", cog=module_name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Runtime state — which cogs are currently loaded
# ---------------------------------------------------------------------------

_loaded_cogs: set[str] = set()  # Fully qualified extension names


def get_loaded_cogs() -> list[str]:
    """Return list of fully qualified extension names that are currently loaded."""
    return sorted(_loaded_cogs)


def is_cog_loaded(module_name: str) -> bool:
    """Check if a specific cog module is currently loaded."""
    if module_name.startswith("cogs.") or module_name.startswith("bot."):
        return module_name in _loaded_cogs
    info = get_cog_info(module_name)
    if info:
        return info["module"] in _loaded_cogs
    return False


def get_cog_info(name: str) -> CogInfo | None:
    """Get metadata for a cog by name or module path."""
    all_info = get_all_cog_info()
    for info in all_info:
        if info["module"] == name:
            return info
        if info["name"].lower() == name.lower():
            return info
        # Check short name match (e.g. "moderation" → "Moderation")
        normalized_info = info["name"].lower().replace(" ", "_").replace("/", "_")
        normalized_name = name.lower().replace(" ", "_").replace("/", "_")
        if normalized_info == normalized_name:
            return info
    return None


# ---------------------------------------------------------------------------
# Widget discovery — collect WIDGETS from loaded cog modules
# ---------------------------------------------------------------------------

WidgetInfo = dict[str, str]


def get_available_widgets() -> list[WidgetInfo]:
    """Discover widgets from all loaded cog modules.

    Each cog module may define a ``WIDGETS`` list of dicts:
        {"id": "moderation_recent", "title": "Recent Actions",
         "template": "widgets/moderation_recent.html", "size": "medium"}
    """
    widgets: list[WidgetInfo] = []
    for module_name in sorted(_loaded_cogs):
        try:
            mod = importlib.import_module(module_name)
            cog_widgets = getattr(mod, "WIDGETS", None)
            if cog_widgets and isinstance(cog_widgets, list):
                for w in cog_widgets:
                    if isinstance(w, dict) and "id" in w and "template" in w:
                        w_copy = dict(w)
                        w_copy.setdefault("cog", module_name)
                        w_copy.setdefault("size", "medium")
                        widgets.append(w_copy)
        except Exception as exc:  # noqa: BLE001
            log.warning("widget_discover_failed", module=module_name, error=str(exc))

    return widgets


def _update_loaded_state(module_name: str, loaded: bool) -> None:
    """Update the internal tracking of loaded cogs."""
    if loaded:
        _loaded_cogs.add(module_name)
    else:
        _loaded_cogs.discard(module_name)


# ---------------------------------------------------------------------------
# Load/Unload helpers — used by IPC, admin commands, and web API
# ---------------------------------------------------------------------------


async def _sync_commands_to_guilds(bot: Any) -> None:
    """Sync slash commands to every guild the bot is in.

    Guild commands propagate instantly (unlike global commands which Discord
    caches for up to 1h). We sync globally first (to remove stale global
    commands) then copy the tree to each guild for instant propagation.
    """
    try:
        # Sync globally — this removes any global commands that are no longer
        # in the tree (e.g. from an unloaded cog). Discord caches these for
        # up to 1h, but at least new clients won't see them.
        await bot.tree.sync()
        # Sync to each guild for instant propagation
        for guild in bot.guilds:
            try:
                await bot.tree.sync(guild=guild)
            except Exception as exc:  # noqa: BLE001
                log.warning("guild_sync_failed", guild=guild.id, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("command_sync_failed", error=str(exc))


def _resolve_cog(cog_name: str) -> tuple[CogInfo | None, str]:
    """Resolve a cog name or module path to (info, module_name)."""
    if cog_name.startswith("cogs.") or cog_name.startswith("bot."):
        return get_cog_info(cog_name), cog_name
    info = get_cog_info(cog_name)
    if info is None:
        return None, cog_name
    return info, info["module"]


def _invalidate_cache(cog_name: str) -> None:
    """Invalidate cog state cache after load/unload."""
    try:
        from bot.runtime import invalidate_cog_state_cache
        invalidate_cog_state_cache(cog_name=cog_name.lower())
    except Exception:  # noqa: BLE001
        pass


async def load_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Load a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    if module_name in _loaded_cogs:
        return {"error": f"Cog already loaded: {info['name']}"}

    try:
        await bot.load_extension(module_name)
        _update_loaded_state(module_name, True)
        _invalidate_cache(info["name"])
        await _sync_commands_to_guilds(bot)
        log.info("cog_loaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"], "loaded_by": "dynamic"}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_load_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to load cog '{cog_name}': {exc}"}


async def unload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Unload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    if module_name not in _loaded_cogs:
        return {"error": f"Cog not loaded: {info['name']}"}

    try:
        await bot.unload_extension(module_name)
        _update_loaded_state(module_name, False)
        _invalidate_cache(info["name"])
        await _sync_commands_to_guilds(bot)
        log.info("cog_unloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_unload_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to unload cog '{cog_name}': {exc}"}


async def reload_cog(bot: Any, cog_name: str) -> dict[str, Any]:
    """Reload a single cog by name or module path.

    Returns: {"ok": True} or {"error": "..."}
    """
    info, module_name = _resolve_cog(cog_name)
    if info is None:
        return {"error": f"Unknown cog: {cog_name}"}

    unload_result = await unload_cog(bot, cog_name)
    if not unload_result.get("ok"):
        return {"error": f"Unload failed: {unload_result.get('error', '')}"}

    try:
        await bot.load_extension(module_name)
        _update_loaded_state(module_name, True)
        await _sync_commands_to_guilds(bot)
        log.info("cog_reloaded", cog=info["name"], module=module_name)
        return {"ok": True, "cog": info["name"]}
    except Exception as exc:  # noqa: BLE001
        log.error("cog_reload_failed", cog=cog_name, error=str(exc))
        return {"error": f"Failed to reload cog '{cog_name}': {exc}"}


# ---------------------------------------------------------------------------
# Persistence helpers — save/load which cogs should be loaded after restart
# ---------------------------------------------------------------------------

async def get_persisted_loaded_cogs() -> list[str]:
    """Get the list of cogs that SHOULD be loaded (from DB)."""
    try:
        from bot.database.session import db_session
        from bot.database.models.system.system_config import SystemConfig
        from sqlalchemy import select as sa_select

        async with db_session() as s:
            cfg = await s.scalar(
                sa_select(SystemConfig).where(SystemConfig.id == 1)
            )
            if cfg and hasattr(cfg, "loaded_cogs_v2") and cfg.loaded_cogs_v2:
                return list(cfg.loaded_cogs_v2)
        return []
    except Exception:  # noqa: BLE001
        return []


async def persist_loaded_cogs(cog_names: list[str]) -> None:
    """Save the list of loaded cogs to system_config for persistence across restarts."""
    try:
        from bot.database.session import db_session
        from sqlalchemy import select as sa_select

        async with db_session() as s:
            from bot.database.models.system.system_config import SystemConfig

            cfg = await s.scalar(sa_select(SystemConfig).where(SystemConfig.id == 1))
            if cfg is not None:
                cfg.loaded_cogs_v2 = list(cog_names)
                await s.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("persist_loaded_cogs_failed", error=str(exc))


async def restore_loaded_cogs(bot: Any) -> int:
    """Auto-load all cogs found in the cogs/ directory on startup.

    This is the universal cog loader: any .py file (excluding __init__.py
    and _*.py) in cogs/ and its subdirectories will be loaded.
    The DB persisted list is synced to reflect what was actually loaded.

    Returns the number of cogs that were loaded.
    """
    # First, try to load from persisted DB state (for backwards compat)
    saved = await get_persisted_loaded_cogs()

    # Then, auto-discover and load ALL cogs in the cogs/ directory
    available = _discover_cogs_cached()
    available_modules = [c["module"] for c in available]

    # Merge: load persisted first, then any new ones discovered
    to_load: list[str] = []
    for name in saved:
        if name not in to_load:
            to_load.append(name)
    for name in available_modules:
        if name not in to_load:
            to_load.append(name)

    if not to_load:
        return 0

    count = 0
    for name in to_load:
        if name in _loaded_cogs:
            count += 1
            continue
        result = await load_cog(bot, name)
        if result.get("ok"):
            count += 1
        else:
            log.warning("restore_cog_failed", cog=name, error=result.get("error"))

    # Sync DB to reflect actual loaded state
    await persist_loaded_cogs(get_loaded_cogs())

    return count
