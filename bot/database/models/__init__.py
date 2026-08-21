"""All ORM models. Importing this package registers them on Base.metadata."""

from bot.database.models.cogs.cog_package import CogPackage
from bot.database.models.auth.audit_log import AuditLog
from bot.database.models.backups.backup import Backup
from bot.database.models.content.bot_profile import BotProfile
from bot.database.models.cogs.cog_state import CogState
from bot.database.models.stats.discord_event import DiscordEvent, DiscordEventType
from bot.database.models.stats.discord_message_cache import DiscordMessageCache
from bot.database.models.content.embed_template import EmbedTemplate
from bot.database.models.giveaways.giveaway import Giveaway, GiveawayStatus
from bot.database.models.invites.invite_stats import InviteStats
from bot.database.models.invites.invite_uses import InviteUse
from bot.database.models.moderation.moderation import ModerationAction, ModerationActionType, Warning_
from bot.database.models.music.music_playlist import MusicPlaylist
from bot.database.models.music.music_play_history import MusicPlayHistory
from bot.database.models.music.music_settings import MusicSettings
from bot.database.models.reaction_roles.reaction_role import ReactionRoleMessage
from bot.database.models.auth.role_permission import RolePermission
from bot.database.models.server.server import Server
from bot.database.models.server.server_cog_state import ServerCogState
from bot.database.models.server.server_config import ServerConfig
from bot.database.models.server.server_event_config import ServerEventConfig
from bot.database.models.stats.stats import AggregatedStat, StatEvent, StatEventType
from bot.database.models.system.system_config import SystemConfig
from bot.database.models.tickets.ticket import Ticket, TicketMessage, TicketStatus
from bot.database.models.tickets.ticket_panel import TicketPanel, TicketType
from bot.database.models.system.user import DiscordUser
from bot.database.models.auth.web_user import (
    BackupCode,
    RefreshToken,
    WebRole,
    WebUser,
)
from bot.database.models.auth.user_dashboard_widget import UserDashboardWidget
from bot.database.models.auth.web_user_settings import (
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
    "MusicSettings",
    "PermissionLevel",
    "ReactionRoleMessage",
    "RefreshToken",
    "UserDashboardWidget",
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
