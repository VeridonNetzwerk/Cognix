from web.api.bot.bot_control import router as bot_control_router
from web.api.bot.cogs import router as cogs_router
from web.api.bot.marketplace import router as marketplace_router

__all__ = ["bot_control_router", "cogs_router", "marketplace_router"]
