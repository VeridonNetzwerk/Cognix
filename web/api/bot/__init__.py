from web.api.bot.bot_control import router as bot_control_router
from web.api.bot.cogs import router as cogs_router
from web.api.bot.dashboard import router as dashboard_router

__all__ = ["bot_control_router", "cogs_router", "dashboard_router"]
