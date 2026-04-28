"""Seed default global embed templates so they appear in the dashboard."""

from __future__ import annotations

from sqlalchemy import select

from database.models.embed_template import EmbedTemplate
from database.session import db_session

DEFAULT_TEMPLATES: list[dict] = [
    {
        "key": "info",
        "title": "Bot Information",
        "description": "🟢 **Bot Status:** Online\n_(0 errors / 0 warnings)_",
        "color": 0x60A5FA,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "ticket_panel",
        "title": "Support Tickets",
        "description": (
            "Click the button below to open a private support ticket.\n"
            "A staff member will be with you shortly."
        ),
        "color": 0x60A5FA,
        "footer_text": "Powered by Cognix · Made by 食べ物",
        "extras": {"button_label": "Open ticket", "button_emoji": "🎫"},
    },
    {
        "key": "ticket_opened",
        "title": "Ticket opened",
        "description": "Hi {user_mention}, support has been notified.\nUse the buttons below to manage this ticket.",
        "color": 0x4ADE80,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "ticket_closed",
        "title": "Ticket closed",
        "description": "Closed by {closer_mention}. Archiving the thread...",
        "color": 0xF59E0B,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "welcome",
        "title": "Welcome {user}!",
        "description": "Glad to have you here, {user_mention}.",
        "color": 0x4ADE80,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "level_up",
        "title": "Level up! 🎉",
        "description": "{user_mention} reached level **{level}**.",
        "color": 0xFACC15,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "music_now_playing",
        "title": "Now playing",
        "description": "**{title}**\n{artist}",
        "color": 0x8B5CF6,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "moderation_action",
        "title": "Moderation action",
        "description": "**{action}** against {target}\nReason: {reason}",
        "color": 0xEF4444,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
]


async def seed_default_embed_templates() -> int:
    """Insert any missing global ``EmbedTemplate`` rows. Returns count inserted."""
    inserted = 0
    async with db_session() as s:
        for tpl in DEFAULT_TEMPLATES:
            exists = await s.scalar(
                select(EmbedTemplate.id).where(
                    EmbedTemplate.key == tpl["key"],
                    EmbedTemplate.server_id.is_(None),
                )
            )
            if exists is not None:
                continue
            row = EmbedTemplate(
                server_id=None,
                key=tpl["key"],
                enabled=True,
                title=tpl.get("title", ""),
                description=tpl.get("description", ""),
                color=tpl.get("color", 0x60A5FA),
                footer_text=tpl.get("footer_text", ""),
                footer_icon_url="",
                thumbnail_url="",
                image_url="",
                author_name="",
                author_icon_url="",
                author_url="",
                fields=tpl.get("fields", []),
                extras=tpl.get("extras", {}),
            )
            s.add(row)
            inserted += 1
    return inserted
