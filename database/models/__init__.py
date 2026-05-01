"""All ORM models. Importing this package registers them on Base.metadata."""

from database.models.audit_log import AuditLog
from database.models.backup import Backup
from database.models.bot_profile import BotProfile
from database.models.cog_state import CogState
from database.models.discord_event import DiscordEvent, DiscordEventType
from database.models.discord_message_cache import DiscordMessageCache
from database.models.embed_template import EmbedTemplate
from database.models.giveaway import Giveaway, GiveawayStatus
from database.models.invite_stats import InviteStats
from database.models.invite_uses import InviteUse
from database.models.moderation import ModerationAction, ModerationActionType, Warning_
from database.models.music_playlist import MusicPlaylist
from database.models.music_play_history import MusicPlayHistory
from database.models.role_permission import RolePermission
from database.models.server import Server
from database.models.server_cog_state import ServerCogState
from database.models.server_config import ServerConfig
from database.models.server_event_config import ServerEventConfig
from database.models.stats import AggregatedStat, StatEvent, StatEventType
from database.models.system_config import SystemConfig
from database.models.ticket import Ticket, TicketMessage, TicketStatus
from database.models.ticket_panel import TicketPanel, TicketType
from database.models.user import DiscordUser
from database.models.web_user import (
    BackupCode,
    RefreshToken,
    WebRole,
    WebUser,
)
from database.models.web_user_settings import (
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
