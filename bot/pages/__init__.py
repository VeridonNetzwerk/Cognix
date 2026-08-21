"""HTML view routes package — re-exports router and templates for app.py."""

import importlib
import logging
from pathlib import Path

# Import core (non-cog) sub-modules to register their routes on the shared router
from bot.pages import (  # noqa: F401
    auth,
    cogs,
    dashboard,
    features,
    settings,
    users,
)
from bot.pages._shared import router, templates

# Dynamically load page modules from installed cogs
# Each cog directory in cogs/ may have a pages/ subdirectory with route modules
_COGS_DIR = Path(__file__).resolve().parent.parent.parent / "cogs"

_log = logging.getLogger("web.pages")
_imported_page_modules: set[str] = set()


def refresh_cog_pages() -> None:
    """Re-scan cogs/ for page modules and import any that haven't been loaded yet.

    Called at startup and after cog install/uninstall to ensure page routes
    are registered without requiring an app restart.
    """
    if not _COGS_DIR.exists():
        return
    for cog_subdir in sorted(_COGS_DIR.iterdir()):
        if not cog_subdir.is_dir() or cog_subdir.name.startswith("_"):
            continue
        cog_pages_dir = cog_subdir / "pages"
        if not cog_pages_dir.exists():
            continue
        for py_file in sorted(cog_pages_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod_name = f"cogs.{cog_subdir.name}.pages.{py_file.stem}"
            if mod_name in _imported_page_modules:
                continue
            try:
                importlib.import_module(mod_name)
                _imported_page_modules.add(mod_name)
            except Exception as exc:  # noqa: BLE001
                _log.warning("cog_page_import_failed", module=mod_name, error=str(exc))


refresh_cog_pages()

__all__ = ["router", "templates", "refresh_cog_pages"]
