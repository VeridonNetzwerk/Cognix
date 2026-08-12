"""All ORM models. Importing this package registers them on Base.metadata."""

from bot.database.models.cog_package import CogPackage
from bot.database.models.audit_log import AuditLog
from bot.database.models.backup import Backup
from bot.database.models.bot_profile import BotProfile
from bot.database.models.cog_state import CogState
from bot.database.models.discord_event import DiscordEvent, DiscordEventType
from bot.database.models.discord_message_cache import DiscordMessageCache
from bot.database.models.embed_template import EmbedTemplate
from bot.database.models.giveaway import Giveaway, GiveawayStatus
from bot.database.models.invite_stats import InviteStats
from bot.database.models.invite_uses import InviteUse
from bot.database.models.moderation import ModerationAction, ModerationActionType, Warning_
from bot.database.models.music_playlist import MusicPlaylist
from bot.database.models.music_play_history import MusicPlayHistory
from bot.database.models.role_permission import RolePermission
from bot.database.models.server import Server
from bot.database.models.server_cog_state import ServerCogState
from bot.database.models.server_config import ServerConfig
from bot.database.models.server_event_config import ServerEventConfig
from bot.database.models.stats import AggregatedStat, StatEvent, StatEventType
from bot.database.models.system_config import SystemConfig
from bot.database.models.ticket import Ticket, TicketMessage, TicketStatus
from bot.database.models.ticket_panel import TicketPanel, TicketType
from bot.database.models.user import DiscordUser
from bot.database.models.web_user import (
    BackupCode,
    RefreshToken,
    WebRole,
    WebUser,
)
from bot.database.models.web_user_settings import (
    MODULES,
    PermissionLevel,
    WebUserModulePermission,
    WebUserSettings,
)

__all__ = [
    "MODULES",
    "AggregatedStat",
    "AuditLog",
    "Backup",
    "BackupCode",
    "BotProfile",
    "CogPackage",
    "CogState",
    "DiscordEvent",
    "DiscordEventType",
    "DiscordMessageCache",
    "DiscordUser",
    "EmbedTemplate",
    "Giveaway",
    "GiveawayStatus",
    "InviteStats",
    "InviteUse",
    "ModerationAction",
    "ModerationActionType",
    "MusicPlaylist",
    "MusicPlayHistory",
    "PermissionLevel",
    "RefreshToken",
    "RolePermission",
    "Server",
    "ServerCogState",
    "ServerConfig",
    "ServerEventConfig",
    "StatEvent",
    "StatEventType",
    "SystemConfig",
    "Ticket",
    "TicketMessage",
    "TicketPanel",
    "TicketStatus",
    "TicketType",
    "Warning_",
    "WebRole",
    "WebUser",
    "WebUserModulePermission",
    "WebUserSettings",
]
