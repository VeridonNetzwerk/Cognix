"""HTML view routes package — re-exports router and templates for app.py."""

# Import all sub-modules to register their routes on the shared router
from bot.pages import (  # noqa: F401
    audit,
    auth,
    backups,
    cogs,
    dashboard,
    features,
    giveaways,
    music,
    settings,
    tickets,
    users,
)
from bot.pages._shared import router, templates

__all__ = ["router", "templates"]
