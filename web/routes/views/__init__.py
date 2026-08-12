"""HTML view routes package — re-exports router and templates for app.py."""

# Import all sub-modules to register their routes on the shared router
from web.routes.views import (  # noqa: F401
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
from web.routes.views._shared import router, templates

__all__ = ["router", "templates"]
