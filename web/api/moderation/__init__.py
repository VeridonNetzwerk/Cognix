from web.api.moderation.moderation import router as moderation_router
from web.api.moderation.tickets import router as tickets_router
from web.api.moderation.backups import router as backups_router

__all__ = ["moderation_router", "tickets_router", "backups_router"]
