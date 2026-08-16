"""HTML view routes package — re-exports router and templates for app.py."""

import importlib
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
_COGS_DIR = Path(__file__).resolve().parent.parent / "cogs"

if _COGS_DIR.exists():
    for cog_subdir in sorted(_COGS_DIR.iterdir()):
        if not cog_subdir.is_dir() or cog_subdir.name.startswith("_"):
            continue
        cog_pages_dir = cog_subdir / "pages"
        if not cog_pages_dir.exists():
            continue
        # Look for .py files (except __init__.py) and import them
        for py_file in sorted(cog_pages_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod_name = f"cogs.{cog_subdir.name}.pages.{py_file.stem}"
            try:
                importlib.import_module(mod_name)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger("web.pages").warning(
                    "cog_page_import_failed", module=mod_name, error=str(exc)
                )

__all__ = ["router", "templates"]
